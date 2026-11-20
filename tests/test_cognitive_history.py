from __future__ import annotations

from modules.cognitive.history import (
    append_jsonl,
    compact_cognitive_state,
    read_jsonl_tail,
)


def test_jsonl_history_rotates_and_reads_tail(tmp_path):
    path = tmp_path / "history.jsonl"
    for index in range(12):
        append_jsonl(path, {"index": index}, max_bytes=60, backup_count=2)

    assert path.stat().st_size <= 60
    assert path.with_name("history.jsonl.1").exists()
    assert read_jsonl_tail(path, limit=2)[-1] == {"index": 11}


def test_compact_cognitive_state_limits_task_payload():
    state = {
        "active_tasks": [
            {"id": str(index), "title": f"Task {index}", "result": "x" * 1000}
            for index in range(20)
        ]
    }

    compact = compact_cognitive_state(state)

    assert compact["active_task_count"] == 20
    assert len(compact["active_tasks"]) == 10
    assert "result" not in compact["active_tasks"][0]
