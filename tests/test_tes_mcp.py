import asyncio
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

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
    monkeypatch.setattr(tes_mcp, "_PROCESS_SESSION_ID", "session-123")

    result = asyncio.run(tes_mcp.run_script("echo 2", "results56.txt"))

    assert json.loads(result) == {"id": "task-123"}
    assert submitted_task["outputs"][0]["path"] == "/results/results56.txt"
    assert submitted_task["outputs"][0]["url"] == (
        "s3://bucket/results/session-123/results56.txt"
    )
    assert submitted_task["outputs"][0]["type"] == "FILE"
    assert submitted_task["executors"][0]["command"] == [
        "/bin/sh",
        "-c",
        "exec > /results/results56.txt\necho 2",
    ]


def test_run_script_invents_output_file_name(monkeypatch, submitted_task):
    monkeypatch.setenv("OUTPUT_PATH", "/results")
    monkeypatch.setenv("OUTPUT_URL", "s3://bucket/results")
    monkeypatch.setattr(tes_mcp, "_PROCESS_SESSION_ID", "session-123")

    asyncio.run(tes_mcp.run_script("echo 2"))

    command = submitted_task["executors"][0]["command"]
    match = re.fullmatch(
        r"exec > /results/(results-[0-9a-f]{32}\.txt)\necho 2",
        command[2],
    )
    assert match is not None
