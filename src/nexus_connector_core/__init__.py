"""Embeddable native harness core. Importing this package has no runtime side effects."""

from .discovery_control import DiscoveryCancelled
from .automation import DEFAULT_RUNTIME_AUTOMATION, RuntimeAutomationPolicy, RuntimeAutomation
from .models import (
    ControlTargeting,
    R4Authority, R4LeaseApplication,
    ExecutionContext,
    Operation,
    OperationReceipt,
    OperationKey,
    SessionKey,
    AttachPolicy, AttachTarget, ClaimedSession,
    SessionClaimPage,
    SessionLeaseState,
    OwnedSlotReservation, OwnedSlotState,
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
    HarnessSettings,
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
from .frame_codec_r4 import (
    R4_CONTRACT_REVISION, R4_PREVIEW_REVISION, R4_BUNDLE_EXECUTABLE, decode_r4_frame,
    encode_r4_frame, r4_submit_intent_hash, verify_r4_bundle, verify_r4_development_bundle,
)
from .lease_reducer_r4 import (
    R4LeaseAttempt, R4LeaseProjection, r4_lease_renew_frame,
    reduce_r4_lease_grant, reduce_r4_lease_applied, r4_lease_productive,
)
from .receipt_reducer_r4 import R4ReceiptProjection, reduce_r4_receipt
from .receipt_binding_r4 import (
    prepare_r4_receipt_binding, validate_r4_receipt_binding, project_r4_bound_receipt,
)
from .resource_release_r4 import r4_resource_release_digest, project_r4_resource_release
from .receipt_bridge_r4 import (
    project_r4_open_receipt, project_r4_turn_receipt, project_r4_steer_receipt,
    project_r4_interrupt_receipt, project_r4_close_receipt, project_r4_decision_receipt,
)
from .decision_bridge_r4 import r4_native_decision_operation, r4_operational_request_hash
from .control_reducer_r4 import (
    R4ReconcileAttempt, R4ControlProjection, R4AttachAttempt,
    R4LaneProjection, reduce_r4_reconcile_accepted,
    reduce_r4_binding_attached, r4_lane_ready,
)
from .event_reducer_r4 import (
    R4EventCommitProjection, reduce_r4_durable_event_batch,
    r4_event_ack_frame,
)
from .approval_reducer_r4 import (
    R4ApprovalProjection, reduce_r4_approval_request,
    reduce_r4_approval_decision,
)
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
from .installation import (
    INSTALLATION_REF_SCHEME, REF_AMBIGUOUS, REF_NOT_FOUND,
    installation_ref, resolve_installation,
)
from .runtime import LocalRuntimeCore
from .slot_ledger import SQLiteOwnedSlotLedger
from .executor_inventory import (
    SNAPSHOT_FORMAT_VERSION, build_executor_inventory_snapshot,
    get_executor_inventory_schema,
    calculate_inventory_revision,
    verify_executor_inventory_snapshot,
)
from .discovery import discover_installations
from .provider_discovery import discover_provider_home
from .harness_configuration import discover_harness_configuration, query_harness_configuration, CONFIGURATION_SCHEMA_VERSION, validate_harness_settings, harness_settings_dict, validate_harness_configuration
from .configuration_file import parse_harness_configuration_file, export_harness_configuration_file
from .configuration_probe import probe_selected_configuration
from .native.native_inputs import response_for as native_input_response
from .targeting import get_control_targeting, validate_control_target
from .close_operation import r4_close_operation

__version__ = "0.2.63.dev0"

__all__ = [
    "DEFAULT_RUNTIME_AUTOMATION", "RuntimeAutomationPolicy", "RuntimeAutomation",
    "native_input_response",
    "HarnessSettings", "validate_harness_settings", "harness_settings_dict", "validate_harness_configuration",
    "parse_harness_configuration_file", "export_harness_configuration_file",
    "probe_selected_configuration",
    "discover_harness_configuration", "query_harness_configuration", "CONFIGURATION_SCHEMA_VERSION",
    "prepare_r4_receipt_binding", "validate_r4_receipt_binding", "project_r4_bound_receipt",
    "r4_close_operation",
    "ControlTargeting", "get_control_targeting", "validate_control_target",
    "R4Authority", "R4LeaseApplication",
    "CONTRACT_REVISION", "CoreError", "ExecutionContext", "Operation",
    "R4_CONTRACT_REVISION", "R4_PREVIEW_REVISION", "R4_BUNDLE_EXECUTABLE", "decode_r4_frame",
    "encode_r4_frame", "r4_submit_intent_hash", "verify_r4_bundle", "verify_r4_development_bundle",
    "R4LeaseAttempt", "R4LeaseProjection", "r4_lease_renew_frame",
    "reduce_r4_lease_grant", "reduce_r4_lease_applied", "r4_lease_productive",
    "R4ReceiptProjection", "reduce_r4_receipt",
    "project_r4_open_receipt", "project_r4_turn_receipt", "project_r4_steer_receipt",
    "project_r4_interrupt_receipt", "project_r4_close_receipt", "project_r4_decision_receipt",
    "r4_native_decision_operation", "r4_operational_request_hash",
    "R4ReconcileAttempt", "R4ControlProjection", "R4AttachAttempt",
    "R4LaneProjection", "reduce_r4_reconcile_accepted",
    "reduce_r4_binding_attached", "r4_lane_ready",
    "R4EventCommitProjection", "reduce_r4_durable_event_batch",
    "r4_event_ack_frame",
    "R4ApprovalProjection", "reduce_r4_approval_request",
    "reduce_r4_approval_decision",
    "OperationReceipt", "OperationKey", "SessionKey", "AttachPolicy", "AttachTarget", "ClaimedSession", "SessionClaimPage", "SessionLeaseState", "OwnedSlotReservation", "OwnedSlotState", "r4_resource_release_digest", "project_r4_resource_release", "OwnedSlotPage", "ProcessBirthEvidence", "ProcessBirthRecord", "ProcessBirthObservation", "RuntimeEvent", "EventCursor", "StorageStatus", "RuntimeSnapshot", "intent_hash", "submit_frame_intent_hash",
    "InstallationCandidate", "LaunchIntent", "PreparedLaunch",
    "DiscoveryRequest", "Inventory", "OpenOperation", "TurnOperation",
    "ControlOperation", "NativeApprovalOperation", "CloseOperation", "CodexResumeGrant", "ReconcileRequest",
    "ReconcileReport", "ShutdownPolicy", "ShutdownReport",
    "RuntimeCore", "LocalRuntimeCore", "create_runtime", "OwnedSlotLedger",
    "RuntimeDescriptor", "RuntimeCatalog", "get_runtime_catalog", "CATALOG_FORMAT_VERSION",
    "AvailabilityReport", "CandidateAvailability", "evaluate_runtime_availability", "AVAILABILITY_FORMAT_VERSION",
    "INSTALLATION_REF_SCHEME", "REF_NOT_FOUND", "REF_AMBIGUOUS", "installation_ref", "resolve_installation",
    "discover_installations", "DiscoveryCancelled",
    "SQLiteOwnedSlotLedger",
    "SNAPSHOT_FORMAT_VERSION", "build_executor_inventory_snapshot",
    "get_executor_inventory_schema",
    "calculate_inventory_revision",
    "verify_executor_inventory_snapshot",
]
