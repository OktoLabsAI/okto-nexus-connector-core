# M4d4e6: bounded forward-head prefix proof

Core now records sparse digest checkpoints as part of completed registration
batches. A previous ledger upgrades through a separate resumable index pass,
at most 128 registrations per transaction. New registrations during conversion
remain in revision order and are included before completion. An exact digest
at an older revision reads the nearest checkpoint and hashes at most 128 rows.

Nexus and Connector convert the index in retained background work and compare
their stored digest with Core's digest at that revision before replacing an
audit token. A forward Core head whose prefix diverges raises `PROFILE_DRIFT`.
This remains evidence only; both hosts still perform their existing physical
audit and do not admit work based on the token.

The 26 source and 26 installed Core registry/cost tests passed at 1k, 10k and
100k registrations. Older-digest reads used 1,108, 228 and 388 SQLite VM
steps respectively. The installed Core wheel SHA-256 is
`f24687913600dfbdfa85cf5c04f7106adca0a4b6903f5981f6e783e7fe200038`.
