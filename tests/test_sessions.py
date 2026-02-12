"""Tests for session management functionality."""
from __future__ import annotations

from orchestra.engine.session import SessionInfo, derive_session_status, extract_session_info


def test_session_status_completed() -> None:
    """Successful pipeline → session status shows completed."""
    turns = [
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "test", "status": "started", "session_display_id": "abc123"},
        },
        {
            "type_id": "dev.orchestra.NodeExecution",
            "data": {"node_id": "start", "status": "started"},
        },
        {
            "type_id": "dev.orchestra.Checkpoint",
            "data": {"current_node": "start", "next_node_id": "exit"},
        },
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "test", "status": "completed", "duration_ms": 100},
        },
    ]

    assert derive_session_status(turns) == "completed"


def test_session_status_failed() -> None:
    """Failed pipeline → session status shows failed."""
    turns = [
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "test", "status": "started"},
        },
        {
            "type_id": "dev.orchestra.Checkpoint",
            "data": {"current_node": "start", "next_node_id": "plan"},
        },
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "test", "status": "failed", "error": "boom"},
        },
    ]

    assert derive_session_status(turns) == "failed"


def test_session_status_paused() -> None:
    """Paused pipeline → session status shows paused."""
    turns = [
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "test", "status": "started"},
        },
        {
            "type_id": "dev.orchestra.Checkpoint",
            "data": {"current_node": "plan", "next_node_id": "build"},
        },
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "test", "status": "paused"},
        },
    ]

    assert derive_session_status(turns) == "paused"


def test_session_status_interrupted() -> None:
    """Checkpoint as head turn (no PipelinePaused) → paused (interrupted)."""
    turns = [
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "test", "status": "started"},
        },
        {
            "type_id": "dev.orchestra.Checkpoint",
            "data": {"current_node": "plan", "next_node_id": "build"},
        },
    ]

    assert derive_session_status(turns) == "paused"


def test_session_status_running() -> None:
    """NodeExecution as head turn → running."""
    turns = [
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "test", "status": "started"},
        },
        {
            "type_id": "dev.orchestra.NodeExecution",
            "data": {"node_id": "plan", "status": "started"},
        },
    ]

    assert derive_session_status(turns) == "running"


def test_session_status_just_started() -> None:
    """PipelineStarted as head turn → running."""
    turns = [
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "test", "status": "started"},
        },
    ]

    assert derive_session_status(turns) == "running"


def test_session_status_empty() -> None:
    """Empty turns → unknown."""
    assert derive_session_status([]) == "unknown"


def test_extract_session_info_basic() -> None:
    """extract_session_info returns correct metadata."""
    turns = [
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {
                "pipeline_name": "my_pipeline",
                "status": "started",
                "session_display_id": "abc123",
            },
        },
        {
            "type_id": "dev.orchestra.Checkpoint",
            "data": {"current_node": "plan", "next_node_id": "build"},
        },
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "my_pipeline", "status": "completed"},
        },
    ]

    info = extract_session_info("ctx-42", turns)
    assert info.context_id == "ctx-42"
    assert info.display_id == "abc123"
    assert info.pipeline_name == "my_pipeline"
    assert info.status == "completed"
    assert info.turn_count == 3


def test_extract_session_info_no_display_id() -> None:
    """Session without display_id returns empty string."""
    turns = [
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "test", "status": "started"},
        },
    ]

    info = extract_session_info("ctx-1", turns)
    assert info.display_id == ""
    assert info.pipeline_name == "test"


def test_session_created() -> None:
    """A session with PipelineStarted turn is correctly identified."""
    turns = [
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {
                "pipeline_name": "test_pipeline",
                "status": "started",
                "session_display_id": "def456",
                "dot_file_path": "/tmp/test.dot",
                "graph_hash": "abcdef",
            },
        },
    ]

    info = extract_session_info("ctx-99", turns)
    assert info.context_id == "ctx-99"
    assert info.display_id == "def456"
    assert info.pipeline_name == "test_pipeline"
    assert info.status == "running"
    assert info.turn_count == 1
