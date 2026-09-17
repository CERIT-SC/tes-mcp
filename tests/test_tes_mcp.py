import asyncio
import json
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


def test_create_empty_file_submits_response(monkeypatch, submitted_task):
    monkeypatch.setenv("OUTPUT_PATH", "/results")
    monkeypatch.setenv("OUTPUT_URL", "s3://bucket/results")

    result = asyncio.run(tes_mcp.create_empty_file("report.txt"))

    assert json.loads(result) == {"id": "task-123"}
    assert submitted_task["outputs"][0]["path"] == "/results"
    assert submitted_task["outputs"][0]["url"] == "s3://bucket/results"
    assert submitted_task["executors"][0]["command"][-1] == "touch /results/report.txt"
