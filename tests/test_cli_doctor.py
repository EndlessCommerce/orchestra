from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from orchestra.cli.main import app

runner = CliRunner()


def test_doctor_healthy() -> None:
    mock_client = MagicMock()
    mock_client.health_check.return_value = {"status": "ok"}

    with patch("orchestra.cli.doctor.CxdbClient", return_value=mock_client):
        result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "CXDB health: OK" in result.output
    assert "Type bundle: OK" in result.output


def test_doctor_connection_failure() -> None:
    from orchestra.storage.cxdb_client import CxdbConnectionError

    mock_client = MagicMock()
    mock_client.health_check.side_effect = CxdbConnectionError("Connection refused")

    with patch("orchestra.cli.doctor.CxdbClient", return_value=mock_client):
        result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "FAILED" in result.output
    assert "docker run" in result.output
