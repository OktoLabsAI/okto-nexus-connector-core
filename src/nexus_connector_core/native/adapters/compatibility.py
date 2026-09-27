# Modified 2026-09-25 for nexus-connector-core: application imports replaced with neutral local types.
"""Bounded compatibility observations; a version string is not a capability grant."""
import re
import subprocess

from ..process import observe_owned_process, spawn_owned_process
from ..adapter_types import ErrorCode, NativeAdapterError
from ..adapter_types import EndpointCapabilities


# Exact wire contracts qualified by the recorded native campaigns and protocol
# fixtures. This is not a claim that every model task succeeds or that a peer
# provides deduplication/resume/sandbox guarantees. Pi remains fixture-qualified.
# The legacy qualification above belongs to the Nexus application build. A
# copied adapter in a new wheel must earn its own native/provider/platform gate.
# Synthetic peers establish protocol regressions only. Until that campaign is
# recorded, no version is an effective capability grant in this wheel.
BASELINE_CONVERSATION_VERSIONS = {"codex": {"0.156.1"}, "claude_code": {"2.1.280", "2.1.281"}, "pi": {"0.85.1"}}
# Exact Core-owned qualification is keyed by native kind, observed version,
# actual host platform, parsed binary architecture and selected file hash.
# Historical Nexus version lists above are provenance, not grants here.
QUALIFIED_BUILDS: set[tuple[str, str, str, str, str]] = set()
QUALIFIED_CONTROL_BUILDS: set[tuple[str, str, str, str, str]] = set()

# Production qualification granted by the recorded 2026-09-26 real
# campaigns on the user-authorized Windows host (see
# plans/implementation/evidence/codex-real-turn-controls-2026-09-26.md,
# pi-real-controls-2026-09-26.md and claude-real-turn-controls-2026-09-26.md
# plus the earlier handshake/readiness observations). Each key is exact:
# kind, observed version, host platform, parsed architecture and the
# selected file fingerprint. The Pi key is the domain-separated composite
# binding the trusted Node executable AND the installed CLI JavaScript
# (paths and hashes) of that one installation; any other Node/CLI pair or
# changed file content does not inherit the grant. This is a wire-contract
# qualification for managed conversation and the listed controls — not a
# promise that every model task succeeds, not resume/deduplication, not the
# Pi work bridge, and not native approval traffic.
_QUALIFIED_PRODUCTION_BUILDS = {
    ("codex", "0.157.0", "win32", "x86_64",
     "sha256:ed1c7b36e44536809c868864c833af8a857f56599a7a7fe23b908a1ba1093b1f"),
    ("pi", "0.87.1", "win32", "x86_64",
     "sha256:3765c5c53d04d5ef6ed4d1309284338aa14104228280fd643ec4cd12fa862058"),
    ("claude_code", "2.1.282", "win32", "x86_64",
     "sha256:fc0e3af017705624b9e1bce913f72761864ff994804514da1f5e41380fca4484"),
}
QUALIFIED_BUILDS |= _QUALIFIED_PRODUCTION_BUILDS
# Real controls were exercised for every build above: Codex steer and
# interrupt with expected native turn IDs, Pi queued steer and abort,
# Claude interrupt while generating (Claude has no steer vocabulary).
QUALIFIED_CONTROL_BUILDS |= _QUALIFIED_PRODUCTION_BUILDS
ATTACH_QUALIFIED = False


def qualified_build(kind, version, platform, architecture, fingerprint,
                    *, control=False, build_identity=None):
    """Exact-build qualification (PC09): fingerprint OR portable identity.

    The path-bound fingerprint key remains the strongest grant (a moved
    installation never inherits it). A portable ``build_identity`` key
    lets an *equivalent* installation - same bytes, different directory -
    conserve the qualification of the same build, while the caller's
    local binding checks still apply independently.

    C2/R06: a Pi build qualifies ONLY through the portable identity. The
    legacy composite fingerprint (Node + cli.js) predates dependency
    coverage and must not bypass it; it remains the path-bound binding
    proof, but it is not a qualification grant on its own.
    """
    sets = (QUALIFIED_CONTROL_BUILDS if control else QUALIFIED_BUILDS,
           QUALIFIED_CONTROL_BUILD_IDENTITIES if control
           else QUALIFIED_BUILD_IDENTITIES)
    key = (kind, version, platform, architecture, fingerprint)
    if key in sets[0] and kind != "pi":
        return True
    if build_identity is not None:
        identity_key = (kind, version, platform, architecture, build_identity)
        return identity_key in sets[1]
    return False


#: Portable identity grants recorded from the same authorized campaigns
#: as the fingerprint entries above (content digests, no paths). A host
#: approves the *local binding* separately; this set never authorizes a
#: path, only conserves qualification of identical bytes.
QUALIFIED_BUILD_IDENTITIES: set[tuple[str, str, str, str, str]] = {
    # Portable content digests of the same three authorized builds above
    # (PC09): identical bytes in a different directory conserve the
    # qualification; the local binding approval still applies separately.
    ("codex", "0.157.0", "win32", "x86_64",
     "sha256:df63d86e72bc1a27f13899ad0467c4b312d8ee2cb67ae3a09e37f734d9f0edcb"),
    ("pi", "0.87.1", "win32", "x86_64",
     "sha256:b454b39171e7428e721ecc01be6654c3608a9091d398c3d3d445897a91a67e43"),
    ("claude_code", "2.1.282", "win32", "x86_64",
     "sha256:b9c8e2e61cc523f4d78630d6141e843c41fbe530cd297e7d4af8acd44841bed9"),
}
QUALIFIED_CONTROL_BUILD_IDENTITIES = set(QUALIFIED_BUILD_IDENTITIES)


def qualified_capabilities(kind, substrate, report):
    if substrate == "attach":
        supported = (ATTACH_QUALIFIED and report.get("transport_contract") == "cc_socks_peer_1" and
                     type(report.get("peer_protocol")) is int and report["peer_protocol"] == 1)
        return EndpointCapabilities(conversation=supported)
    version = report.get("native_version")
    supported = qualified_build(kind, version, report.get("platform"),
                                report.get("architecture"), report.get("fingerprint"))
    controls = report.get("compatible_controls", ()) if supported else ()
    return EndpointCapabilities(conversation=supported,
        managed_work=supported and bool(report.get("work_bridge_qualified")),
        events=supported, correlated_results=supported,
        multiplexing=supported and kind == "codex",
        steer_timing=("NEXT_TURN_BOUNDARY" if kind == "pi" else "IMMEDIATE") if "steer" in controls else None,
        interrupt="interrupt" in controls, interrupt_requires_settle=kind == "pi",
        observes_stop=kind in {"pi", "codex", "claude_code"},
        approvals=supported and bool(report.get("compatible_native_requests")))

# Exact installed schema inspected in P09_NATIVE_PROTOCOL_SURVEY.md, with the
# Nexus handlers exercised by protocol fixtures; actual command denial is
# evidenced in P07_EFFECTIVE_NATIVE_REQUIREMENTS.md. Input elicitation is not
# claimed as an actual model-generated request by this allowlist.
# This is a protocol-contract allowlist, never a semver range or permission.
CODEX_NATIVE_REQUEST_CONTRACTS = {
    "0.156.1": (
        "item/commandExecution/requestApproval", "item/fileChange/requestApproval",
        "item/tool/requestUserInput", "mcpServer/elicitation/request",
    ),
    # 0.157.0: only what the authorized 2026-09-26 real campaign exercised —
    # a command-execution approval surfaced, declined through the checked
    # host reply path (mapped to the native "cancel" decision) and a tardy
    # reply refused after the turn ended. No other request shape is claimed.
    "0.157.0": (
        "item/commandExecution/requestApproval",
    ),
}

# One-shot permissions and explicit questions exercised in the isolated native
# campaigns recorded in P09. This does not assert sandbox or general capability
# verification, nor support for any other can_use_tool shape.
CLAUDE_NATIVE_REQUEST_CONTRACTS = {
    "2.1.280": tuple("control_request:can_use_tool/" + tool
                     for tool in ("Write", "Edit", "Bash", "AskUserQuestion")),
    # Only the two flows actually qualified after the local binary updated.
    "2.1.281": ("control_request:can_use_tool/Write", "control_request:can_use_tool/AskUserQuestion"),
    # 2.1.282: only what the authorized 2026-09-26 real campaign exercised —
    # a Write permission request surfaced, a forged tool kind refused before
    # the wire write, and the decline delivered through the checked host
    # reply path. Bash was auto-allowed by the host settings and is not
    # claimed; AskUserQuestion remains unexercised on this build.
    "2.1.282": (
        "control_request:can_use_tool/Write",
    ),
}

# Current installed versions qualified by the isolated control campaign. Pi's
# protocol contract is covered by the existing 0.85.1 wire fixtures/reference;
# no new native Pi campaign is claimed.
BASELINE_CONTROL_VERSIONS = {"codex": {"0.156.1"}, "claude_code": {"2.1.281"}, "pi": {"0.85.1"}}
def control_observation(kind, version, *, platform=None, architecture=None,
                        fingerprint=None, build_identity=None):
    verified = qualified_build(kind, version, platform, architecture,
                               fingerprint, control=True,
                               build_identity=build_identity)
    if not verified:
        return {"compatible_controls": [],
                "control_contract_basis": "unverified"}
    # Claude stream has no steer vocabulary: its only real-time control is
    # interrupt, and public turn.steer is refused for claude_stream. Pi's
    # steer is the ID-less queued next-turn-boundary contract.
    controls = (["interrupt"] if kind == "claude_code"
                else ["steer", "interrupt"])
    return {"compatible_controls": controls,
            "control_contract_basis": "tested_version_contract"}


def claude_version_observation(command, *, cwd, env, timeout=3.0):
    output = _version_output(command, cwd=cwd, env=env, timeout=timeout)
    match = re.fullmatch(rb"(\d{1,4}\.\d{1,4}\.\d{1,4}) \(Claude Code\)\r?\n?", output) if len(output) <= 1024 else None
    version = match.group(1).decode("ascii") if match else None
    contracts = CLAUDE_NATIVE_REQUEST_CONTRACTS.get(version, ())
    return {"schema_version": 1, "native_version": version,
        "observation": "executable_version" if version else "version_not_observed",
        "capabilities_verified": False,
        "compatible_native_requests": list(contracts),
        "native_request_basis": ("tested_version_contract" if contracts
                                  else "unverified"),
        **control_observation("claude_code", version)}


def pi_version_observation(command, *, cwd, env):
    output = _version_output(command, cwd=cwd, env=env)
    match = re.fullmatch(rb"(\d{1,4}\.\d{1,4}\.\d{1,4})\r?\n?", output) if len(output) <= 1024 else None
    version = match.group(1).decode("ascii") if match else None
    return {"schema_version": 1, "native_version": version,
        "observation": "executable_version" if version else "version_not_observed",
        "capabilities_verified": False, "compatible_native_requests": [],
        "native_request_basis": "unverified", **control_observation("pi", version)}


def codex_version_observation(command, *, cwd, env):
    """Observe only the selected CLI's version; do not qualify app-server."""
    output = _version_output(command, cwd=cwd, env=env)
    match = re.fullmatch(
        rb"codex-cli (\d{1,4}\.\d{1,4}\.\d{1,4})\r?\n?", output,
    ) if len(output) <= 1024 else None
    version = match.group(1).decode("ascii") if match else None
    contracts = CODEX_NATIVE_REQUEST_CONTRACTS.get(version, ())
    return {"schema_version": 1, "native_version": version,
            "observation": "executable_version" if version else "version_not_observed",
            "capabilities_verified": False,
            "compatible_native_requests": list(contracts),
            "native_request_basis": ("tested_version_contract" if contracts
                                      else "unverified"),
            **control_observation("codex", version)}


def _version_output(command, *, cwd, env, timeout=3.0):
    """Bounded read-only probe under the same birth ownership as the runtime.

    Wait before reading: the OS pipe bounds output, including a flooding peer.
    Read only after the owned tree has stopped, so descendants cannot hold EOF.
    This helper issues no model request and resolves no secrets; env is sealed.
    """
    # Modified for Core: owned backends require all three pipes. Closing stdin
    # gives the probe EOF while keeping Job Object/guardian birth ownership.
    proc = spawn_owned_process(command, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env)
    proc.stdin.close()
    try:
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise NativeAdapterError(ErrorCode.CONFIG_ERROR,
                "Native version probe exceeded its deadline.",
                {"reason": "version_probe_timeout"}) from exc
        if not observe_owned_process(proc)["stop_observed"]:
            raise NativeAdapterError(ErrorCode.CONFIG_ERROR,
                "Native version probe tree stop is unconfirmed.",
                {"reason": "version_probe_stop_unknown"})
        return proc.stdout.read(1025) if code == 0 else b""
    finally:
        try:
            if not observe_owned_process(proc)["stop_observed"]:
                proc.kill()
                proc.wait(timeout=3)
        finally:
            proc.stdout.close()
            proc.stderr.close()


def codex_initialize_observation(result, *, client_name):
    """Retain only the CLI version from this client's user-agent prefix."""
    user_agent = result.get("userAgent") if isinstance(result, dict) else None
    prefix = client_name + "/"
    match = (re.match(r"^(\d{1,4}\.\d{1,4}\.\d{1,4})(?: |$)",
                      user_agent[len(prefix):])
             if isinstance(user_agent, str) and len(user_agent) <= 1024
             and user_agent.startswith(prefix) else None)
    version = match.group(1) if match else None
    return {"schema_version": 1, "native_version": version,
            "observation": "initialize_version" if match else "version_not_observed",
            "capabilities_verified": False,
            "compatible_native_requests": [],
            "native_request_basis": "unverified",
            **control_observation("codex", version)}
