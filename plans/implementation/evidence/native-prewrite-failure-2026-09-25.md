# K04/K05 native pre-write failure classification — 2026-09-25

The copied Codex adapter has several rejection paths that run entirely
before its JSONL write: no bound/live thread, dead child, invalid text,
closing or already-active thread, and exhausted pending-request capacity.
Those paths now attach an explicit `not_sent` marker to the existing
`NativeAdapterError`; the adapter's public exception type/code remains
unchanged for direct consumers. The bridge converts **only** that marker to
`RuntimeCommandNotSent` and clears a tentatively active turn. Errors during
`_write` or without the marker stay uncertain and retain the active slot.
The invalid-text error also no longer embeds raw prompt text in its details.

Synthetic Codex peer coverage proves a second `turn/start` is refused with
`not_sent` while the first is pending. The Core bridge and SQLite kernel test
proves that such a refusal is journaled as `FAILED`, `possible_effect=false`,
`retry_safe=true`, and a later distinct operation can be submitted on the
same session. A separate injected unmarked native error remains journaled
`OUTCOME_UNKNOWN` with `possible_effect=true`. Focused tests passed on
Windows and WSL2.

The same explicit marker now covers Pi's missing/ended/dead session,
invalid prompt, pending-settle and duplicate-interrupt refusals, and Claude
stream's unstarted/wrong session, invalid content and full pending queue.
The copied attach adapter marks its initial missing-session, unsupported-verb
and invalid-content checks before opening a socket. Targeted tests assert
these paths and that invalid Pi/Claude prompt payloads are not echoed in
exception details. Only paths with a known pre-write boundary receive the
marker; Pi RPC request failures, Claude stream write/flush failures, and
attach socket/connect/send errors remain uncertain. Attach remains ack-less
even after a successful write.

This is local proof of specific rejection paths, not a blanket pre-write
guarantee or a real-provider qualification. Real provider timing and
process-crash boundaries remain K05/K10 work. The effective native-build
allowlist is still empty.
