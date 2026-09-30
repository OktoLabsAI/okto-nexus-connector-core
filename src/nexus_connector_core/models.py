"""Small immutable, application-neutral public data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class CoreError(Exception):
    def __init__(self, code: str, stage: str, *, possible_effect: bool = False,
                 retry_safe: bool = False, operation_id: str | None = None,
                 message: str | None = None):
        # C3/S07: ``code`` stays a stable machine-readable enum;
        # ``message`` carries human diagnostics (redacted by the raiser)
        # without being concatenated into the classification field.
        super().__init__(message if message is not None else code)
        self.code = code
        self.stage = stage
        self.possible_effect = possible_effect
        self.retry_safe = retry_safe
        self.operation_id = operation_id
        self.message = message if message is not None else code


class EffectNotSent(Exception):
    """The native command was rejected before any effect-capable write."""

    def __init__(self, message: str, *, code: str = "CAPABILITY_UNSUPPORTED"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ControlTargeting:
    """Implemented control shape, never a grant or provider qualification."""

    action: str
    supported: bool
    native_turn_id: str  # required | optional | forbidden
    requires_active_run: bool
    steer_timing: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "supported": self.supported,
                "native_turn_id": self.native_turn_id,
                "requires_active_run": self.requires_active_run,
                "steer_timing": self.steer_timing}


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    server_id: str
    executor_id: str
    binding_id: str
    agent_id: str
    workspace_id: str
    authorization_revision: int
    configuration_revision: int
    connection_generation: int
    lease_deadline_monotonic: float
    allowed_actions: frozenset[str]
    session_owner_generation: int = 1


@dataclass(frozen=True, slots=True)
class Operation:
    operation_id: str
    session_id: str
    action: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    expected_turn_id: str | None = None


@dataclass(frozen=True, slots=True)
class OperationReceipt:
    operation_id: str
    intent_hash: str
    stage: str
    possible_effect: bool
    retry_safe: bool
    session_id: str
    native_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class OperationKey:
    server_id: str
    executor_id: str
    operation_id: str


@dataclass(frozen=True, slots=True)
class SessionKey:
    server_id: str
    executor_id: str
    session_id: str


@dataclass(frozen=True, slots=True)
class ClaimedSession:
    key: SessionKey
    opening_operation_id: str
    opening_connection_generation: int | None = None
    opening_owner_generation: int | None = None


@dataclass(frozen=True, slots=True)
class SessionLeaseState:
    """Durable last-known lease fence for one claimed session.

    Historical CAS evidence written with the session claim and updated by
    `renew_lease`/`revoke_lease`. It is not process liveness, not a lease
    deadline and not takeover authority.
    """

    key: SessionKey
    connection_generation: int
    owner_generation: int
    authorization_revision: int
    configuration_revision: int
    revoked: bool


@dataclass(frozen=True, slots=True)
class SessionClaimPage:
    claims: tuple[ClaimedSession, ...]
    high_water_rowid: int
    next_after_rowid: int | None


@dataclass(frozen=True, slots=True)
class OwnedSlotReservation:
    key: SessionKey
    opening_operation_id: str


@dataclass(frozen=True, slots=True)
class OwnedSlotPage:
    reservations: tuple[OwnedSlotReservation, ...]
    high_water_rowid: int
    next_after_rowid: int | None


@dataclass(frozen=True, slots=True)
class ProcessBirthEvidence:
    """Historical OS identity of a Core-owned container, never PID authority."""

    platform: str
    pid: int
    birth_token: str
    containment: str


@dataclass(frozen=True, slots=True)
class ProcessBirthRecord:
    key: SessionKey
    opening_operation_id: str
    evidence: ProcessBirthEvidence


@dataclass(frozen=True, slots=True)
class ProcessBirthObservation:
    """Transient PID observation; no process-control or lease authority."""

    record: ProcessBirthRecord | None
    state: str


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    server_id: str
    executor_id: str
    session_id: str
    stream_epoch: str
    sequence: int
    category: str
    native_type: str | None
    payload: Mapping[str, Any]
    operation_id: str | None = None


@dataclass(frozen=True, slots=True)
class EventCursor:
    server_id: str
    executor_id: str
    session_id: str
    stream_epoch: str
    after_sequence: int = 0


@dataclass(frozen=True, slots=True)
class StorageStatus:
    database_bytes: int
    wal_bytes: int
    shm_bytes: int
    page_size: int
    page_count: int
    free_pages: int
    max_bytes: int

    @property
    def total_bytes(self) -> int:
        return self.database_bytes + self.wal_bytes + self.shm_bytes


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    session_id: str
    process_state: str
    turn_state: str
    ownership: str
    last_sequence: int
    lease_state: str = "UNKNOWN"
    connection_generation: int | None = None
    session_owner_generation: int | None = None


@dataclass(frozen=True, slots=True)
class InstallationCandidate:
    adapter_id: str
    executable: str
    fingerprint: str
    source: str
    trust: str
    version: str | None = None
    architecture: str | None = None
    launch_script: str | None = None
    # PC09: portable, path-free identity of the build content. The
    # path-bound ``fingerprint`` remains the local binding proof.
    build_identity: str | None = None
    # C11/A11-01: opaque ref of the SELECTABLE LOCAL INSTALLATION
    # (canonical executable + launch script; ``installation.py``).
    # Byte-identical copies in distinct locations are distinct
    # installations: distinct refs, same build identity.
    installation_ref: str | None = None


@dataclass(frozen=True, slots=True)
class LaunchIntent:
    agent_id: str
    workspace_id: str
    adapter_id: str
    mode: str = "managed"
    model: str | None = None
    auth_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PreparedLaunch:
    intent: LaunchIntent
    candidate: InstallationCandidate
    argv: tuple[str, ...]
    cwd: str
    requested_root: str
    root_fingerprint: str
    profile_fingerprint: str
    secret_refs: tuple[str, ...]
    sandbox_applied: bool = False


@dataclass(frozen=True, slots=True)
class DiscoveryRequest:
    # C9/C01: None asks the CATALOG which adapters admit discovery on
    # this host (managed executables) - the caller never needs its own
    # adapter array; an explicit tuple remains a filter; () is "none".
    adapter_ids: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class Inventory:
    candidates: tuple[InstallationCandidate, ...]


@dataclass(frozen=True, slots=True)
class OpenOperation:
    operation_id: str
    session_id: str
    stream_epoch: str
    prepared: PreparedLaunch


@dataclass(frozen=True, slots=True)
class CodexResumeGrant:
    """Trusted-host proof for binding one stored Codex thread to one open.

    C2/R09: this is the PUBLIC resume contract. Hosts construct it from
    ``nexus_connector_core`` and the copied-adapter bridge validates the
    exact type plus every binding field; a structural look-alike is not
    accepted. All fields come from the trusted host's own verification
    of the persisted rollout.
    """

    thread_id: str
    session_id: str
    server_id: str
    executor_id: str
    binding_id: str
    agent_id: str
    workspace_id: str
    session_owner_generation: int
    candidate_fingerprint: str
    root_fingerprint: str
    profile_fingerprint: str
    terminal_observed: bool
    persisted_rollout_observed: bool
    exclusive_owner: bool


@dataclass(frozen=True, slots=True)
class TurnOperation:
    operation_id: str
    session_id: str
    text: str
    expected_turn_id: str | None = None


@dataclass(frozen=True, slots=True)
class ControlOperation:
    operation_id: str
    session_id: str
    verb: str
    text: str | None = None
    expected_turn_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class NativeApprovalOperation:
    operation_id: str
    session_id: str
    request: Mapping[str, Any]
    decision: str
    operator_response: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AttachTarget:
    """Host-chosen external attach target evidence (C1/PC12).

    The host selects and approves exactly one target with verifiable
    technical identity; the Core never auto-attaches to the first process
    or window found, and never infers consent from a shared OS user.
    This is target *evidence* for a future qualified attach mode - it
    grants no process-control authority by itself.
    """

    substrate: str
    identity: Mapping[str, Any]
    approved_by_host: bool = False

    def __post_init__(self) -> None:
        if (type(self.substrate) is not str or not self.substrate or
                len(self.substrate) > 80 or
                not isinstance(self.identity, Mapping) or
                type(self.approved_by_host) is not bool):
            raise ValueError("invalid attach target")
        encoded = repr(sorted(self.identity.items()))
        if len(encoded) > 4096:
            raise ValueError("attach target identity too large")


@dataclass(frozen=True, slots=True)
class AttachPolicy:
    """Detach semantics for external targets: never kill, only revoke."""

    detach_on_stop: bool = True
    revoke_handles_on_lease_expiry: bool = True


@dataclass(frozen=True, slots=True)
class CloseOperation:
    operation_id: str
    session_id: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ReconcileRequest:
    server_id: str
    executor_id: str
    operation_ids: tuple[str, ...] = ()
    session_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    receipts: tuple[OperationReceipt | None, ...]
    snapshots: tuple[RuntimeSnapshot, ...]


@dataclass(frozen=True, slots=True)
class ShutdownPolicy:
    drain_seconds: float = 30.0
    interrupt_seconds: float = 15.0


@dataclass(frozen=True, slots=True)
class ShutdownReport:
    session_outcomes: Mapping[SessionKey, str]
