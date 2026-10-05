# Owned close completion after observation timeout

Core 0.2.34.dev0 adds close(..., wait_for_completion=True) for explicit-policy close. It joins the retained producer without changing physical drain/interrupt/force deadlines. Cancellation detaches the observer; durable write failures propagate. The default public observation keeps its prior bounded behavior.

Two added tests join an existing close after the default observer has timed out, hold the terminal write beyond the deadline, and check terminal success or an injected write failure. Existing cancellation and idempotence tests remain applicable.

Source directed tests: 22 passed. Installed focused kernel/journal/receipt/lease/close regression: 78 passed. The adjacent late-close-installed-core.* files and artifact manifest record the installed campaign. Both product consumers adopt the explicit complete wait for their R4 operation owner.

This proves an in-process completion observation path, not reconnection, restart recovery or the remaining release gates.
