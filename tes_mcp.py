"""MCP server for submitting file-creation tasks to a TES endpoint."""

import asyncio
import json
import logging
import os
import shlex
from typing import Any

import httpx2

from mcp.server import MCPServer

logger = logging.getLogger(__name__)
mcp = MCPServer("minio-task-server")


def _required_setting(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


def _submit_task(payload: dict[str, Any]) -> dict[str, Any]:
    tes_url = _required_setting("TES_URL").rstrip("/")
    username = _required_setting("TES_USERNAME")
    password = _required_setting("TES_PASSWORD")

    try:
        response = httpx2.post(
            f"{tes_url}/tasks",
            json=payload,
            auth=(username, password),
            headers={"Accept": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        response_body = response.text
    except httpx2.HTTPStatusError as error:
        detail = error.response.text
        raise RuntimeError(
            f"TES returned HTTP {error.response.status_code}: {detail}"
        ) from error
    except httpx2.RequestError as error:
        raise RuntimeError(f"Could not reach TES endpoint: {error}") from error

    if not response_body:
        return {"status": "submitted"}

    try:
        return json.loads(response_body)
    except json.JSONDecodeError:
        return {"status": "submitted", "response": response_body}


@mcp.tool()
async def create_empty_file(file_name: str) -> str:
    """Submit a task that creates an empty file in the requested output directory.

    The output directory and URL are configured through OUTPUT_PATH and OUTPUT_URL
    in the MCP environment file. The file name is provided when calling the tool.
    """
    output_path = _required_setting("OUTPUT_PATH")
    output_url = _required_setting(
        "OUTPUT_URL"
    )  # add session ID here, should know it automatically from the header
    if not file_name.strip():
        raise ValueError("file_name must not be empty")
    if not output_path.strip():
        raise ValueError("output_path must not be empty")
    if not output_url.strip():
        raise ValueError("output_url must not be empty")

    payload = {
        "name": "create-empty-file",
        "inputs": [],
        "outputs": [
            {
                "path": output_path,
                "url": output_url,
                "type": "DIRECTORY",
            }
        ],
        "executors": [
            {
                "image": "ubuntu:20.04",
                "command": [
                    "/bin/sh",
                    "-c",
                    f"touch {shlex.quote(output_path.rstrip('/') + '/' + file_name)}",
                ],
            }
        ],
    }

    logger.info("Submitting create-empty-file task for %s", output_path)
    result = await asyncio.to_thread(_submit_task, payload)
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="stdio")
