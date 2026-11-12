"""MCP server for submitting file-creation tasks to a TES endpoint."""

import asyncio
import json
import logging
import posixpath
import re
import uuid
from typing import Any
from urllib.parse import quote, urlsplit

import boto3  # type: ignore[import-untyped]
import httpx2
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from pydantic import AnyHttpUrl, AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    tes_url: AnyHttpUrl
    tes_username: str = Field(min_length=1)
    tes_password: str = Field(min_length=1)
    output_path: str = Field(default="/data", min_length=1)
    output_url: AnyUrl
    s3_endpoint_url: AnyHttpUrl = Field(min_length=1)
    s3_access_key_id: str = Field(min_length=1)
    s3_secret_access_key: str = Field(min_length=1)
    s3_region: str = Field(default="us-east-1", min_length=1)
    presigned_url_expiration: int = Field(default=3600, gt=0, le=604800)
    session_id: str | None = None
    session_id_header_key: str = Field(default="MCP-Session-Id", min_length=1)
    executor_image: str = Field(default="ubuntu:20.04", min_length=1)


logger = logging.getLogger(__name__)
mcp = MCPServer("tes")
settings = Settings()  # type: ignore[call-arg]
_TERMINAL_TASK_STATES = frozenset(
    {"COMPLETE", "EXECUTOR_ERROR", "SYSTEM_ERROR", "CANCELED"}
)
_MAX_SLEEP_SECONDS = 300


@mcp.tool()
async def run_script(
    script: str,
    ctx: Context,
    output_file_name: str,
) -> str:
    """Run a shell script and return a temporary URL for its output file.

    Scripts run asynchronously; do not use sleep or wait commands.
    Sleeping only keeps containers alive without any effect.
    """
    if not script.strip():
        raise ValueError("script must not be empty")

    session_id = _get_session_id(ctx) or uuid.uuid4().hex

    output_file_url = _get_session_output_url(session_id)
    payload = {
        "name": "run-script",
        "tags": {"MCP-Session-Id": session_id},
        "inputs": [
            {
                "path": settings.output_path,
                "url": output_file_url,
                "type": "DIRECTORY",
            }
        ],
        "outputs": [
            {
                "path": settings.output_path,
                "url": output_file_url,
                "type": "DIRECTORY",
            }
        ],
        "executors": [
            {
                "image": settings.executor_image,
                "workdir": settings.output_path,
                "command": [
                    "/bin/sh",
                    "-c",
                    script,
                ],
            }
        ],
    }

    logger.info("Submitting run-script task for %s", settings.output_path)
    result = await asyncio.to_thread(_make_tes_request, "post", json=payload)
    output_object_key = _get_output_object_key(session_id, output_file_name)
    output_presigned_url = await asyncio.to_thread(
        _generate_presigned_url,
        output_object_key,
    )
    return json.dumps(
        {
            "task": result,
            "output_url": output_presigned_url,
            "output_object_key": output_object_key,
            "expires_in": settings.presigned_url_expiration,
        },
        indent=2,
    )


@mcp.tool()
async def list_tasks(ctx: Context) -> str:
    """List tasks submitted during the current MCP session."""
    if session_id := _get_session_id(ctx):
        result = await asyncio.to_thread(
            _make_tes_request,
            "get",
            params={
                "view": "FULL",
                "page_size": 100,
                "tag_key": ["MCP-Session-Id"],
                "tag_value": [session_id],
            },
        )
        return json.dumps(result, indent=2)
    raise ValueError("Session ID is missing. Cannot list tasks without a session ID.")


@mcp.tool()
async def get_presigned_url(object_key: str, ctx: Context) -> str:
    """Return a temporary GET URL for an object in this session's output directory."""
    if session_id := _get_session_id(ctx):
        key = _get_output_object_key(session_id, object_key)
        await asyncio.to_thread(_ensure_object_exists, key)
        url = await asyncio.to_thread(_generate_presigned_url, key)
        return json.dumps(
            {
                "url": url,
                "object_key": key,
                "expires_in": settings.presigned_url_expiration,
            },
            indent=2,
        )
    raise ValueError(
        "Session ID is missing. Cannot create a presigned URL without a session ID."
    )


@mcp.tool()
async def get_session_files_presigned_url(ctx: Context) -> str:
    """Get a download URL for all session files.

    Everything is handled in one call; no extra tasks or verification needed.
    """
    if session_id := _get_session_id(ctx):
        archive_name = f"session-files_{session_id}.tar.gz"
        archive_output_path = "/archive"
        source_path = settings.output_path
        payload = {
            "name": "tar-session-files",
            "tags": {"MCP-Session-Id": session_id},
            "inputs": [
                {
                    "path": source_path,
                    "url": _get_session_output_url(session_id),
                    "type": "DIRECTORY",
                }
            ],
            "outputs": [
                {
                    "path": archive_output_path,
                    "url": _get_session_output_url(session_id),
                    "type": "DIRECTORY",
                }
            ],
            "executors": [
                {
                    "image": settings.executor_image,
                    "workdir": source_path,
                    "command": [
                        "/bin/sh",
                        "-c",
                        f"tar --exclude=./{archive_name} -czf {archive_output_path}/{archive_name} -C {source_path} .",
                    ],
                }
            ],
        }
        task = await asyncio.to_thread(_make_tes_request, "post", json=payload)
        await wait_for_task_finish(task["id"])
        archive_object_key = _get_output_object_key(session_id, archive_name)
        await asyncio.to_thread(_ensure_object_exists, archive_object_key)
        archive_url = await asyncio.to_thread(
            _generate_presigned_url,
            archive_object_key,
        )
        return json.dumps(
            {
                "url": archive_url,
                "object_key": archive_object_key,
                "expires_in": settings.presigned_url_expiration,
            },
            indent=2,
        )
    raise ValueError(
        "Session ID is missing. Cannot create a session archive without a session ID."
    )


@mcp.tool()
async def get_service_info() -> str:
    """Return information about the remote execution service."""
    result = await asyncio.to_thread(_make_tes_request, "get", path="/service-info")
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_task(task_id: str) -> str:
    """Return full details and the current status of a submitted task."""
    result = await asyncio.to_thread(
        _make_tes_request,
        "get",
        path=_get_task_path(task_id),
        params={"view": "FULL"},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def sleep(seconds: float) -> str:
    """Wait for up to 300 seconds before returning."""
    if seconds < 0:
        raise ValueError("seconds must not be negative")
    if seconds > _MAX_SLEEP_SECONDS:
        raise ValueError("seconds must not exceed 300")

    await asyncio.sleep(seconds)
    return json.dumps({"status": "ok", "slept_seconds": seconds}, indent=2)


@mcp.tool()
async def wait_for_task_finish(task_id: str) -> str:
    """Wait until a submitted task reaches a terminal state."""
    task_path = _get_task_path(task_id)
    while True:
        result = await asyncio.to_thread(
            _make_tes_request,
            "get",
            path=task_path,
            params={"view": "FULL"},
        )
        if _is_task_finished(result):
            return json.dumps(result, indent=2)
        await asyncio.sleep(1)


@mcp.tool()
async def cancel_task(task_id: str) -> str:
    """Cancel a submitted remote execution task."""
    result = await asyncio.to_thread(
        _make_tes_request,
        "post",
        path=_get_task_path(task_id, ":cancel"),
    )
    return json.dumps(result, indent=2)


def _make_tes_request(
    method: str,
    path: str = "/tasks",
    **request_kwargs: Any,
) -> dict[str, Any]:
    """Send an authenticated request to TES and return its response."""
    tes_url = str(settings.tes_url).rstrip("/")
    username = settings.tes_username
    password = settings.tes_password

    try:
        response = getattr(httpx2, method)(
            f"{tes_url}{path}",
            auth=(username, password),
            headers={"Accept": "application/json"},
            timeout=30,
            **request_kwargs,
        )
        response.raise_for_status()
    except httpx2.HTTPStatusError as error:
        detail = error.response.text
        raise RuntimeError(
            f"TES returned HTTP {error.response.status_code}: {detail}"
        ) from error
    except httpx2.RequestError as error:
        raise RuntimeError(f"Could not reach TES endpoint: {error}") from error
    try:
        return json.loads(response.text)
    except json.JSONDecodeError:
        if method == "post":
            return {"status": "submitted", "response": response.text}
        return {"response": response.text}


def _get_session_id(ctx: Context, default: str | None = None) -> str | None:
    """Return the validated session ID, or the one supplied by the request."""
    session_id = settings.session_id or (ctx.headers or {}).get(
        settings.session_id_header_key
    )
    session_id = session_id or default
    if session_id is None:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]+", session_id):
        raise ValueError(
            "session_id must contain only letters, digits, underscores, and hyphens"
        )
    return session_id


def _get_task_path(task_id: str, suffix: str = "") -> str:
    """Return the TES path for a task, optionally with a suffix."""
    if not task_id.strip():
        raise ValueError("task_id must not be empty")
    return f"/tasks/{quote(task_id, safe='')}{suffix}"


def _is_task_finished(task: dict[str, Any]) -> bool:
    """Return whether a TES task has reached a terminal state."""
    state = task.get("state") or task.get("status")
    return isinstance(state, str) and state.upper() in _TERMINAL_TASK_STATES


def _get_output_object_key(session_id: str, object_key: str) -> str:
    """Return a safe object key below the session's output directory."""
    object_key = object_key.strip("/")
    if not object_key or any(part in {"", ".", ".."} for part in object_key.split("/")):
        raise ValueError("object_key must be a non-empty relative object key")
    return posixpath.join(_get_session_id_prefix(session_id), object_key)


def _get_session_id_prefix(session_id: str) -> str:
    """Return the configured S3 output prefix for a session."""
    prefix = urlsplit(str(settings.output_url)).path.strip("/")
    return posixpath.join(prefix, session_id)


def _get_session_output_url(session_id: str) -> str:
    """Return the S3 URL for a session's output directory."""
    return str(settings.output_url).rstrip("/") + "/" + session_id


def _get_output_bucket() -> str:
    """Return the S3 bucket from the configured output URL."""
    if bucket := urlsplit(str(settings.output_url)).netloc:
        return bucket
    raise ValueError("OUTPUT_URL must include an S3 bucket")


def _get_s3_client() -> Any:
    """Return a configured S3 client."""
    return boto3.client(
        "s3",
        endpoint_url=str(settings.s3_endpoint_url),
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _ensure_object_exists(key: str) -> None:
    """Raise an explicit error unless the configured S3 object exists."""
    try:
        _get_s3_client().head_object(Bucket=_get_output_bucket(), Key=key)
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            raise FileNotFoundError(f"S3 object does not exist: {key}") from error
        raise RuntimeError(f"Unable to verify S3 object: {key}") from error


def _generate_presigned_url(key: str) -> str:
    """Generate a temporary read URL for an S3 object."""
    client = _get_s3_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": _get_output_bucket(), "Key": key},
        ExpiresIn=settings.presigned_url_expiration,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8001, stateless_http=True)
