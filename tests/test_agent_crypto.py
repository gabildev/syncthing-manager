from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from syncthing_manager.agent import _decrypt_config, _is_encrypted_config
from syncthing_manager.generate import _build_embedded_block
from syncthing_manager.ssh_ops import SSHClient, SSHError


class TestAgentConfigEncryption:
    def test_plaintext_block_when_no_passphrase(self):
        cfg = {"format": "multi-device-v1", "devices": {}}
        block = _build_embedded_block(cfg, None)
        assert json.loads(block.decode()) == cfg
        assert not _is_encrypted_config(json.loads(block.decode()))

    def test_encrypted_block_roundtrip(self):
        cfg = {"format": "multi-device-v1",
               "devices": {"D1": {"api_key": "SUPERSECRETKEY", "folder_id": "ULL"}}}
        block = _build_embedded_block(cfg, "hunter2")
        env = json.loads(block.decode())
        assert _is_encrypted_config(env)
        # The secret must NOT be recoverable from the raw bytes (the whole point).
        assert "SUPERSECRETKEY" not in block.decode()
        assert _decrypt_config(env, "hunter2") == cfg

    def test_wrong_passphrase_returns_none(self):
        cfg = {"format": "multi-device-v1", "devices": {}}
        env = json.loads(_build_embedded_block(cfg, "right").decode())
        assert _decrypt_config(env, "wrong") is None


class TestSSHCurlDiagnostics:
    def test_get_parses_body_and_strips_status(self):
        with patch.object(SSHClient, "_exec", return_value=(0, '{"id":"ULL"}\n200', "")):
            data = SSHClient(host="h").syncthing_api_get("/rest/x", "key", 8384)
        assert data == {"id": "ULL"}

    def test_http_error_surfaces_code_and_body(self):
        with patch.object(SSHClient, "_exec", return_value=(0, 'folder not found\n404', "")):
            with pytest.raises(SSHError, match="HTTP 404"):
                SSHClient(host="h").syncthing_api_get("/rest/x", "key", 8384)

    def test_missing_curl_reported(self):
        # curl absent → no numeric status line; must raise a clear error, not silently pass.
        with patch.object(SSHClient, "_exec", return_value=(0, "", "")):
            with pytest.raises(SSHError):
                SSHClient(host="h").syncthing_api_post("/rest/x", "key", 8384)
