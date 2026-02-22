"""Unit tests for _validate_tls_config() in server.py."""

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import mcpvectordb.server as server_module
from mcpvectordb.server import _validate_tls_config


def _make_settings(**kwargs) -> MagicMock:
    """Return a MagicMock that mimics Settings with the given overrides."""
    defaults = {
        "tls_enabled": False,
        "mcp_transport": "streamable-http",
        "tls_cert_file": None,
        "tls_key_file": None,
    }
    defaults.update(kwargs)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


@pytest.mark.unit
def test_disabled_no_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """TLS disabled — no error, no warning."""
    mock_settings = _make_settings(tls_enabled=False)
    monkeypatch.setattr(server_module, "settings", mock_settings)
    _validate_tls_config()  # must not raise


@pytest.mark.unit
def test_stdio_logs_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """TLS enabled with stdio transport — warning logged, no raise."""
    mock_settings = _make_settings(tls_enabled=True, mcp_transport="stdio")
    monkeypatch.setattr(server_module, "settings", mock_settings)
    with caplog.at_level(logging.WARNING, logger="mcpvectordb.server"):
        _validate_tls_config()
    assert any("stdio" in rec.message for rec in caplog.records)


@pytest.mark.unit
def test_sse_logs_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """TLS enabled with sse transport — warning logged, no raise."""
    mock_settings = _make_settings(tls_enabled=True, mcp_transport="sse")
    monkeypatch.setattr(server_module, "settings", mock_settings)
    with caplog.at_level(logging.WARNING, logger="mcpvectordb.server"):
        _validate_tls_config()
    assert any("sse" in rec.message for rec in caplog.records)


@pytest.mark.unit
def test_missing_both_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """TLS enabled, streamable-http, no cert or key — ValueError naming both vars."""
    mock_settings = _make_settings(
        tls_enabled=True,
        mcp_transport="streamable-http",
        tls_cert_file=None,
        tls_key_file=None,
    )
    monkeypatch.setattr(server_module, "settings", mock_settings)
    with pytest.raises(ValueError, match="TLS_CERT_FILE"):
        _validate_tls_config()


@pytest.mark.unit
def test_missing_key_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """TLS enabled, cert file exists, key is None — ValueError naming TLS_KEY_FILE."""
    cert = tmp_path / "cert.pem"
    cert.write_text("cert")
    mock_settings = _make_settings(
        tls_enabled=True,
        mcp_transport="streamable-http",
        tls_cert_file=str(cert),
        tls_key_file=None,
    )
    monkeypatch.setattr(server_module, "settings", mock_settings)
    with pytest.raises(ValueError, match="TLS_KEY_FILE"):
        _validate_tls_config()


@pytest.mark.unit
def test_cert_not_found_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """TLS enabled, cert path does not exist on disk — ValueError with 'not found'."""
    key = tmp_path / "key.pem"
    key.write_text("key")
    mock_settings = _make_settings(
        tls_enabled=True,
        mcp_transport="streamable-http",
        tls_cert_file=str(tmp_path / "missing_cert.pem"),
        tls_key_file=str(key),
    )
    monkeypatch.setattr(server_module, "settings", mock_settings)
    with pytest.raises(ValueError, match="not found"):
        _validate_tls_config()


@pytest.mark.unit
def test_key_not_found_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """TLS enabled, key path does not exist on disk — ValueError with 'not found'."""
    cert = tmp_path / "cert.pem"
    cert.write_text("cert")
    mock_settings = _make_settings(
        tls_enabled=True,
        mcp_transport="streamable-http",
        tls_cert_file=str(cert),
        tls_key_file=str(tmp_path / "missing_key.pem"),
    )
    monkeypatch.setattr(server_module, "settings", mock_settings)
    with pytest.raises(ValueError, match="not found"):
        _validate_tls_config()


@pytest.mark.unit
def test_valid_config_no_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """TLS enabled, both files exist — no raise."""
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("cert")
    key.write_text("key")
    mock_settings = _make_settings(
        tls_enabled=True,
        mcp_transport="streamable-http",
        tls_cert_file=str(cert),
        tls_key_file=str(key),
    )
    monkeypatch.setattr(server_module, "settings", mock_settings)
    _validate_tls_config()  # must not raise
