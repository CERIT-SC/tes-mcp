"""MCP server for submitting file-creation tasks to a TES endpoint."""

import asyncio
import base64
import json
import logging
import uuid
from typing import Any
from urllib.parse import quote

import httpx2
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
    output_path: str = Field(min_length=1)
    output_url: AnyUrl
    output_browse_url: AnyHttpUrl | None = Field(
        default="https://minio-kovac-ns.dyn.cloud.e-infra.cz",
        validate_default=True,
    )
    session_id: str | None = None
    session_id_header_key: str = Field(default="MCP-Session-Id", min_length=1)
    executor_image: str = Field(default="ubuntu:20.04", min_length=1)


logger = logging.getLogger(__name__)
mcp = MCPServer("tes")
settings = Settings()  # type: ignore[call-arg]


@mcp.tool()
async def run_script(
    script: str,
    ctx: Context,
) -> str:
    """Run a shell script remotely and save its output directory.

    Use this tool whenever the user asks to execute a command or script, or
    create files from command output.

    The output directory and URL are configured through OUTPUT_PATH and OUTPUT_URL
    in the MCP environment file. The script runs with OUTPUT_PATH as its working
    directory, and everything it writes there is uploaded to OUTPUT_URL/<session
    id> when the task completes.

    The response includes that location as output_url: a clickable link to the
    session's output directory when OUTPUT_BROWSE_URL is configured, otherwise
    the s3:// URL itself. Give output_url to the user as the link to the saved
    files. The task may still be running when this tool returns; use get_task to
    follow its status.
    """
    output_path = settings.output_path
    output_url = str(settings.output_url)
    if not script.strip():
        raise ValueError("script must not be empty")

    session_id = _get_session_id(ctx) or uuid.uuid4().hex

    output_directory_url = output_url.rstrip("/") + "/" + session_id
    payload = {
        "name": "run-script",
        "tags": {"MCP-Session-Id": session_id},
        "inputs": [
            {
                "path": output_path,
                "url": output_directory_url,
                "type": "DIRECTORY",
            }
        ],
        "outputs": [
            {
                "path": output_path,
                "url": output_directory_url,
                "type": "DIRECTORY",
            }
        ],
        "executors": [
            {
                "image": settings.executor_image,
                "workdir": output_path,
                "command": [
                    "/bin/sh",
                    "-c",
                    f"{script}",
                ],
            }
        ],
    }

    logger.info("Submitting run-script task for %s", output_path)
    result = await asyncio.to_thread(_make_tes_request, "post", json=payload)
    return json.dumps(
        {
            "task": result,
            "output_url": _get_output_link(output_url, session_id),
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


def _get_output_link(output_url: str, session_id: str) -> str:
    """Return a link to the session's output directory.

    OUTPUT_URL is the location handed to TES. When it points at S3 and
    OUTPUT_BROWSE_URL names an S3 console, build the console's browse URL:
    {console}/buckets/{bucket}/browse/{base64 of the key without the bucket,
    ending in a slash}. Otherwise fall back to the OUTPUT_URL itself.
    """
    output_directory_url = output_url.rstrip("/") + "/" + session_id
    browse_url = settings.output_browse_url
    if not browse_url or not output_url.startswith("s3://"):
        return output_directory_url + "/"

    bucket, _, prefix = output_url[len("s3://") :].rstrip("/").partition("/")
    if not bucket:
        return output_directory_url + "/"

    key = "/".join(part for part in (prefix, session_id) if part) + "/"
    encoded_key = base64.b64encode(key.encode()).decode()
    return f"{str(browse_url).rstrip('/')}/buckets/{bucket}/browse/{encoded_key}"


def _get_session_id(ctx: Context, default: str | None = None) -> str | None:
    """Return the configured session ID, or the one supplied by the request."""
    if settings.session_id:
        return settings.session_id
    session_id = (ctx.headers or {}).get(settings.session_id_header_key)
    return session_id or default


def _get_task_path(task_id: str, suffix: str = "") -> str:
    """Return the TES path for a task, optionally with a suffix."""
    if not task_id.strip():
        raise ValueError("task_id must not be empty")
    return f"/tasks/{quote(task_id, safe='')}{suffix}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8001, stateless_http=True)
