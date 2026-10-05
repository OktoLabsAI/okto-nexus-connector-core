# Confirmed native close outcomes — September 30, 2026

Core 0.2.32.dev0 corrects an ambiguity observed with real Codex 0.159.0 and Claude 2.1.282: the adapter previously returned None after cleanup, so the bridge could only call a stop graceful if it was already observed before close. Native processes stopping during close were returned as unknown despite subsequent confirmed stop.

Codex transport now records termination requests and returns forced only after owned-tree stop is observed. Claude distinguishes EOF/wait completion from timeout or explicit force. Force intent is retained across subsequent observations. The bridge accepts the classification only with its own post-close tree-stop observation. Unconfirmed stops and legacy adapters retain conservative behavior.

Fifteen focused tests cover EOF completion, timeout kill, prior force, absent tree-stop proof, and bridge report validation. A combined source campaign passed 48 cases but the global control-thread census test saw another test's executor; the census test passed alone. The installed full-suite result is recorded in the coordinated Nexus evidence.

## Real installed results

Codex and Claude completed R4 turns and returned close SUBMITTED with no receipt error, followed by shutdown already_closed. The probe now records the durable close receipt as well as the immediate response. The close receipt remains SUBMITTED; this increment does not claim terminal close publication completeness.

The native grant is locally constructed by the Core probe. Server-issued authority, complete embedded/remote journeys, full provider/OS shutdown qualification and remaining release gates stay open. No product readiness flag changed.

Artifacts and installed regressions: okto_labs_okto_nexus/plans/r4_execution/evidence/native-close-artifacts.json and native-close-installed-*.json/xml/log. Exact real-provider commands/results are the adjacent close-outcome-*-installed.json files.
