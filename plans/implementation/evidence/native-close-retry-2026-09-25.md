# K04 native close evidence and retry — 2026-09-25

The copied-adapter async bridge now distinguishes *close started* from
*stopped*. Starting close prevents further sends, but a connector exception or
a close return without `stop_observed` does not mark the bridge closed. A
subsequent Core shutdown or explicit close can retry containment without
re-sending the native `end` command. The bridge marks closed only after its
own lifecycle observation or a later `observe()` proves stop.

The runtime releases ownership when stop is observed, but reports `unknown`
if the backend cannot attribute the stop to graceful or forced closure. It no
longer fabricates `forced` from the observation alone. Synthetic tests cover
exception, unobserved return, retry, one-time `end`, and the distinct receipt,
ownership and shutdown outcomes. These do not qualify a real provider's stop
mechanism or prove tree containment on every supported OS.
