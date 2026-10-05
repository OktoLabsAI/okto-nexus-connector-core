# Native protocol readiness

Managed execution separates installation integrity from protocol compatibility.
An observed version and a valid installation identity allow an installed harness
to attempt startup on a supported platform. A recorded exact-build hash is no
longer required for conversation startup. Fingerprints, selected paths, workspace
identity, lease deadlines and process containment remain enforced.

Codex validates initialize and thread startup. Pi validates its correlated
get_state response. Unrecorded Claude builds must return a correlated successful
initialize response within ten seconds before the session is exposed to work.
Historical build campaigns remain evidence for specific control capabilities;
startup does not automatically grant every optional control.

The Connector installation check calls probe_selected_protocol in a temporary
workspace and home, using a filtered environment without provider credentials.
It performs startup negotiation, not a model request. Passing this check does
not prove provider authentication or model availability. Actual session startup
still validates its selected installation and protocol.

A confirmed native startup failure is recorded as a failed operation. If process
cleanup or the operation outcome is uncertain, reconciliation is still required;
the failure must never be reported as a safely completed shutdown.
