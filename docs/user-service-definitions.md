# Portable user-service definition contract

`nexus_connector_core.user_service_definition` contains pure definition values,
Windows logon-task rendering and observed-XML fingerprints. Importing or rendering
does not inspect an OS, open storage, register a task or start any process.

Hosts supply resolved paths, their effective OS principal and canonical component
instance ID. The definition name includes the component and full instance hash;
its revision digest also covers executable, arguments and working directory.
Arguments must reference non-secret context. The host retains responsibility for
authorization, user review, execution context, instance exclusion and drain.

The Windows candidate uses an InteractiveToken principal and user logon trigger,
LeastPrivilege, one concurrent task, no runtime deadline, no hard termination,
and at most three failure retries spaced one minute apart. The foreground
entrypoint must remain alive under the scheduler. This is a logon task, not a
Windows Service, and does not promise operation without login. A host must
prevent automatic restart after an explicit application stop.

After registration, fingerprint the **native exported** XML and retain that
digest with the instance-owned receipt. Before replacement/removal, compare a
fresh native export to the receipt. Do not compare only the original template:
the scheduler can normalize its representation. The fingerprint retains unknown
elements to detect user edits; it never grants permission to overwrite them.

Windows action values with environment expansion syntax are refused rather than
silently changing the selected path. XML escaping and Windows literal argument
quoting preserve spaces and metacharacters without a shell.

References: [Task Scheduler schema](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-schema),
[registration flags](https://learn.microsoft.com/en-us/windows/win32/api/taskschd/ne-taskschd-task_creation),
[RegisterTask and logon types](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskfolder-registertask).

R3 evidence: 13 definition/public-documentation tests passed on Windows, including
native `TASK_VALIDATE_ONLY` validation with verified task absence before/after.
The native test initially rejected a UTF-8 declaration sent through Unicode COM;
the renderer now leaves transport encoding unspecified. No personal task was
installed. Host integration and actual service/login qualification remain open.
