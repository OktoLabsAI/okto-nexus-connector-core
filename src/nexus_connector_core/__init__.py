"""Embeddable native harness core. Importing this package has no runtime side effects."""

from .models import (
    ExecutionContext,
    Operation,
    OperationReceipt,
    OperationKey,
    SessionKey,
    AttachPolicy, AttachTarget, ClaimedSession,
    SessionClaimPage,
    SessionLeaseState,
    OwnedSlotReservation,
    OwnedSlotPage,
    ProcessBirthEvidence,
    ProcessBirthRecord,
    ProcessBirthObservation,
    RuntimeEvent,
    EventCursor,
    StorageStatus,
    RuntimeSnapshot,
    CoreError,
    InstallationCandidate,
    LaunchIntent,
    PreparedLaunch,
    DiscoveryRequest,
    Inventory,
    OpenOperation,
    TurnOperation,
    ControlOperation,
    NativeApprovalOperation,
    CloseOperation,
    CodexResumeGrant,
    ReconcileRequest,
    ReconcileReport,
    ShutdownPolicy,
    ShutdownReport,
)
from .protocol import CONTRACT_REVISION, intent_hash, submit_frame_intent_hash
from .ports import OwnedSlotLedger, RuntimeCore
from .composition import create_runtime
from .catalog import (
    RuntimeDescriptor, RuntimeCatalog, get_runtime_catalog,
    CATALOG_FORMAT_VERSION,
)
from .availability import (
    AvailabilityReport, CandidateAvailability,
    evaluate_runtime_availability, AVAILABILITY_FORMAT_VERSION,
)
from .runtime import LocalRuntimeCore
from .slot_ledger import SQLiteOwnedSlotLedger

__version__ = "0.2.9.dev0"

__all__ = [
    "CONTRACT_REVISION", "CoreError", "ExecutionContext", "Operation",
    "OperationReceipt", "OperationKey", "SessionKey", "AttachPolicy", "AttachTarget", "ClaimedSession", "SessionClaimPage", "SessionLeaseState", "OwnedSlotReservation", "OwnedSlotPage", "ProcessBirthEvidence", "ProcessBirthRecord", "ProcessBirthObservation", "RuntimeEvent", "EventCursor", "StorageStatus", "RuntimeSnapshot", "intent_hash", "submit_frame_intent_hash",
    "InstallationCandidate", "LaunchIntent", "PreparedLaunch",
    "DiscoveryRequest", "Inventory", "OpenOperation", "TurnOperation",
    "ControlOperation", "NativeApprovalOperation", "CloseOperation", "CodexResumeGrant", "ReconcileRequest",
    "ReconcileReport", "ShutdownPolicy", "ShutdownReport",
    "RuntimeCore", "LocalRuntimeCore", "create_runtime", "OwnedSlotLedger",
    "RuntimeDescriptor", "RuntimeCatalog", "get_runtime_catalog", "CATALOG_FORMAT_VERSION",
    "AvailabilityReport", "CandidateAvailability", "evaluate_runtime_availability", "AVAILABILITY_FORMAT_VERSION",
    "SQLiteOwnedSlotLedger",
]
