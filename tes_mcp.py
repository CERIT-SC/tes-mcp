"""MCP server for submitting file-creation tasks to a TES endpoint."""

import asyncio
import json
import logging
import os
import shlex
from typing import Any
from uuid import uuid4

import httpx2
from mcp.server import MCPServer

logger = logging.getLogger(__name__)
mcp = MCPServer("minio-task-server")


def _get_required_setting(name: str) -> str:
    """Get a required environment variable, raising an error if it is not set."""
    if value := os.getenv(name):
        return value
    raise RuntimeError(f"Required environment variable {name} is not set.")


def _submit_task(payload: dict[str, Any]) -> dict[str, Any]:
    """Submit a task to the TES endpoint and return the response as a dictionary."""
    tes_url = _get_required_setting("TES_URL").rstrip("/")
    username = _get_required_setting("TES_USERNAME")
    password = _get_required_setting("TES_PASSWORD")

    try:
        response = httpx2.post(
            f"{tes_url}/tasks",
            json=payload,
            auth=(username, password),
            headers={"Accept": "application/json"},
            timeout=30,
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
        return {"status": "submitted", "response": response.text}


@mcp.tool()
async def run_script(script: str, output_file_name: str | None = None) -> str:
    """Submit a task that runs a shell script and saves its output.

    The output directory and URL are configured through OUTPUT_PATH and OUTPUT_URL
    in the MCP environment file. The script and optional output file name are
    provided when calling the tool. The script's standard output is saved to the
    output file.
    """
    output_path = _get_required_setting("OUTPUT_PATH")
    output_url = _get_required_setting(
        "OUTPUT_URL"
    )
    if not script.strip():
        raise ValueError("script must not be empty")
    if not output_path.strip():
        raise ValueError("output_path must not be empty")
    if not output_url.strip():
        raise ValueError("output_url must not be empty")

    output_file_name = output_file_name.strip() if output_file_name else ""
    if not output_file_name:
        output_file_name = f"results-{uuid4().hex}.txt"
    output_file_path = output_path.rstrip("/") + "/" + output_file_name
    output_file_url = output_url.rstrip("/") + "/" + output_file_name
    payload = {
        "name": "run-script",
        "inputs": [],
        "outputs": [
            {
                "path": output_file_path,
                "url": output_file_url,
                "type": "FILE",
            }
        ],
        "executors": [
            {
                "image": "ubuntu:20.04",
                "command": [
                    "/bin/sh",
                    "-c",
                    f"exec > {shlex.quote(output_file_path)}\n{script}",
                ],
            }
        ],
    }

    logger.info("Submitting run-script task for %s", output_file_path)
    result = await asyncio.to_thread(_submit_task, payload)
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="stdio")
