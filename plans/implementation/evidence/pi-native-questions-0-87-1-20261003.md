# Pi 0.87.1 native questions

Isolated campaign `pi-questions-campaign-20261003-132655` on Windows used the
installed Pi 0.87.1, provider `zai`, model `glm-5.3`, thinking `low`, and the
Core-owned `nexus_ask_user` extension tool. The operator answered through the
Nexus Meta-Harness UI. Real native `tool_execution_end` results, with
`isError: false`, confirmed all five cases:

| Native UI method | Submitted choice | Native tool result |
| --- | --- | --- |
| select | Green | `answer: "Green"` |
| input | Pi texto livre 42 | same text |
| confirm | No | `answer: false` (boolean) |
| editor | two lines: Linha 1 / Linha 2 | same text with a literal newline |
| input, cancelled | Deny runtime request | `cancelled: true` |

The model continued and published a correlated reply for every case; all five
originating messages were acknowledged. The session and lease then closed with
no owner failure. The native response uses the original request ID, with either
`value`, `confirmed`, or `cancelled`, and produces no command-response envelope.

An earlier exploratory campaign captured a real select request but was stopped
before answering while Core's adapter allowlist/projection was being extended.
Closing that still-waiting turn produced a containment reconciliation error;
that path still needs investigation and is not qualified by the successful
completed-turn close above.
