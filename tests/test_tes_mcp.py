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
        executor_image="ubuntu:20.04",
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
    command = tes_request["json"]["executors"][0]["command"]
    assert command[:2] == ["/bin/sh", "-c"]
    assert command[2].endswith("\necho 2\n" + tes_mcp._ENV_SYNC_SNIPPET)


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
    command = tes_request["json"]["executors"][0]["command"]
    assert command[:2] == ["/bin/sh", "-c"]
    assert command[2].endswith("\necho 2 > text.txt\n" + tes_mcp._ENV_SYNC_SNIPPET)


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


def test_wrap_script_wraps_script_between_bootstrap_and_sync():
    wrapped = tes_mcp._wrap_script_with_env("echo hi")

    assert wrapped.startswith(tes_mcp._get_env_bootstrap_snippet())
    assert wrapped.endswith(tes_mcp._ENV_SYNC_SNIPPET)
    assert "\necho hi\n" in wrapped


def test_bootstrap_uses_output_path_for_env_dir():
    original = tes_mcp.settings.output_path
    try:
        tes_mcp.settings.output_path = "/results"
        bootstrap = tes_mcp._get_env_bootstrap_snippet()
    finally:
        tes_mcp.settings.output_path = original

    assert "MCP_ENV_PERSIST=/results/mcp-env" in bootstrap
    assert (
        'MCP_ENV_BUNDLE="$MCP_ENV_PERSIST/' + tes_mcp._ENV_BUNDLE_NAME + '"'
        in bootstrap
    )


def test_bootstrap_unpacks_bundle_and_installs_to_target():
    bootstrap = tes_mcp._get_env_bootstrap_snippet()

    assert 'tar -xzf "$MCP_ENV_BUNDLE"' in bootstrap  # unpack persisted env
    assert "chmod u+x" in bootstrap  # S3 strips modes; repair loose files
    assert 'install --target "$MCP_ENV/py"' in bootstrap  # pip persists to py/
    assert 'PYTHONPATH="$MCP_ENV/py' in bootstrap  # and is importable next task


def test_sync_snippet_repacks_bundle_and_preserves_status():
    sync = tes_mcp._ENV_SYNC_SNIPPET

    # Standalone subshell close: `(...) || MCP_STATUS=$?` would disable the
    # user's `set -e` inside the subshell.
    assert sync.startswith(")\nMCP_STATUS=$?\n")  # propagate script exit status
    assert 'find "$MCP_ENV" -newer "$MCP_ENV/.stamp"' in sync  # skip if unchanged
    assert "tar -C \"$MCP_ENV\" --exclude='./.stamp'" in sync  # repack on change
    # Checked pipeline: a failed tar/gzip must never replace a good bundle.
    assert "--ignore-failed-read" in sync
    assert 'gzip -1 -c "$MCP_ENV_BUNDLE.new" > "$MCP_ENV_BUNDLE.new.gz"' in sync
    assert 'mv -f "$MCP_ENV_BUNDLE.new.gz" "$MCP_ENV_BUNDLE"' in sync
    assert 'rm -f "$MCP_ENV_BUNDLE.new" "$MCP_ENV_BUNDLE.new.gz"' in sync
    assert 'exit "$MCP_STATUS"' in sync


def test_bootstrap_migrates_loose_env_dirs_into_bundle():
    bootstrap = tes_mcp._get_env_bootstrap_snippet()

    assert '[ -d "$MCP_ENV_PERSIST/venv" ]' in bootstrap  # venv-era sessions too


def test_run_script_wraps_script_with_env_bootstrap(monkeypatch, tes_request):
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})

    asyncio.run(
        tes_mcp.run_script("echo 2", ctx=context, output_file_name="output.txt")
    )

    command = tes_request["json"]["executors"][0]["command"]
    assert command[:2] == ["/bin/sh", "-c"]
    assert command[2] == tes_mcp._wrap_script_with_env("echo 2")


def test_bootstrap_preamble_is_set_e_safe():
    preamble = tes_mcp._get_env_bootstrap_snippet()

    assert preamble.count("|| true") >= 5
    # mkdir/find/chmod failures must never abort a user script with `set -e`.
    assert "mkdir -p" in preamble
    assert "2>/dev/null || true" in preamble


def test_bootstrap_touches_stamp_after_writing_shims():
    preamble = tes_mcp._get_env_bootstrap_snippet()

    # The pip/pip3 shims are rewritten on every task; if .stamp were touched
    # first, the shims would always read as newer and every task would repack
    # and re-upload the whole bundle.
    assert preamble.rindex('touch "$MCP_ENV/.stamp"') > preamble.rindex("MCP_SHIM_PIP3")


def test_user_script_runs_inside_subshell_before_status_capture():
    preamble = tes_mcp._get_env_bootstrap_snippet()
    sync = tes_mcp._ENV_SYNC_SNIPPET

    # set -e must stay effective for the user script: the subshell closes as a
    # standalone command and its status is captured on the next line.
    assert preamble.rstrip("\n").endswith("(")
    assert sync.startswith(")\nMCP_STATUS=$?\n")


def test_failed_archive_task_raises_instead_of_stale_presign(monkeypatch, tes_request):
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})
    monkeypatch.setattr(tes_mcp, "_ensure_object_exists", lambda key: None)

    async def fake_wait_for_task_finish(task_id):
        return json.dumps({"id": task_id, "state": "SYSTEM_ERROR"})

    monkeypatch.setattr(tes_mcp, "wait_for_task_finish", fake_wait_for_task_finish)

    with pytest.raises(RuntimeError, match="SYSTEM_ERROR"):
        asyncio.run(tes_mcp.get_session_files_presigned_url(ctx=context))


def test_failed_archive_task_tolerates_missing_stale_object(monkeypatch, tes_request):
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})

    async def fake_wait_for_task_finish(task_id):
        return json.dumps({"id": task_id, "state": "COMPLETE"})

    monkeypatch.setattr(tes_mcp, "wait_for_task_finish", fake_wait_for_task_finish)
    monkeypatch.setattr(
        tes_mcp,
        "_ensure_object_exists",
        lambda key: None,
    )

    result = asyncio.run(tes_mcp.get_session_files_presigned_url(ctx=context))

    assert "url" in json.loads(result)


def test_ensure_object_exists_maps_unexpected_client_error_to_runtime_error(
    monkeypatch, tes_request
):
    class FakeS3Client:
        def head_object(self, **kwargs):
            raise tes_mcp.ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "Forbidden"}},
                "HeadObject",
            )

    monkeypatch.setattr(tes_mcp, "_get_s3_client", lambda: FakeS3Client())

    with pytest.raises(RuntimeError, match="Unable to verify S3 object"):
        tes_mcp._ensure_object_exists("results/session-123/missing.txt")


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
    monkeypatch.setattr(tes_mcp, "_ensure_object_exists", lambda key: None)

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


def test_get_presigned_url_rejects_missing_object(monkeypatch, tes_request):
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})

    def reject_object(key):
        raise FileNotFoundError(f"S3 object does not exist: {key}")

    monkeypatch.setattr(
        tes_mcp,
        "_ensure_object_exists",
        reject_object,
    )

    with pytest.raises(FileNotFoundError, match="S3 object does not exist"):
        asyncio.run(tes_mcp.get_presigned_url("missing.txt", ctx=context))


def test_ensure_object_exists_checks_bucket_and_key(monkeypatch, tes_request):
    calls = []

    class FakeS3Client:
        def head_object(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(tes_mcp, "_get_s3_client", lambda: FakeS3Client())

    tes_mcp._ensure_object_exists("results/session-123/result.txt")

    assert calls == [
        {
            "Bucket": "bucket",
            "Key": "results/session-123/result.txt",
        }
    ]


def test_ensure_object_exists_reports_missing_object(monkeypatch, tes_request):
    class FakeS3Client:
        def head_object(self, **kwargs):
            raise tes_mcp.ClientError(
                {
                    "Error": {
                        "Code": "404",
                        "Message": "Not Found",
                    }
                },
                "HeadObject",
            )

    monkeypatch.setattr(tes_mcp, "_get_s3_client", lambda: FakeS3Client())

    with pytest.raises(
        FileNotFoundError,
        match="S3 object does not exist: results/session-123/missing.txt",
    ):
        tes_mcp._ensure_object_exists("results/session-123/missing.txt")


def test_get_session_files_presigned_url_submits_tar_task(monkeypatch, tes_request):
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})
    monkeypatch.setattr(
        tes_mcp,
        "_generate_presigned_url",
        lambda key: f"https://s3.example/{key}",
    )
    monkeypatch.setattr(tes_mcp, "_ensure_object_exists", lambda key: None)
    calls = []

    async def fake_wait_for_task_finish(task_id):
        calls.append(task_id)
        return json.dumps({"id": task_id, "state": "COMPLETE"})

    monkeypatch.setattr(tes_mcp, "wait_for_task_finish", fake_wait_for_task_finish)

    result = asyncio.run(tes_mcp.get_session_files_presigned_url(ctx=context))

    assert json.loads(result) == {
        "url": "https://s3.example/results/session-123/session-files_session-123.tar.gz",
        "object_key": "results/session-123/session-files_session-123.tar.gz",
        "expires_in": 3600,
    }
    assert calls == ["task-123"]
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
    command = tes_request["json"]["executors"][0]["command"]
    assert command[:2] == ["/bin/sh", "-c"]
    assert command[2].endswith(
        "\ntar --exclude=./session-files_session-123.tar.gz --exclude=./mcp-env -czf /archive/session-files_session-123.tar.gz -C /results .\n"
        + tes_mcp._ENV_SYNC_SNIPPET
    )


def test_get_session_files_presigned_url_uses_configured_executor_image(
    monkeypatch, tes_request
):
    tes_mcp.settings.executor_image = "python:3.12"
    context = SimpleNamespace(headers={"MCP-Session-Id": "session-123"})

    monkeypatch.setattr(tes_mcp, "_ensure_object_exists", lambda key: None)

    async def fake_wait_for_task_finish(task_id):
        return json.dumps({"id": task_id, "state": "COMPLETE"})

    monkeypatch.setattr(tes_mcp, "wait_for_task_finish", fake_wait_for_task_finish)

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
