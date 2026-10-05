# C10 cancellation boundary and hosted status — 2026-10-02

Hosted run 37000873878 failed on Windows Python 3.11 in the setup of
`test_retained_ledger_does_not_delay_other_resource_force`: the first resource's
release obligation was absent before the cross-resource shutdown assertion.
The fixture cancelled public open after an unconditional 200 ms sleep.

A 350 ms delay in the durable receipt lookup reproduces the same setup failure
against installed Core .56; the zero-delay control passes. See
`c10-admission-before.xml` (one pass, one failure). Cancellation can occur before
any native producer/owned reservation exists, so a release obligation is not
required at that earlier boundary. The original hosted run did not retain its
precise scheduler/storage timing; this reproduction establishes the fixture
defect, not a measurement of that hosted delay.

Both C10 setup helpers now wait for an event set by the actual synthetic native
factory, then cancel the caller and release the native factory's held result.
They require `CancelledError` instead of suppressing arbitrary exceptions.
The deliberate delayed-admission case remains parametrized. Original checks
for retained producers, no backend cancellation, cross-resource containment,
idempotent late convergence and acknowledgement-loss recovery remain intact.
No production Core file, timeout policy or packaged byte changed.

Eight installed tests passed on Windows Python 3.13.1 (10.22 seconds) and WSL
Linux Python 3.12.13 (10.89 seconds), using the already reviewed .56 wheel.
See `c10-admission-windows.xml` and `c10-admission-linux.xml`.
A fresh Windows Python 3.11.14 environment also passed the same eight tests
in 10.65 seconds (`c10-admission-windows311.xml`). This covers the affected
minor version locally, not the hosted Windows Server/Python 3.11.9 environment
or the complete hosted matrix.

The subsequent run 37001262922 at `10585bb` is terminal: Windows Python 3.12
passed including build/offline-install steps, while five other jobs were never
started. GitHub reported failed account payments or a spending-limit restriction.
`hosted-10585bb-billing.txt` preserves its annotations and job IDs. These five
failures are infrastructure refusals, not five additional regression failures.
Hosted qualification remains open pending account intervention and a complete
run of the reviewed code. No workflow retry, billing or limit change was made.
