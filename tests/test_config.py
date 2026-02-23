"""Tests for config.py — platform-aware default path helpers."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest


class TestDefaultDataDir:
    """Tests for _default_data_dir() platform dispatch."""

    @pytest.mark.unit
    def test_posix_returns_dot_mcpvectordb(self):
        """On non-Windows platforms _default_data_dir returns ~/.mcpvectordb."""
        from mcpvectordb.config import _default_data_dir

        with patch.object(sys, "platform", "linux"):
            result = _default_data_dir()

        assert result == Path.home() / ".mcpvectordb"

    @pytest.mark.unit
    def test_windows_returns_appdata_local(self):
        """On win32 _default_data_dir returns AppData/Local/mcpvectordb."""
        from mcpvectordb.config import _default_data_dir

        with patch.object(sys, "platform", "win32"):
            result = _default_data_dir()

        assert result == Path.home() / "AppData" / "Local" / "mcpvectordb"

    @pytest.mark.unit
    def test_lancedb_uri_ends_with_lancedb(self):
        """_default_lancedb_uri appends /lancedb to the data dir."""
        from mcpvectordb.config import _default_data_dir, _default_lancedb_uri

        uri = _default_lancedb_uri()
        assert uri == str(_default_data_dir() / "lancedb")

    @pytest.mark.unit
    def test_model_cache_ends_with_models(self):
        """_default_model_cache appends /models to the data dir."""
        from mcpvectordb.config import _default_data_dir, _default_model_cache

        cache = _default_model_cache()
        assert cache == str(_default_data_dir() / "models")


class TestSettingsDefaults:
    """Tests that Settings fields declare the platform-aware helpers as their defaults."""

    @pytest.mark.unit
    def test_lancedb_uri_field_uses_default_factory(self):
        """Settings.lancedb_uri has default_factory set to _default_lancedb_uri."""
        from mcpvectordb.config import Settings, _default_lancedb_uri

        field = Settings.model_fields["lancedb_uri"]
        assert field.default_factory is _default_lancedb_uri

    @pytest.mark.unit
    def test_fastembed_cache_path_field_uses_default_factory(self):
        """Settings.fastembed_cache_path has default_factory set to _default_model_cache."""
        from mcpvectordb.config import Settings, _default_model_cache

        field = Settings.model_fields["fastembed_cache_path"]
        assert field.default_factory is _default_model_cache
