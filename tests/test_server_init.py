"""Tests for server.py module-level initialization code.

Kept in a separate file to prevent importlib.reload from interfering
with the autouse fixtures defined in test_server.py.
"""

import importlib
import logging

import pytest


class TestServerModuleInit:
    """Tests for module-level initialization code in server.py."""

    @pytest.mark.unit
    def test_file_handler_added_when_log_file_configured(self, tmp_path, monkeypatch):
        """FileHandler is appended to _log_handlers when settings.log_file is set (line 20).

        Uses importlib.reload to re-execute module-level init with the patched setting.
        """
        import mcpvectordb.config as config_mod
        import mcpvectordb.server as server_mod

        log_file = str(tmp_path / "test_server.log")
        monkeypatch.setattr(config_mod.settings, "log_file", log_file)

        # Reload so module-level initialization code re-runs with log_file set
        importlib.reload(server_mod)

        try:
            file_handlers = [
                h for h in server_mod._log_handlers
                if isinstance(h, logging.FileHandler)
            ]
            assert len(file_handlers) >= 1
        finally:
            # Close FileHandlers to release the tmp_path file handle
            for h in list(server_mod._log_handlers):
                if isinstance(h, logging.FileHandler):
                    h.close()
                    server_mod._log_handlers.remove(h)
            # Restore module to a clean state (no FileHandler) for subsequent tests
            monkeypatch.setattr(config_mod.settings, "log_file", None)
            importlib.reload(server_mod)
