"""Read-only, no-turn handshake survey of an explicitly selected Codex binary.

The probe uses a disposable CODEX_HOME and emits only whitelisted metadata.
It does not qualify the binary or make a model request.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from nexus_connector_core.discovery import candidate, fingerprint
from nexus_connector_core.native.adapters.codex import (
    CodexAppServerConnector, _CodexTransport,
)
from nexus_connector_core.native.adapter_types import NativeAdapterError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--adapter-thread-start", action="store_true",
                        help="also start a local thread without starting a turn")
    parser.add_argument("--adapter-thread-resume", action="store_true",
                        help="start then resume that thread on a fresh connection, without a turn")
    args = parser.parse_args()
    selected = candidate("codex_app_server", args.executable, explicit=True)
    with tempfile.TemporaryDirectory(prefix="nexus-core-codex-probe-") as directory:
        transport = _CodexTransport(
            (selected.executable, "app-server"), cwd=str(Path.cwd().resolve()),
            env={"CODEX_HOME": directory},
            on_notification=lambda *_: None,
            on_unmatched_response=lambda *_: None,
            on_child_exit=lambda *_: None,
            on_malformed_line=lambda *_: None,
            on_dispatch_error=lambda *_: None,
        )
        try:
            transport.start()
            initialized = transport.request(
                "initialize",
                {"clientInfo": {"name": "nexus_connector_core_probe",
                                "title": "Nexus Connector Core Probe",
                                "version": "0.1.0"}},
                timeout_s=5,
            )
            transport.notify("initialized", {})
            loaded = transport.request("thread/loaded/list", {}, timeout_s=5)
            if fingerprint(Path(selected.executable)) != selected.fingerprint:
                raise RuntimeError("selected executable changed during handshake")
            user_agent = initialized.get("userAgent") if isinstance(initialized, dict) else None
            print(json.dumps({
                "architecture": selected.architecture,
                "initialize_keys": sorted(initialized) if isinstance(initialized, dict) else None,
                "user_agent_prefix": user_agent.split(" ", 1)[0]
                if isinstance(user_agent, str) and len(user_agent) <= 1024 else None,
                "loaded_result_keys": sorted(loaded) if isinstance(loaded, dict) else None,
                "model_request_sent": False,
            }, sort_keys=True))
        finally:
            transport.close(grace_s=2)
        if args.adapter_thread_start or args.adapter_thread_resume:
            connector = CodexAppServerConnector(
                command=(selected.executable, "app-server"),
                cwd=str(Path.cwd().resolve()), env={"CODEX_HOME": directory},
                client_info={"name": "nexus_connector_core_probe",
                             "title": "Nexus Connector Core Probe",
                             "version": "0.1.0"},
                handshake_timeout_s=5,
            )
            try:
                session = connector.start(owning_agent_id="core-probe")
                print(json.dumps({
                    "adapter_thread_start_ok": bool(session.metadata.get("thread_id")),
                    "adapter_observed_version": session.compatibility_report.get("native_version"),
                    "model_request_sent": False,
                }, sort_keys=True))
            finally:
                connector.close()
            if args.adapter_thread_resume:
                resumed_connector = CodexAppServerConnector(
                    command=(selected.executable, "app-server"),
                    cwd=str(Path.cwd().resolve()), env={"CODEX_HOME": directory},
                    client_info={"name": "nexus_connector_core_probe",
                                 "title": "Nexus Connector Core Probe",
                                 "version": "0.1.0"},
                    handshake_timeout_s=5,
                )
                try:
                    try:
                        resumed = resumed_connector.start(
                            owning_agent_id="core-probe", resume_thread_id=session.metadata["thread_id"])
                    except NativeAdapterError as exc:
                        if "no rollout found" not in str(exc):
                            raise
                        print(json.dumps({"adapter_thread_resume_ok": False,
                                          "reason": "no_persisted_rollout",
                                          "model_request_sent": False}, sort_keys=True))
                        raise SystemExit(2) from None
                    else:
                        print(json.dumps({
                            "adapter_thread_resume_ok": resumed.metadata["thread_id"] == session.metadata["thread_id"],
                            "model_request_sent": False,
                        }, sort_keys=True))
                finally:
                    resumed_connector.close()


if __name__ == "__main__":
    main()
