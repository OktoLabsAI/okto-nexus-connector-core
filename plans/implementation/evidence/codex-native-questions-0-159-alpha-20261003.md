# Codex native questions — 0.159.0-alpha.12.1

On 2026-10-03, the installed Windows Codex app-server was exercised through an
isolated Nexus HTTP application with the production Core transport and UI.
The runtime used gpt-6.1-sol, low reasoning effort, approvalPolicy=never,
sandbox=workspace-write and user_input=enabled. The latter maps to
thread/start.config.features.default_mode_request_user_input=true, observed in
the installed CLI's `features list` as an under-development feature.

The first real request exposed an incorrect Core restriction: the native
requestUserInput frame had isBlocking=false and autoResolutionMs=null, and the
Core rejected it. The installed `app-server generate-json-schema --experimental`
contract defines isBlocking as a boolean. Both values are now accepted; the
existing session, turn, request hash, recipient and dispatch checks remain.

The corrected campaign was `codex-questions-campaign-20261003-135959`.
Two native requests were answered using Meta-Harness controls:

- Select Green: the native continuation returned `CODEX_QUESTION_OK Green`.
- Select Write another answer and type Violet 42: the native continuation
  returned `CODEX_CUSTOM_OK Violet 42`.

Both requests were isBlocking=false. No automatic or fabricated answer was sent.
The operator's explicit response was delivered as the native answers map while
the original turn remained active. Both messages received their completed ACKs.
This qualifies only item/tool/requestUserInput on this exact build, not other
approval or elicitation methods, and not managed harness-to-harness routing.

Screenshots and redacted result evidence are in the task outputs directory:
codex-native-question-response.png, codex-native-custom-question.png and
codex-native-question-evidence.json.
