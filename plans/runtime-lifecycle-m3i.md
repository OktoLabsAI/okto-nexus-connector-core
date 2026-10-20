# M3i — Independent inventory observations (foundation)

2026-10-17. Core 0.0.12, branch `feature/v0.0.12`. This is a qualified
technical checkpoint, not an integrated rollout or completion of M3.

## Contract

The inventory envelope and negotiated snapshot format are now 3. Each
discoverable adapter has explicit PENDING, PRESENT, ABSENT or FAILED coverage.
PENDING/FAILED cannot publish candidates or imply NOT_INSTALLED. Completed
observations carry their own age; effective freshness includes that age,
transport age and the consumer's monotonic elapsed time. A sibling's new
publication cannot renew old evidence. The semantic revision includes coverage
state and failure code, excluding time-dependent ages. Availability rows retain
their internal version 2. Formats 1/2 are historical reads only.

`IndependentInventoryObserver` owns one retained async worker per adapter.
Workers discover and validate independently, with bounded retry backoff and
jitter. Results form immutable batches, including the exact raw and augmented
candidates from each attempt. A host must retain the batch it successfully
published; it must not select from newer, unpublished worker state.

Each adapter receives an equal share of the 128-candidate envelope (currently
42). Exceeding that budget fails the entire adapter observation explicitly;
there is no truncation or false absence, and siblings can still publish.
Invalid results and callback failures remain scoped and have path-free error
codes. Cancellation of a separately awaited child is an explicit failed attempt
and does not silently kill the observer. External cancellation of the worker
itself is not a supported shutdown operation.

Explicit refresh returns a frontier requiring an attempt that starts after the
request. Requests during discovery coalesce into the next attempt, without
duplicate workers or an unbounded queue. Failure completes the attempt, not
successful discovery; consumers inspect the resulting coverage. Frontiers
cannot cross observer owners. Shutdown signals cooperative cancellation and
joins every retained producer. Cancelling the close waiter does not release
the running work; late results cannot publish after the shutdown fence.

## Validation

**117 installed cases passed**, no skips or failures, in 10.54 seconds.
Python 3.13.1, Windows 11 AMD64, isolated interpreter, no application source
added to the import path. All 158 installed package files matched the wheel;
selected tests, loaded helpers and current package source matched the recorded
inputs after the campaign. `pip check` and `git diff --check` passed.

Wheel SHA-256:
`13d72e63d1406a8cd6fcb154ce31bb218c0e042cce0bf946cc8e0350f69a3b9a`.
Evidence: [runtime-lifecycle-m3i-results.json](runtime-lifecycle-m3i-results.json),
local full manifest/JUnit under `build/runtime-lifecycle-m3i-workers-installed`.

The cases cover a stalled Pi while Claude/Codex each finish five observations;
per-adapter expiry despite other publications; discovery duration included in
age; automatic retry and restoration; invalid/oversized observations;
concurrent refresh; owner replacement; and a real blocked thread surviving
cancellation of the shutdown waiter. Contract tampering, historical reads,
format negotiation and prior passive-discovery/cancellation tests also pass.
These are synthetic provider observations, not real model execution or proof
of Linux/macOS runtime behavior.

An earlier contract-only installed campaign passed 73 cases. During development,
the handshake schema still declared format 2 and was corrected with explicit
negotiation tests; error assertions were aligned with CoreError.code. An initial
isolated environment lacked rfc8785; the final standalone environment has all
declared dependencies and passes pip check. The final combined campaign has
no failures or environment inheritance.

## Remaining integration

Nexus and Connector still vendor the qualified M3h wheel. Their publication,
refresh acknowledgement, exact selection, per-adapter freshness and retained
selection-baseline migration must be updated together before deploying format
3. Partial/failed observations must preserve consent and cannot prove an
installation disappeared. Follow with joint installed tests and the major real
UI gate. The current global generation 72 remains on M3j Nexus / M3h Core;
read-only Agents verification at 05:34 UTC showed Pi, Claude and Codex Online,
with four warm Pi instances. No restart was performed for this checkpoint.
