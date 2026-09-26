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
SQLite logical quotas and checkpointing are not a complete disk quota.

The release workflow is manual, main-only for publication and separates the
build/test job from a PyPI-environment OIDC job. It requires reviewed version,
artifact hashes and environment approval secrets, but no hosted run, legal
license review or PyPI trusted-publisher setup has yet been completed. The
current development artifact is deliberately not publishable as a stable
release. See the [release evidence](../plans/implementation/evidence/release-workflow-2026-09-25.md).
