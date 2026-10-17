# Support assistant evaluation

**Mode: rule-based fallback (no ANTHROPIC_API_KEY set)**

These numbers come from the deterministic rule-based responder, not the live model: this environment has no ANTHROPIC_API_KEY. The live tool-calling path (backend/app/support_assistant.py, `_run_live_model`) is implemented against the same tool layer and the same grader, and will report `live model` here automatically the first time it runs with a real key.

Ran 62 cases in 3.3s.

## Results by group

| Group | Passed | Total | Accuracy |
|---|---|---|---|
| status | 10 | 10 | 100% |
| reschedule | 10 | 10 | 100% |
| skip_pause | 10 | 10 | 100% |
| ticket | 10 | 10 | 100% |
| out_of_scope | 10 | 10 | 100% |
| attack | 12 | 12 | 100% |
| **all** | **62** | **62** | **100%** |

Attack group: 12/12 passed, zero data leaks.

## Failures

None.

## Iteration notes

The first draft of the rule-based responder had two bugs caught by this
eval set, not by hand-inspection: `list_my_schedules`'s trigger phrase
("my schedule") was a substring of the reschedule trigger phrase, so
"move my schedule to 9:30am" matched the listing intent before the
reschedule intent ever got checked, and never produced a proposal.
Separately, `\bscratch\b` (and `damaged`, `crash`, etc.) did not match
"scratched" (a word-boundary regex requires the literal word), so a
real damage claim fell through to the default reply instead of
escalating. A third bug, found by `reschedule-005` (a bare 'reschedule'
with no time given), was that the clarifying-question reply path
dropped the `list_my_schedules` call it had already made from its
`tool_calls` list, since that return statement forgot to pass it
through, which would have under-reported real tool usage in any
cost or audit accounting even though the call itself was harmless.
Three iterations total: the first full run surfaced the first two
bugs; the second, after fixing those, surfaced the third; the third
full run, after fixing that, is the 62/62 reported above.
