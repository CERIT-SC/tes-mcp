import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "mcp"))

import tes_mcp


@pytest.fixture
def submitted_task(monkeypatch):
    submitted = {}

    def fake_submit_task(payload):
        submitted.update(payload)
        return {"id": "task-123"}

    monkeypatch.setattr(tes_mcp, "_submit_task", fake_submit_task)
    return submitted


def test_run_script_submits_response(monkeypatch, submitted_task):
    monkeypatch.setenv("OUTPUT_PATH", "/results")
    monkeypatch.setenv("OUTPUT_URL", "s3://bucket/results")
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})

    result = asyncio.run(tes_mcp.run_script("echo 2", ctx=context))

    assert json.loads(result) == {"id": "task-123"}
    assert submitted_task["outputs"][0] == {
        "path": "/results",
        "url": "s3://bucket/results/session-123",
        "type": "DIRECTORY",
    }
    assert submitted_task["executors"][0]["command"] == [
        "/bin/sh",
        "-c",
        "echo 2",
    ]


def test_run_script_uses_configured_output_directory(monkeypatch, submitted_task):
    monkeypatch.setenv("OUTPUT_PATH", "/results")
    monkeypatch.setenv("OUTPUT_URL", "s3://bucket/results")
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})

    asyncio.run(tes_mcp.run_script("echo 2", ctx=context))

    assert submitted_task["inputs"][0]["path"] == "/results"
    assert submitted_task["inputs"][0]["type"] == "DIRECTORY"


def test_run_script_uses_session_id_from_context(monkeypatch, submitted_task):
    monkeypatch.setenv("OUTPUT_PATH", "/results")
    monkeypatch.setenv("OUTPUT_URL", "s3://bucket/results")
    context = SimpleNamespace(headers={"MCP-Session-Id": "request-session"})

    asyncio.run(tes_mcp.run_script("echo 2", ctx=context))

    assert submitted_task["outputs"][0]["url"] == (
        "s3://bucket/results/request-session"
    )
