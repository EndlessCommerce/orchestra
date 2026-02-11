from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from orchestra.cli.main import app

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


def test_compile_valid_pipeline() -> None:
    result = runner.invoke(app, ["compile", str(FIXTURES / "test-linear.dot")])
    assert result.exit_code == 0
    assert "Pipeline: test_linear" in result.output
    assert "Nodes: 5" in result.output
    assert "Edges: 4" in result.output


def test_compile_invalid_pipeline() -> None:
    result = runner.invoke(app, ["compile", str(FIXTURES / "test-invalid-no-start-exit.dot")])
    assert result.exit_code == 1
    assert "ERROR" in result.output
    assert "start_node" in result.output


def test_run_valid_pipeline_with_mock_cxdb() -> None:
    mock_client = MagicMock()
    mock_client.health_check.return_value = {"status": "ok"}
    mock_client.create_context.return_value = {"context_id": "42"}
    mock_client.append_turn.return_value = {"turn_id": "1"}

    with patch("orchestra.cli.run.CxdbClient", return_value=mock_client):
        result = runner.invoke(app, ["run", str(FIXTURES / "test-linear.dot")])

    assert result.exit_code == 0
    assert "Pipeline" in result.output
    assert "Session" in result.output


def test_run_invalid_pipeline() -> None:
    result = runner.invoke(app, ["run", str(FIXTURES / "test-invalid-no-start-exit.dot")])
    assert result.exit_code == 1
    assert "ERROR" in result.output


def test_run_without_cxdb() -> None:
    from orchestra.storage.cxdb_client import CxdbConnectionError

    mock_client = MagicMock()
    mock_client.health_check.side_effect = CxdbConnectionError("Connection refused")

    with patch("orchestra.cli.run.CxdbClient", return_value=mock_client):
        result = runner.invoke(app, ["run", str(FIXTURES / "test-linear.dot")])

    assert result.exit_code == 1
    assert "Cannot connect" in result.output or "CXDB" in result.output


def test_doctor_command() -> None:
    mock_client = MagicMock()
    mock_client.health_check.return_value = {"status": "ok"}

    with patch("orchestra.cli.doctor.CxdbClient", return_value=mock_client):
        result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "OK" in result.output
