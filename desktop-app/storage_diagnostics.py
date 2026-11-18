"""Non-network packaged save test. Never loads or replaces the user's credential."""
from __future__ import annotations

from pathlib import Path
import secrets
import uuid

from credentials import CredentialError, CredentialStore


def diagnose_save(directory: Path | None = None) -> dict:
    report = {
        "schema": "vwc-key-save-check/1", "version": "0.1.1",
        "success": False, "storage_directory": None,
        "uses_synthetic_credential": True, "uses_network": False,
        "real_credential_loaded": False, "real_credential_replaced": False,
        "checks": {}, "cleanup": False,
    }
    probe = None
    probe_created = False
    stage = "resolve_storage"
    try:
        destination = CredentialStore(directory).directory.resolve()
        report["storage_directory"] = str(destination)
        stage = "create_probe"
        destination.mkdir(parents=True, exist_ok=True)
        probe = destination / f".save-check-{uuid.uuid4().hex}"
        probe.mkdir(exist_ok=False)
        probe_created = True
        # Only the new, exclusively created probe folder receives test data.
        test_store = CredentialStore(probe)
        sentinel = "sk-local-self-test-" + secrets.token_urlsafe(32)
        stage = "save_encrypted_key"
        test_store.save_key(sentinel)
        report["checks"]["encrypted_on_disk"] = sentinel.encode() not in test_store.key_path.read_bytes()
        stage = "save_model_settings"
        test_store.save_settings("gpt-6.1-terra", "high")
        stage = "reopen"
        reopened = CredentialStore(probe)
        report["checks"]["key_reopened"] = reopened.load_key() == sentinel
        report["checks"]["settings_reopened"] = reopened.load_settings() == {
            "model": "gpt-6.1-terra", "reasoning": "high"}
        report["success"] = all(report["checks"].values())
    except CredentialError as error:
        report["error"] = {"type": "CredentialError", "stage": error.stage or stage, "code": error.code}
    except OSError as error:
        report["error"] = {"type": type(error).__name__, "stage": stage,
                           "code": getattr(error, "winerror", None) or error.errno}
    finally:
        if probe_created:
            try:
                # No recursive deletion. Never remove anything outside our unique probe.
                if probe.resolve().parent != destination:
                    raise OSError("Probe location changed")
                for name in ("openai-key.bin", "settings.json"):
                    (probe / name).unlink(missing_ok=True)
                probe.rmdir()
                report["cleanup"] = True
            except OSError:
                report["cleanup"] = False
        if not report["cleanup"]:
            report["success"] = False
    return report
