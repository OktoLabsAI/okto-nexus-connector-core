# Durable terminal R4 close — September 30, 2026

Core 0.2.33.dev0 commits SUCCEEDED for R4 policy close after observing confirmed physical stop and releasing its owned slot. The kernel writes this terminal receipt directly after the successful close effect. Existing nonterminal operations and legacy close semantics retain their stages.

The retained close producer owns this write. Canceling a public waiter does not cancel the producer; concurrent same-ID calls join it, later calls replay the durable terminal fact, and an unknown native outcome remains OUTCOME_UNKNOWN. Four new tests cover normal/forced/unknown close and cancellation while the terminal journal write is held.

Installed focused Core regression: 76 passed, covering close policy, R4 leases, kernel/crash admission, journal conformance and receipt projection/reduction. This is a targeted campaign, not a new full-suite release qualification. Source close/lease regression: 33 passed; four new tests passed separately.

The real provider probes use the installed wheel and locally constructed R4 grants. Their adjacent terminal-close-*-installed.json evidence records both the returned and durable close stages. The consumer integration asserts SUCCEEDED through actual daemon HTTP/WSS receipt publication.

Remaining work includes publication/reconciliation after delayed completion, disconnection and crash; disk-error recovery; all other operation lifecycles; full Server-issued native provider journeys and M00–M13 acceptance. No milestone or gate is closed.
