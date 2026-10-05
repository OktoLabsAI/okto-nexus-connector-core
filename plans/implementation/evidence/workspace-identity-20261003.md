# Shared workspace launch regression — Windows, 2026-10-03

Core `0.2.58.dev0` replaces mutable workspace directory stat fields in the
managed launch signature with the prepared root fingerprint (canonical path,
device and inode). It resolves the requested path again at each existing
content-validation frontier. Binary and Pi dependency-closure checks remain.

## Deterministic coverage

`tests/test_workspace_launch_identity.py` exercises all three adapters while
opening is paused in the environment callback, after signature capture:

- Child creation, rename and deletion allow opening.
- Root replacement, missing root, root becoming a file, redirected directory
  symlink and executable mutation refuse opening before adapter start.
- All 24 cases ran on this Windows host; none were skipped.

The targeted native bridge and C4/C5 artifact audit run passed 83 tests.
The final full Core run had 1,270 passes, 100 skips and one stale documentation
version assertion. Updating the current documentation version resolved that
assertion: all three public-documentation tests passed against source 0.2.58.
The full-run XML is retained unchanged; no green full-run result is claimed.

## Native concurrent campaign

An isolated Nexus instance opened Claude 2.1.288, Codex 0.159.0-alpha.12.1 and
Pi 0.87.1 concurrently in the same workspace with real provider accounts.
An environment-callback barrier held all three openings after their initial
signature capture. The fixture then created, renamed and deleted a child,
verified directory mtime changed, and released the barrier while a background
writer continued. It completed 5,508 create/rename/delete cycles.

All three harnesses used native tools to create and read their own file.
All three result tokens were published, all three input deliveries reached
read status, and the Meta-harness UI displayed their replies and receipts.
The owner had no failure. Shutdown drained with no resources or errors.
The campaign ran the corrected source before its version label was bumped
from 0.2.57.dev0 to 0.2.58.dev0.

The companion Nexus regression suite passed 30 cases, including session-local
release after a durable no-effect PROFILE_DRIFT receipt, healthy peer and
subsequent sessions, restart recovery, and containment when proof is missing
or effects are possible. No automatic retry is added.

The complete Connector suite passed 734 tests with one skip in 652.09 seconds
in an isolated Python 3.13 environment with the rebuilt Connector wheel and
the vendored Core 0.2.58.dev0 wheel installed. All Python files in the three
deployment wheels were byte-compared with their corresponding source trees.

This is Windows execution evidence. It does not claim a native macOS run,
an atomic launch snapshot, or coverage of every Nexus interaction scenario.
