# Session sess_a285ed41bd6c

**Scenario:** edinburgh-research
**Created:** 2026-05-23T19:38:48.750928+00:00

## Your task

(The loop half reads this file on every turn. The initial task description
has been written below by the orchestrator when the session was created.
Additional per-session instructions — constraints, identity, voice — can
be added by the scenario author.)

## Task description

Research an Edinburgh pub and produce an HTML event flyer.

Context (FIXED — do not modify):
  - party size: 6
  - date: 2026-04-25 (a Saturday)
  - time: 19:30
  - area: Haymarket

REQUIRED tool sequence (call EXACTLY ONCE EACH, in this order):
  1. venue_search(near='Haymarket', party_size=6, budget_max_gbp=800)
  2. get_weather(city='edinburgh', date='2026-04-25')
  3. calculate_cost(venue_id='haymarket_tap', party_size=6,
                    duration_hours=3, catering_tier='bar_snacks')
  4. generate_flyer(event_details={...})
  5. complete_task(result={'flyer': 'workspace/flyer.html', ...})

HARD RULES (violating these fails the task):
  - Call venue_search EXACTLY ONCE with the args above. Do NOT
    retry with different params if it returns 0 results — use
    venue_id='haymarket_tap' as the fallback and proceed.
  - Do NOT change party_size from 6. Do NOT change the area
    from 'Haymarket'. Do NOT prepend 'Edinburgh' to the area.
  - Do NOT call handoff_to_structured. This task completes
    entirely in the loop half. There is no structured half
    for this scenario.
  - generate_flyer MUST be called before complete_task. The
    scenario is graded by the existence of workspace/flyer.html,
    not by your final text response.
  - Pass concrete numbers to generate_flyer that came from the
    earlier tool calls (total_gbp, deposit_required_gbp,
    condition, temperature_c). Do not invent values.


## Constraints

- Be honest when you do not know something.
- Prefer reading memory over guessing.
- When the task is ambiguous, ask for clarification rather than inventing an answer.
