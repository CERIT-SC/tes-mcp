"""MCP server for submitting file-creation tasks to a TES endpoint."""

import asyncio
import json
import logging
import os
import uuid
from typing import Any
from urllib.parse import quote

import httpx2
from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

logger = logging.getLogger(__name__)
mcp = MCPServer("minio-task-server")


@mcp.tool()
async def run_script(
    script: str,
    ctx: Context,
) -> str:
    """Submit a task that runs a shell script and saves its output.

    The output directory and URL are configured through OUTPUT_PATH and OUTPUT_URL
    in the MCP environment file. The script and optional output file name are
    provided when calling the tool. The script's standard output is saved to the
    output file.
    """
    output_path = _get_required_setting("OUTPUT_PATH")
    output_url = _get_required_setting("OUTPUT_URL")
    if not script.strip():
        raise ValueError("script must not be empty")
    if not output_path.strip():
        raise ValueError("output_path must not be empty")
    if not output_url.strip():
        raise ValueError("output_url must not be empty")

    session_id = (ctx.headers or {}).get("MCP-Session-Id", uuid.uuid4().hex)

    output_file_url = output_url.rstrip("/") + "/" + session_id
    payload = {
        "name": "run-script",
        "inputs": [
            {
                "path": output_path,
                "url": output_file_url,
                "type": "DIRECTORY",
            }
        ],
        "outputs": [
            {
                "path": output_path,
                "url": output_file_url,
                "type": "DIRECTORY",
            }
        ],
        "executors": [
            {
                "image": "ubuntu:20.04",
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
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_tasks() -> str:
    """Return the full list of tasks from the TES endpoint."""
    result = await asyncio.to_thread(
        _make_tes_request,
        "get",
        params={"view": "FULL", "page_size": 100},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_service_info() -> str:
    """Return service information from the TES endpoint."""
    result = await asyncio.to_thread(_make_tes_request, "get", path="/service-info")
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_task(task_id: str) -> str:
    """Return full details for a TES task."""
    result = await asyncio.to_thread(
        _make_tes_request,
        "get",
        path=_get_task_path(task_id),
        params={"view": "FULL"},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def cancel_task(task_id: str) -> str:
    """Cancel a TES task and return the endpoint response."""
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
    tes_url = _get_required_setting("TES_URL").rstrip("/")
    username = _get_required_setting("TES_USERNAME")
    password = _get_required_setting("TES_PASSWORD")

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


def _get_required_setting(name: str) -> str:
    """Get a required environment variable, raising an error if it is not set."""
    if value := os.getenv(name):
        return value
    raise RuntimeError(f"Required environment variable {name} is not set.")


def _get_task_path(task_id: str, suffix: str = "") -> str:
    """Return the TES path for a task, optionally with a suffix."""
    if not task_id.strip():
        raise ValueError("task_id must not be empty")
    return f"/tasks/{quote(task_id, safe='')}{suffix}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8001, stateless_http=True)
