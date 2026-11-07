# Cooperative drain — Core 0.0.14 feature candidate

The runtime can now fence new productive work and observe existing work without
invoking shutdown containment. Authorized decisions, receipts and results remain
available. The host chooses when proven quiescence or explicit operator force
permits its existing containment path. Unknown ownership never becomes success.

Public additions: begin_drain(), drain_status(), drain_revision() and pure
combine_drain_status(). Shared-journal aggregation resolves only an exact claim
retained by another known owner; orphans and changed revisions remain pending.
R4 stopped refusals accept RUNTIME_DRAINING without changing wire authority.

Durable change: additive operation_actions metadata committed with admission;
receipt hashes and operations_v2 stay unchanged. Historical unknown actions are
not inferred or backfilled. Custom journals must implement the new admission
keywords and passive snapshot API. Existing shutdown semantics are preserved.
Reverting code leaves the additive table harmlessly present; unresolved records
written without metadata are conservative on a later upgrade.

Validation: 217 unique source cases and 217 unique installed cases, not added
together. The immutable installed full selection passed216 and had one fixture
import failure; that one case passed after adding the copied test parent to
pytest's fixture path. Product, tests and wheel bytes were unchanged. Earlier
preparation/collection failures and source fixture failures are retained.
All166 package payload files match source, wheel and installed bytes. pip check
passed; source Ruff review found no new issues against12 retained baseline items.

Only synthetic native peers and disposable SQLite/state were used. No provider,
personal vault or OS service was invoked. Host integration and actual M1 remain
separate qualification gates. Scripts, input hashes, dependency versions, XML
and exact-byte manifest are retained here.
