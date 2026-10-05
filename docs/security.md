# Trust and release limits

The host is responsible for issuing `ExecutionContext`, selecting native
executables and workspace paths, resolving secret references, approving
configuration writes, and committing canonical Server ingress. Core scopes
operations by Server/executor/session and fails closed on stale generations,
unexpected adapter IDs, profile/root drift and unknown contract revisions.
Its local redaction and restricted environment reduce exposure, but do not
protect against a compromised trusted host or provider.

Only an owned managed process tree may receive a force-stop request. An attach
target is externally owned. Shutdown, clock rollback, disk pressure and
provider write errors can leave an `unknown` effect/ownership; callers must
retain those facts and reconcile rather than silently retry or report success.
SQLite logical quotas and checkpointing are not a complete disk quota; the
journal additionally enforces a hard WAL admission ceiling with automatic
bounded-truncate maintenance — a pinned reader that prevents truncation
stops new admissions honestly (`JOURNAL_FULL`, with a reserve kept for
critical writes) instead of letting the WAL grow without bound.

Owned launches may set `max_tree_processes`: on Windows this is
kernel-enforced through the job object's active-process limit (process
creation inside the tree fails once the cap is reached); on Linux it is
recorded but not kernel-enforced and is reported as such.
`owned_tree_census` offers a bounded read-only PID census of one owned tree
(job object on Windows; the guardian plus the isolated native session's
process group on Linux). Both are observations, never authority to signal
or adopt a PID, and descendants that escape via `setsid` remain outside
census and containment alike.

The release workflow is manual, main-only for publication and separates the
build/test job from a PyPI-environment OIDC job. It requires reviewed version,
artifact hashes and environment approval secrets, but no hosted run, legal
license review or PyPI trusted-publisher setup has yet been completed. The
current development artifact is deliberately not publishable as a stable
release. See the [release evidence](../plans/implementation/evidence/release-workflow-2026-09-25.md).

## Operational native approval proposals

A correlated native approval event carries two separate fields in the authenticated execution plane: native_approval is an immutable copy of the original operational proposal; native_approval_display is its redacted presentation. The original native request ID, native hash, parameters and local generation remain unchanged. Only the adapter's correlation port can create this operational field; an arbitrary native event payload cannot.

Hosts must persist the operational proposal separately from presentation and use the original when admitting a decision. User-facing event/history projections must use the display field and must not expose the operational payload. This proposal is distinct from operator input responses, whose sensitive content still requires the explicit host retention policy. The Core does not provide a new secret store or promise recovery of unretained response content.

Claude MCP permission names are bounded and classified for an explicit operator decision. This classification does not authorize a tool. Stream launch arguments with an approved model or MCP suffix retain the stdio permission channel when native approvals are enabled.
