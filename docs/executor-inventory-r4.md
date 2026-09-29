# Executor inventory projection (R4 draft)

`build_executor_inventory_snapshot(candidates, *, server_id, executor_id,
producer_instance_id, publication_sequence, observation_age_ms)` is the
shared, passive projection for the Nexus Server and Connector. It evaluates
the supplied full `InstallationCandidate` objects on the execution host and
returns a path-free JSON object with catalog format 1, availability format 2,
ordered evidence and a complete `sha256:` revision computed with the Core's
RFC 8785 canonicalizer. The revision excludes publication sequence, age,
producer instance and display labels. It includes candidate ref, content and
build evidence, technical assessment, platform, and catalog capabilities.

`verify_executor_inventory_snapshot(snapshot)` checks shape, format, evidence
consistency and revision before the receiving application stores it. The
receiving application must still authenticate the producer, compare the
`server_id` and `executor_id` to the ticket, apply publication sequence CAS,
set a local freshness deadline, and enforce agent policy. A valid inventory
does not authorize a binding or start a process. The full candidates and path
resolution remain on the producing host.

This module is an R4 inventory building block. The NXL contract still reports
the r3 revision; remote execution must remain disabled until the separate R4
bundle, Server admission, and Connector dispatcher pass their integration gates.

Development wheel built locally on 2026-09-29:
`nexus_connector_core-0.2.11.dev0-py3-none-any.whl`, SHA-256
`41193bc203bb6425163b8992effb6dfa701d3ef309ed08832a58d84cc0c3158d`.
The wheel is a handoff artifact, not a PyPI publication or provider test.

Core `0.2.12.dev0` adds the public `discover_installations` facade. It
enumerates the managed adapters from the Core catalog and retains full local
candidate objects without composing a runtime, opening a journal, or starting
a provider. `LocalRuntimeCore.discover` now uses that same path. The wheel
`nexus_connector_core-0.2.12.dev0-py3-none-any.whl` has SHA-256
`bd5326357608906bdd80ccefc3db4890137d9e8dc00935a88c5f6dd955bf9d8e`.
The NXL wire revision remains r3; this facade does not enable remote effects.
