# Ex9 — Reflection

## Q1 — Planner handoff decision

### Your answer

In session sess_9a36e05db507 (ex7-handoff-bridge), the planner produced
exactly one subgoal — sg_1 "find venue near haymarket for 12" — with
`assigned_half: "loop"` (tk_70f46ffb/raw_output.json:8). I checked all
three of my Ex7 sessions (sess_9a36e05db507, sess_c72098e4c21c,
sess_c9935cc8383f); none of them produced a subgoal with
`assigned_half: "structured"`. The planner always assigned to loop.

The actual decision to hand off was made by the executor LLM inside
the loop half, recorded as a `handoff_to_structured` tool call at
trace.jsonl:5. Its reason field reads verbatim:

> "loop half identified a candidate venue; passing to structured half
>  for confirmation under policy rules"

The data payload was `{"action": "confirm_booking", "venue_id":
"Haymarket Tap", "party_size": "12", "deposit": "£0"}`. The
structured half then rejected with reason `party_too_large`
(trace.jsonl:7) — proving the executor's intuition that policy
checking belonged in structured Python was correct.

The signal driving the decision was the prose phrase "for confirmation
under policy rules" in the executor's own reasoning. It recognised
that party-size limits, blackout dates, and deposit thresholds are
deterministic checks better evaluated in pub_policy.py than re-derived
by the LLM each turn.

The broader lesson from this trace: in a DefaultPlanner configuration
the handoff signal is not a planner field — it is an executor tool
call. If pub_policy enforcement migrated from structured Python into
an LLM prompt inside the loop half, the rejection "party_too_large"
would still surface, but as model output text rather than a
`session.state_changed` event, breaking the bridge's round counter.
Putting deterministic rules in Python and discoverable rejection
reasons in a state-machine field is how the prose-level "decision"
gets disambiguated.

### Citation

- sessions/examples/ex7-handoff-bridge/sess_9a36e05db507/logs/tickets/tk_70f46ffb/raw_output.json:8
- sessions/examples/ex7-handoff-bridge/sess_9a36e05db507/logs/trace.jsonl:5
- sessions/examples/ex7-handoff-bridge/sess_9a36e05db507/logs/trace.jsonl:7

---

## Q2 — Dataflow integrity catch

### Your answer

In session sess_d36eb7103465 (ex5-edinburgh-research), a dataflow
integrity check would have caught a fabrication that reads as plausible
to a human skim. The task fixed party_size=6, date=2026-04-25, area=
Haymarket, and required the tool sequence venue_search → get_weather →
calculate_cost → generate_flyer.

What the executor actually did (trace.jsonl): three venue_search calls,
all with party=10 in Edinburgh (lines 3-5); a calculate_cost on
`royal_oak, party=10, sit_down_meal, 3h` returning total £1612, deposit
£483 (line 6); then generate_flyer with `total_gbp: 385,
deposit_required_gbp: 75, party_size: 12, date: "2023-11-24",
condition: "Clear", temperature_c: 8` (line 7). get_weather was never
called. The rendered flyer.html shows £385 total / £75 deposit / 8°C /
Clear — every number looks reasonable; nothing screams "wrong" to a
reviewer.

The integrity check would lift every numeric and string field from
workspace/flyer.html and require each to be either a literal task
constant or a value present in `_TOOL_CALL_LOG`. It would return:

```
ok=False
unverified_facts=['£385','£75','Clear','8°C','2023-11-24','party=12','The Royal Edinburgh']
```

Per-field reasoning:
- £385 / £75: calculate_cost returned 1612/483 — the flyer values
  appear in no tool output → fabricated.
- "Clear" / 8°C: no get_weather call exists in the trace → fabricated.
- 2023-11-24: the task fixed 2026-04-25; no tool returned this date.
- party_size 12: every tool call used 10, the task said 6 — 12 appears
  nowhere upstream → fabricated.

The check survives the eye-test because it does not ask "does this
look reasonable" — it compares against ground truth recorded by the
tool dispatcher. To verify the same scenario on a future run, plant a
deliberately-weird upstream value (e.g. calculate_cost forced to
return £9999) and confirm the artifact's number either matches £9999
or is flagged.

### Citation

- sessions/examples/ex5-edinburgh-research/sess_d36eb7103465/logs/trace.jsonl:6
- sessions/examples/ex5-edinburgh-research/sess_d36eb7103465/logs/trace.jsonl:7
- sessions/examples/ex5-edinburgh-research/sess_d36eb7103465/workspace/flyer.html

---

## Q3 — First production failure & primitive that surfaces it

### Your answer

**Failure mode:** concurrent confirmation race on the same time-slot.
**Primitive:** IPC atomic rename.

On Day 1 with real pub managers, two booking sessions land ten seconds
apart, each ending in `handoff_to_structured` with
`action: "confirm_booking"` for the same venue/slot — e.g. The Royal
Oak, Friday 19:30. The structured half reads bookings.json, sees the
slot free, appends booking A, writes via `tmp_file → os.rename(tmp,
dest)`. Session B (started 200ms later) read bookings.json before A's
rename landed, also sees the slot free, appends booking B, renames.
Result: the file now holds A or B depending on rename ordering — the
loser is silently dropped, and both customers received a confirmation
reply.

The Ex7 traces make this concrete. In sess_9a36e05db507, both bridge
rounds complete inside ~100ms (trace.jsonl timestamps
23:31:47.564 → 23:31:47.644) — well inside the window where two real
customers could hit confirm_booking concurrently. The fact that the
structured half's response is synchronous within a single session
hides the cross-session race.

The primitive that surfaces it is **IPC atomic rename**. Sovereign-agent
writes structured-half state via tmp + os.rename. On a local
ext4/APFS volume this is atomic per inode, so a concurrent writer's
file overwrites cleanly — failure manifests as a missing row in the
booking-count audit (visible). On a network filesystem (NFS, EFS,
S3-fuse) the rename is not guaranteed atomic; a partially-written
bookings.json fails the next ticket's JSON parse, and the ticket
state machine transitions that ticket to `error` rather than `complete`
(also visible). Either deployment surface produces an observable
signal — the primitive does not silently mask the race, it converts
it into either an audit discrepancy or a ticket-error event.

Mitigation: per-(venue, slot) file locking inside the structured half,
with the ticket state machine refusing the `complete` transition until
the lock is released and the rename is observed by a re-read.

### Citation

- sessions/examples/ex7-handoff-bridge/sess_9a36e05db507/logs/trace.jsonl
  (timestamps 23:31:47.564 — 23:31:47.644 show <100ms round latency)
- sessions/examples/ex7-handoff-bridge/sess_c9935cc8383f/logs/trace.jsonl
  (same pattern, replicating the timing observation)
