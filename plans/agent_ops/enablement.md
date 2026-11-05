# R3 user-task enablement contract

The pure definition module now renders enablement-only proposals and compares
an observed result against the original native export. It ignores only the
task's Settings/Enabled value when checking structural equality; trigger
enablement, executable/argv, principal, privileges and unknown settings remain
part of the comparison. Schema-default enabled state is supported; duplicate
or invalid enablement values, oversized XML and entities are rejected.

The host still owns scope, authorization, receipts, launch exclusion and all OS
I/O. This helper confirms a retained host intent; it does not establish ownership
or permit adopting foreign tasks. Native fingerprint format remains unchanged.
Core version/pins stay at the coordinated unreleased candidate 0.0.14.

12 definition tests passed, including Task Scheduler TASK_VALIDATE_ONLY for the
disabled proposal, with absence checked before/after. All 130 wheel Python
payloads match source and pass the existing import-boundary audit. Both consumers
receive the same wheel; their installed coordinated campaign has separate Nexus
R3 evidence. No task was registered by these tests, no NXL revision changed and
no package was published.
