import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "mcp"))

import tes_mcp


@pytest.fixture
def tes_request(monkeypatch):
    request = {}

    def fake_tes_request(method, path="/tasks", **kwargs):
        request.update(method=method, path=path, **kwargs)
        return {"id": "task-123"}

    monkeypatch.setattr(tes_mcp, "_make_tes_request", fake_tes_request)
    return request


def test_run_script_submits_response(monkeypatch, tes_request):
    monkeypatch.setenv("OUTPUT_PATH", "/results")
    monkeypatch.setenv("OUTPUT_URL", "s3://bucket/results")
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})

    result = asyncio.run(tes_mcp.run_script("echo 2", ctx=context))

    assert json.loads(result) == {"id": "task-123"}
    assert tes_request["method"] == "post"
    assert tes_request["path"] == "/tasks"
    assert tes_request["json"]["tags"] == {"MCP-Session-Id": "session-123"}
    assert tes_request["json"]["outputs"][0] == {
        "path": "/results",
        "url": "s3://bucket/results/session-123",
        "type": "DIRECTORY",
    }
    assert tes_request["json"]["executors"][0]["command"] == [
        "/bin/sh",
        "-c",
        "echo 2",
    ]


def test_run_script_uses_configured_output_directory(monkeypatch, tes_request):
    monkeypatch.setenv("OUTPUT_PATH", "/results")
    monkeypatch.setenv("OUTPUT_URL", "s3://bucket/results")
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})

    asyncio.run(tes_mcp.run_script("echo 2", ctx=context))

    assert tes_request["json"]["inputs"][0]["path"] == "/results"
    assert tes_request["json"]["inputs"][0]["type"] == "DIRECTORY"


def test_run_script_uses_session_id_from_context(monkeypatch, tes_request):
    monkeypatch.setenv("OUTPUT_PATH", "/results")
    monkeypatch.setenv("OUTPUT_URL", "s3://bucket/results")
    context = SimpleNamespace(headers={"MCP-Session-Id": "request-session"})

    asyncio.run(tes_mcp.run_script("echo 2", ctx=context))

    assert tes_request["json"]["outputs"][0]["url"] == (
        "s3://bucket/results/request-session"
    )


def test_list_tasks_requests_session_tasks(monkeypatch, tes_request):
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})

    result = asyncio.run(tes_mcp.list_tasks(ctx=context))

    assert json.loads(result) == {"id": "task-123"}
    assert tes_request == {
        "method": "get",
        "path": "/tasks",
        "params": {
            "view": "FULL",
            "page_size": 100,
            "tag_key": ["MCP-Session-Id"],
            "tag_value": ["session-123"],
        },
    }


def test_list_tasks_rejects_missing_session_id(tes_request):
    context = SimpleNamespace(headers=None)

    with pytest.raises(
        ValueError,
        match="Session ID is missing. Cannot list tasks without a session ID.",
    ):
        asyncio.run(tes_mcp.list_tasks(ctx=context))

    assert tes_request == {}


def test_get_service_info_requests_service_info(monkeypatch, tes_request):
    result = asyncio.run(tes_mcp.get_service_info())

    assert json.loads(result) == {"id": "task-123"}
    assert tes_request == {"method": "get", "path": "/service-info"}


def test_get_task_encodes_task_id(monkeypatch, tes_request):
    result = asyncio.run(tes_mcp.get_task("task/with spaces"))

    assert json.loads(result) == {"id": "task-123"}
    assert tes_request == {
        "method": "get",
        "path": "/tasks/task%2Fwith%20spaces",
        "params": {"view": "FULL"},
    }


def test_cancel_task_uses_cancel_endpoint(monkeypatch, tes_request):
    result = asyncio.run(tes_mcp.cancel_task("task-123"))

    assert json.loads(result) == {"id": "task-123"}
    assert tes_request == {
        "method": "post",
        "path": "/tasks/task-123:cancel",
    }


@pytest.mark.parametrize("tool", [tes_mcp.get_task, tes_mcp.cancel_task])
def test_task_tools_reject_empty_id(tool):
    with pytest.raises(ValueError, match="task_id must not be empty"):
        asyncio.run(tool("  "))
