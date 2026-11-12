import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

os.environ.setdefault("TES_URL", "https://tes.example.com")
os.environ.setdefault("TES_USERNAME", "test-user")
os.environ.setdefault("TES_PASSWORD", "test-password")
os.environ.setdefault("OUTPUT_URL", "s3://test-bucket/results")
os.environ.setdefault("S3_ENDPOINT_URL", "https://s3.example.com")
os.environ.setdefault("S3_ACCESS_KEY_ID", "test-access-key")
os.environ.setdefault("S3_SECRET_ACCESS_KEY", "test-secret-key")

sys.path.insert(0, str(Path(__file__).parents[1] / "mcp"))

import tes_mcp


def test_settings_rejects_invalid_tes_url():
    with pytest.raises(ValidationError, match="tes_url"):
        tes_mcp.Settings(
            _env_file=None,
            tes_url="not-a-url",
            tes_username="username",
            tes_password="password",
            output_url="s3://bucket/results",
            s3_access_key_id="access-key",
            s3_secret_access_key="secret-key",
        )


@pytest.fixture
def tes_request(monkeypatch):
    request = {}
    settings = tes_mcp.Settings(
        tes_url="https://tes.example.com",
        tes_username="username",
        tes_password="password",
        output_path="/results",
        output_url="s3://bucket/results",
    )
    monkeypatch.setattr(tes_mcp, "settings", settings)

    def fake_tes_request(method, path="/tasks", **kwargs):
        request.update(method=method, path=path, **kwargs)
        return {"id": "task-123"}

    monkeypatch.setattr(tes_mcp, "_make_tes_request", fake_tes_request)
    return request


def test_run_script_submits_response(monkeypatch, tes_request):
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})
    monkeypatch.setattr(
        tes_mcp,
        "_generate_presigned_url",
        lambda key: f"https://s3.example/{key}",
    )

    result = asyncio.run(
        tes_mcp.run_script("echo 2", ctx=context, output_file_name="output.txt")
    )

    assert json.loads(result) == {
        "task": {"id": "task-123"},
        "output_url": "https://s3.example/results/session-123/output.txt",
        "output_object_key": "results/session-123/output.txt",
        "expires_in": 3600,
    }
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


def test_run_script_returns_requested_file_url(monkeypatch, tes_request):
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})
    monkeypatch.setattr(
        tes_mcp,
        "_generate_presigned_url",
        lambda key: f"https://s3.example/{key}",
    )

    result = asyncio.run(
        tes_mcp.run_script(
            "echo 2 > text.txt", ctx=context, output_file_name="text.txt"
        )
    )

    assert json.loads(result) == {
        "task": {"id": "task-123"},
        "output_url": "https://s3.example/results/session-123/text.txt",
        "output_object_key": "results/session-123/text.txt",
        "expires_in": 3600,
    }
    assert tes_request["json"]["executors"][0]["command"] == [
        "/bin/sh",
        "-c",
        "echo 2 > text.txt",
    ]


def test_run_script_uses_output_directory(monkeypatch, tes_request):
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})

    asyncio.run(
        tes_mcp.run_script("echo 2", ctx=context, output_file_name="output.txt")
    )

    assert tes_request["json"]["inputs"][0]["path"] == "/results"
    assert tes_request["json"]["inputs"][0]["type"] == "DIRECTORY"


def test_run_script_uses_session_id_from_context(monkeypatch, tes_request):
    context = SimpleNamespace(headers={"MCP-Session-Id": "request-session"})

    asyncio.run(
        tes_mcp.run_script("echo 2", ctx=context, output_file_name="output.txt")
    )

    assert tes_request["json"]["outputs"][0]["url"] == (
        "s3://bucket/results/request-session"
    )


def test_run_script_uses_configured_session_id_over_context(monkeypatch, tes_request):
    tes_mcp.settings.session_id = "configured-session"
    context = SimpleNamespace(headers={"MCP-Session-Id": "request-session"})

    asyncio.run(
        tes_mcp.run_script("echo 2", ctx=context, output_file_name="output.txt")
    )

    assert tes_request["json"]["outputs"][0]["url"] == (
        "s3://bucket/results/configured-session"
    )


def test_run_script_uses_configured_session_header(monkeypatch, tes_request):
    tes_mcp.settings.session_id_header_key = "X-Session-Id"
    context = SimpleNamespace(headers={"X-Session-Id": "custom-session"})

    asyncio.run(
        tes_mcp.run_script("echo 2", ctx=context, output_file_name="output.txt")
    )

    assert tes_request["json"]["outputs"][0]["url"] == (
        "s3://bucket/results/custom-session"
    )


def test_run_script_uses_configured_executor_image(monkeypatch, tes_request):
    tes_mcp.settings.executor_image = "python:3.12"
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})

    asyncio.run(
        tes_mcp.run_script("echo 2", ctx=context, output_file_name="output.txt")
    )

    assert tes_request["json"]["executors"][0]["image"] == "python:3.12"


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


def test_get_presigned_url_for_session_object(monkeypatch, tes_request):
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})
    monkeypatch.setattr(
        tes_mcp,
        "_generate_presigned_url",
        lambda key: f"https://s3.example/{key}",
    )

    result = asyncio.run(tes_mcp.get_presigned_url("result.txt", ctx=context))

    assert json.loads(result) == {
        "url": "https://s3.example/results/session-123/result.txt",
        "object_key": "results/session-123/result.txt",
        "expires_in": 3600,
    }


def test_get_presigned_url_rejects_path_traversal(tes_request):
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})

    with pytest.raises(ValueError, match="relative object key"):
        asyncio.run(tes_mcp.get_presigned_url("../secret.txt", ctx=context))


def test_get_session_files_presigned_url_submits_tar_task(monkeypatch, tes_request):
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})
    monkeypatch.setattr(
        tes_mcp,
        "_generate_presigned_url",
        lambda key: f"https://s3.example/{key}",
    )

    result = asyncio.run(tes_mcp.get_session_files_presigned_url(ctx=context))

    assert json.loads(result) == {
        "task": {"id": "task-123"},
        "url": "https://s3.example/results/session-123/session-files_session-123.tar.gz",
        "object_key": "results/session-123/session-files_session-123.tar.gz",
        "expires_in": 3600,
    }
    assert tes_request["method"] == "post"
    assert tes_request["json"]["name"] == "tar-session-files"
    assert tes_request["json"]["tags"] == {"MCP-Session-Id": "session-123"}
    assert tes_request["json"]["inputs"][0] == {
        "path": "/results",
        "url": "s3://bucket/results/session-123",
        "type": "DIRECTORY",
    }
    assert tes_request["json"]["outputs"][0] == {
        "path": "/archive",
        "url": "s3://bucket/results/session-123",
        "type": "DIRECTORY",
    }
    assert tes_request["json"]["executors"][0]["image"] == "ubuntu:20.04"
    assert tes_request["json"]["executors"][0]["command"] == [
        "/bin/sh",
        "-c",
        "tar --exclude=./session-files_session-123.tar.gz -czf /archive/session-files_session-123.tar.gz -C /results .",
    ]


def test_get_session_files_presigned_url_uses_configured_executor_image(
    monkeypatch, tes_request
):
    tes_mcp.settings.executor_image = "python:3.12"
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})

    asyncio.run(tes_mcp.get_session_files_presigned_url(ctx=context))

    assert tes_request["json"]["executors"][0]["image"] == "python:3.12"


@pytest.mark.parametrize(
    "session_id", ["session;id", "session $(id)", "../escape", "session id"]
)
def test_get_session_files_presigned_url_rejects_invalid_session_id(
    tes_request, session_id
):
    context = SimpleNamespace(headers={"MCP-Session-Id": session_id})

    with pytest.raises(ValueError, match="session_id must contain only"):
        asyncio.run(tes_mcp.get_session_files_presigned_url(ctx=context))

    assert tes_request == {}


def test_get_session_files_presigned_url_rejects_missing_session(tes_request):
    context = SimpleNamespace(headers=None)

    with pytest.raises(
        ValueError,
        match="Session ID is missing. Cannot create a session archive without a session ID.",
    ):
        asyncio.run(tes_mcp.get_session_files_presigned_url(ctx=context))

    assert tes_request == {}


def test_list_tasks_uses_configured_session_id(monkeypatch, tes_request):
    tes_mcp.settings.session_id = "configured-session"
    context = SimpleNamespace(headers={"MCP-Session-Id": "request-session"})

    asyncio.run(tes_mcp.list_tasks(ctx=context))

    assert tes_request["params"]["tag_value"] == ["configured-session"]


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


def test_sleep_waits_and_returns_success(monkeypatch):
    waited = []

    async def fake_sleep(seconds):
        waited.append(seconds)

    monkeypatch.setattr(tes_mcp.asyncio, "sleep", fake_sleep)

    result = asyncio.run(tes_mcp.sleep(2.5))

    assert waited == [2.5]
    assert json.loads(result) == {"status": "ok", "slept_seconds": 2.5}


def test_sleep_allows_maximum_seconds(monkeypatch):
    waited = []

    async def fake_sleep(seconds):
        waited.append(seconds)

    monkeypatch.setattr(tes_mcp.asyncio, "sleep", fake_sleep)

    asyncio.run(tes_mcp.sleep(300))

    assert waited == [300]


def test_sleep_rejects_negative_seconds():
    with pytest.raises(ValueError, match="seconds must not be negative"):
        asyncio.run(tes_mcp.sleep(-1))


def test_sleep_rejects_seconds_above_maximum():
    with pytest.raises(ValueError, match="seconds must not exceed 300"):
        asyncio.run(tes_mcp.sleep(300.1))


def test_wait_for_task_finish_polls_until_terminal(monkeypatch, tes_request):
    responses = iter(
        [
            {"id": "task-123", "state": "RUNNING"},
            {"id": "task-123", "state": "COMPLETE"},
        ]
    )
    waits = []

    def fake_tes_request(method, path="/tasks", **kwargs):
        request = {"method": method, "path": path, **kwargs}
        tes_request.setdefault("calls", []).append(request)
        return next(responses)

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(tes_mcp, "_make_tes_request", fake_tes_request)
    monkeypatch.setattr(tes_mcp.asyncio, "sleep", fake_sleep)

    result = asyncio.run(tes_mcp.wait_for_task_finish("task-123"))

    assert json.loads(result) == {"id": "task-123", "state": "COMPLETE"}
    assert tes_request["calls"] == [
        {
            "method": "get",
            "path": "/tasks/task-123",
            "params": {"view": "FULL"},
        },
        {
            "method": "get",
            "path": "/tasks/task-123",
            "params": {"view": "FULL"},
        },
    ]
    assert waits == [1]


def test_wait_for_task_finish_rejects_empty_id():
    with pytest.raises(ValueError, match="task_id must not be empty"):
        asyncio.run(tes_mcp.wait_for_task_finish("  "))


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
