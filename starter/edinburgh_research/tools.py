"""Ex5 tools. Four tools the agent uses to research an Edinburgh booking.

Each tool:
  1. Reads its fixture from sample_data/ (DO NOT modify the fixtures).
  2. Logs its arguments and output into _TOOL_CALL_LOG (see integrity.py).
  3. Returns a ToolResult with success=True/False, output=dict, summary=str.

The grader checks for:
  * Correct parallel_safe flags (reads True, generate_flyer False).
  * Every tool's results appear in _TOOL_CALL_LOG.
  * Tools fail gracefully on missing fixtures or bad inputs (ToolError,
    not RuntimeError).
"""

from __future__ import annotations

import html
import inspect
import json
from pathlib import Path

from sovereign_agent.errors import ToolError
from sovereign_agent.session.directory import Session
from sovereign_agent.tools.registry import ToolRegistry, ToolResult, _RegisteredTool

from starter.edinburgh_research.integrity import _TOOL_CALL_LOG, record_tool_call

_VENUE_SEARCH_MAX_CALLS = 3
_AREA_NEEDLE_STOPWORDS = {"edinburgh", "near", "in", "the", "around", "by", "city"}


def _normalise_area_needle(near: str) -> str:
    tokens = [t for t in (near or "").lower().split() if t not in _AREA_NEEDLE_STOPWORDS]
    return " ".join(tokens).strip()


def _area_matches(needle: str, area: str) -> bool:
    if not needle:
        return True
    n, a = needle.lower(), area.lower()
    if n in a or a in n:
        return True
    return bool(set(n.split()) & set(a.split()))


def _venues_already_found() -> list[dict]:
    """Scan _TOOL_CALL_LOG for venues returned by past venue_search calls.

    Defensive: a log entry's output may be the spiral-guard sentinel
    ({"error": "too_many_searches", ...}) rather than a results dict.
    """
    seen_ids: set[str] = set()
    accumulated: list[dict] = []
    for r in _TOOL_CALL_LOG:
        if r.tool_name != "venue_search":
            continue
        results = r.output.get("results") if isinstance(r.output, dict) else None
        if not isinstance(results, list):
            continue
        for v in results:
            if not isinstance(v, dict):
                continue
            vid = v.get("id")
            if vid and vid not in seen_ids:
                seen_ids.add(vid)
                accumulated.append(v)
    return accumulated


_SAMPLE_DATA = Path(__file__).parent / "sample_data"


def _load_fixture(name: str) -> object:
    path = _SAMPLE_DATA / name
    if not path.exists():
        raise ToolError(
            code="SA_TOOL_DEPENDENCY_MISSING",
            message=f"fixture {name!r} not found at {path}",
        )
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# TODO 1 — venue_search
# ---------------------------------------------------------------------------
def venue_search(near: str, party_size: int, budget_max_gbp: int = 1000) -> ToolResult:
    """Search for Edinburgh venues near <near> that can seat the party.

    Reads sample_data/venues.json. Filters by:
      * open_now == True
      * area contains <near> (case-insensitive substring match)
      * seats_available_evening >= party_size
      * hire_fee_gbp + min_spend_gbp <= budget_max_gbp

    Returns a ToolResult with:
      output: {"near": ..., "party_size": ..., "results": [<venue dicts>], "count": int}
      summary: "venue_search(<near>, party=<N>): <count> result(s)"

    MUST call record_tool_call(...) before returning so the integrity
    check can see what data was produced.
    """
    arguments = {"near": near, "party_size": party_size, "budget_max_gbp": budget_max_gbp}

    prior_calls = sum(1 for r in _TOOL_CALL_LOG if r.tool_name == "venue_search")
    if prior_calls >= _VENUE_SEARCH_MAX_CALLS:
        accumulated = _venues_already_found()
        if accumulated:
            seen_ids = [v["id"] for v in accumulated]
            fallback_id = seen_ids[0]
            suggestion = (
                f"You already found {len(seen_ids)} venue(s): "
                f"{', '.join(seen_ids)}. Pick one (suggest '{fallback_id}') "
                "and proceed."
            )
        else:
            fallback_id = "haymarket_tap"
            suggestion = (
                "No matches in prior searches. Use venue_id='haymarket_tap' "
                "as the safe default and proceed."
            )

        output = {
            "error": "too_many_searches",
            "count": prior_calls,
            "limit": _VENUE_SEARCH_MAX_CALLS,
            "fallback_venue_id": fallback_id,
            "results": accumulated,
            "seen_venue_ids": [v["id"] for v in accumulated],
        }
        summary = (
            f"STOP calling venue_search ({prior_calls} prior calls). "
            f"{suggestion} Do NOT hand off to the structured half. Call "
            "get_weather, calculate_cost, and generate_flyer next."
        )
        record_tool_call("venue_search", arguments, output)
        return ToolResult(success=False, output=output, summary=summary)

    venues = _load_fixture("venues.json")

    needle = _normalise_area_needle(near)
    matches: list[dict] = []
    for v in venues:
        if not v.get("open_now"):
            continue
        if not _area_matches(needle, v.get("area", "")):
            continue
        if v.get("seats_available_evening", 0) < party_size:
            continue
        if v.get("hire_fee_gbp", 0) + v.get("min_spend_gbp", 0) > budget_max_gbp:
            continue
        matches.append(v)

    output = {
        "near": near,
        "party_size": party_size,
        "budget_max_gbp": budget_max_gbp,
        "results": matches,
        "count": len(matches),
    }
    summary = f"venue_search({near}, party={party_size}): {len(matches)} result(s)"
    record_tool_call("venue_search", arguments, output)
    return ToolResult(success=True, output=output, summary=summary)


# ---------------------------------------------------------------------------
# TODO 2 — get_weather
# ---------------------------------------------------------------------------
def get_weather(city: str, date: str) -> ToolResult:
    """Look up the scripted weather for <city> on <date> (YYYY-MM-DD).

    Reads sample_data/weather.json. Returns:
      output: {"city": str, "date": str, "condition": str, "temperature_c": int, ...}
      summary: "get_weather(<city>, <date>): <condition>, <temp>C"

    If the city or date is not in the fixture, return success=False with
    a clear ToolError (SA_TOOL_INVALID_INPUT). Do NOT raise.

    MUST call record_tool_call(...) before returning.
    """
    arguments = {"city": city, "date": date}
    weather = _load_fixture("weather.json")

    city_key = (city or "").strip().lower()
    city_data = weather.get(city_key)
    if city_data is None:
        err = ToolError(
            code="SA_TOOL_INVALID_INPUT",
            message=f"no weather data for city {city!r}",
        )
        record_tool_call("get_weather", arguments, {"error": err.code})
        return ToolResult(
            success=False,
            output={"city": city, "date": date},
            summary=f"get_weather({city}, {date}): city not found",
            error=err,
        )

    entry = city_data.get(date)
    if entry is None:
        err = ToolError(
            code="SA_TOOL_INVALID_INPUT",
            message=f"no weather data for {city!r} on {date!r}",
        )
        record_tool_call("get_weather", arguments, {"error": err.code})
        return ToolResult(
            success=False,
            output={"city": city, "date": date},
            summary=f"get_weather({city}, {date}): date not found",
            error=err,
        )

    output = {
        "city": city,
        "date": date,
        "condition": entry["condition"],
        "temperature_c": entry["temperature_c"],
        "precip_mm": entry.get("precip_mm"),
        "wind_kph": entry.get("wind_kph"),
    }
    summary = f"get_weather({city}, {date}): {entry['condition']}, {entry['temperature_c']}C"
    record_tool_call("get_weather", arguments, output)
    return ToolResult(success=True, output=output, summary=summary)


# ---------------------------------------------------------------------------
# TODO 3 — calculate_cost
# ---------------------------------------------------------------------------
def calculate_cost(
    venue_id: str,
    party_size: int,
    duration_hours: int,
    catering_tier: str = "bar_snacks",
) -> ToolResult:
    """Compute the total cost for a booking.

    Formula:
      base_per_head = base_rates_gbp_per_head[catering_tier]
      venue_mult    = venue_modifiers[venue_id]
      subtotal      = base_per_head * venue_mult * party_size * max(1, duration_hours)
      service       = subtotal * service_charge_percent / 100
      total         = subtotal + service + <venue's hire_fee_gbp + min_spend_gbp>
      deposit_rule  = per deposit_policy thresholds

    Returns:
      output: {
        "venue_id": str,
        "party_size": int,
        "duration_hours": int,
        "catering_tier": str,
        "subtotal_gbp": int,
        "service_gbp": int,
        "total_gbp": int,
        "deposit_required_gbp": int,
      }
      summary: "calculate_cost(<venue>, <party>): total £<N>, deposit £<M>"

    MUST call record_tool_call(...) before returning.
    """
    arguments = {
        "venue_id": venue_id,
        "party_size": party_size,
        "duration_hours": duration_hours,
        "catering_tier": catering_tier,
    }
    catering = _load_fixture("catering.json")
    venues = _load_fixture("venues.json")

    base_rates = catering["base_rates_gbp_per_head"]
    if catering_tier not in base_rates:
        err = ToolError(
            code="SA_TOOL_INVALID_INPUT",
            message=f"unknown catering_tier {catering_tier!r}",
        )
        record_tool_call("calculate_cost", arguments, {"error": err.code})
        return ToolResult(
            success=False,
            output=arguments,
            summary=f"calculate_cost: unknown tier {catering_tier!r}",
            error=err,
        )

    venue_mods = catering["venue_modifiers"]
    if venue_id not in venue_mods:
        err = ToolError(
            code="SA_TOOL_INVALID_INPUT",
            message=f"unknown venue_id {venue_id!r}",
        )
        record_tool_call("calculate_cost", arguments, {"error": err.code})
        return ToolResult(
            success=False,
            output=arguments,
            summary=f"calculate_cost: unknown venue {venue_id!r}",
            error=err,
        )

    venue_row = next((v for v in venues if v["id"] == venue_id), None)
    if venue_row is None:
        err = ToolError(
            code="SA_TOOL_INVALID_INPUT",
            message=f"venue {venue_id!r} not in venues fixture",
        )
        record_tool_call("calculate_cost", arguments, {"error": err.code})
        return ToolResult(
            success=False,
            output=arguments,
            summary=f"calculate_cost: venue {venue_id!r} not found",
            error=err,
        )

    base_per_head = base_rates[catering_tier]
    venue_mult = venue_mods[venue_id]
    hours = max(1, duration_hours)
    subtotal = base_per_head * venue_mult * party_size * hours
    service = subtotal * catering["service_charge_percent"] / 100
    fixed = venue_row.get("hire_fee_gbp", 0) + venue_row.get("min_spend_gbp", 0)
    total = subtotal + service + fixed

    if total < 300:
        deposit = 0
    elif total <= 1000:
        deposit = int(round(total * 0.20))
    else:
        deposit = int(round(total * 0.30))

    output = {
        "venue_id": venue_id,
        "party_size": party_size,
        "duration_hours": duration_hours,
        "catering_tier": catering_tier,
        "subtotal_gbp": int(round(subtotal)),
        "service_gbp": int(round(service)),
        "total_gbp": int(round(total)),
        "deposit_required_gbp": deposit,
    }
    summary = (
        f"calculate_cost({venue_id}, {party_size}): "
        f"total £{output['total_gbp']}, deposit £{deposit}"
    )
    record_tool_call("calculate_cost", arguments, output)
    return ToolResult(success=True, output=output, summary=summary)


# ---------------------------------------------------------------------------
# TODO 4 — generate_flyer
# ---------------------------------------------------------------------------
def generate_flyer(session: Session, event_details: dict) -> ToolResult:
    """Produce an HTML flyer and write it to workspace/flyer.html.

    event_details is expected to contain at least:
      venue_name, venue_address, date, time, party_size, condition,
      temperature_c, total_gbp, deposit_required_gbp

    Write a self-contained HTML flyer (inline CSS, no external assets). Tag every key fact with data-testid="<n>" so the integrity check can parse it.

    Write a formatted HTML flyer with an H1 title, the event
    facts, a weather summary, and the cost breakdown.

    Returns:
      output: {"path": "workspace/flyer.html", "bytes_written": int}
      summary: "generate_flyer: wrote <path> (<N> chars)"

    MUST call record_tool_call(...) before returning — the integrity
    check compares the flyer's contents against earlier tool outputs.

    IMPORTANT: this tool MUST be registered with parallel_safe=False
    because it writes a file.
    """
    arguments = {"event_details": dict(event_details)}

    def _esc(value: object) -> str:
        return html.escape(str(value), quote=True)

    venue_name = _esc(event_details.get("venue_name", "TBD"))
    venue_address = _esc(event_details.get("venue_address", ""))
    date = _esc(event_details.get("date", ""))
    time = _esc(event_details.get("time", ""))
    party_size = _esc(event_details.get("party_size", ""))
    condition = _esc(event_details.get("condition", ""))
    temperature_c = _esc(event_details.get("temperature_c", ""))
    total_gbp = _esc(event_details.get("total_gbp", ""))
    deposit_gbp = _esc(event_details.get("deposit_required_gbp", ""))

    flyer_html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Edinburgh Booking — {venue_name}</title>
<style>
  body {{ font-family: Georgia, serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; color: #222; }}
  h1 {{ font-size: 2rem; margin-bottom: 0.25rem; }}
  .address {{ color: #555; margin-top: 0; }}
  dl {{ display: grid; grid-template-columns: 12rem 1fr; gap: 0.4rem 1rem; }}
  dt {{ font-weight: bold; }}
  section {{ margin-top: 1.5rem; }}
</style>
</head>
<body>
  <h1 data-testid="venue_name">{venue_name}</h1>
  <p class="address" data-testid="venue_address">{venue_address}</p>

  <section>
    <h2>Event</h2>
    <dl>
      <dt>Date</dt><dd data-testid="date">{date}</dd>
      <dt>Time</dt><dd data-testid="time">{time}</dd>
      <dt>Party size</dt><dd data-testid="party_size">{party_size}</dd>
    </dl>
  </section>

  <section>
    <h2>Weather</h2>
    <dl>
      <dt>Condition</dt><dd data-testid="condition">{condition}</dd>
      <dt>Temperature</dt><dd data-testid="temperature_c">{temperature_c}°C</dd>
    </dl>
  </section>

  <section>
    <h2>Cost</h2>
    <dl>
      <dt>Total</dt><dd data-testid="total">£{total_gbp}</dd>
      <dt>Deposit</dt><dd data-testid="deposit">£{deposit_gbp}</dd>
    </dl>
  </section>
</body>
</html>
"""

    flyer_path = session.workspace_dir / "flyer.html"
    flyer_path.parent.mkdir(parents=True, exist_ok=True)
    flyer_path.write_text(flyer_html, encoding="utf-8")
    bytes_written = len(flyer_html.encode("utf-8"))

    output = {
        "path": "workspace/flyer.html",
        "bytes_written": bytes_written,
    }
    summary = f"generate_flyer: wrote workspace/flyer.html ({len(flyer_html)} chars)"
    record_tool_call("generate_flyer", arguments, output)
    return ToolResult(success=True, output=output, summary=summary)


# ---------------------------------------------------------------------------
# Registry builder — DO NOT MODIFY the name, signature, or registration calls.
# The grader imports and calls this to pick up your tools.
# ---------------------------------------------------------------------------
def build_tool_registry(session: Session) -> ToolRegistry:
    """Build a session-scoped tool registry with all four Ex5 tools plus
    the sovereign-agent builtins (read_file, write_file, list_files,
    handoff_to_structured, complete_task).

    DO NOT change the tool names — the tests and grader call them by name.
    """
    from sovereign_agent.tools.builtin import make_builtin_registry

    reg = make_builtin_registry(session)

    # venue_search
    reg.register(
        _RegisteredTool(
            name="venue_search",
            description=inspect.getdoc(venue_search)
            or "Search Edinburgh venues by area, party size, and max budget.",
            fn=venue_search,
            parameters_schema={
                "type": "object",
                "properties": {
                    "near": {"type": "string"},
                    "party_size": {"type": "integer"},
                    "budget_max_gbp": {"type": "integer", "default": 1000},
                },
                "required": ["near", "party_size"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,  # read-only
            examples=[
                {
                    "input": {"near": "Haymarket", "party_size": 6, "budget_max_gbp": 800},
                    "output": {"count": 1, "results": [{"id": "haymarket_tap"}]},
                }
            ],
        )
    )

    # get_weather
    reg.register(
        _RegisteredTool(
            name="get_weather",
            description=inspect.getdoc(get_weather)
            or "Get scripted weather for a city on a YYYY-MM-DD date.",
            fn=get_weather,
            parameters_schema={
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": ["city", "date"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,  # read-only
            examples=[
                {
                    "input": {"city": "Edinburgh", "date": "2026-04-25"},
                    "output": {"condition": "cloudy", "temperature_c": 12},
                }
            ],
        )
    )

    # calculate_cost
    reg.register(
        _RegisteredTool(
            name="calculate_cost",
            description=inspect.getdoc(calculate_cost)
            or "Compute total cost and deposit for a booking.",
            fn=calculate_cost,
            parameters_schema={
                "type": "object",
                "properties": {
                    "venue_id": {"type": "string"},
                    "party_size": {"type": "integer"},
                    "duration_hours": {"type": "integer"},
                    "catering_tier": {
                        "type": "string",
                        "enum": ["drinks_only", "bar_snacks", "sit_down_meal", "three_course_meal"],
                        "default": "bar_snacks",
                    },
                },
                "required": ["venue_id", "party_size", "duration_hours"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,  # pure compute, no shared state
            examples=[
                {
                    "input": {
                        "venue_id": "haymarket_tap",
                        "party_size": 6,
                        "duration_hours": 3,
                    },
                    "output": {"total_gbp": 540, "deposit_required_gbp": 0},
                }
            ],
        )
    )

    # generate_flyer — parallel_safe=False because it writes a file
    def _flyer_adapter(event_details: dict) -> ToolResult:
        return generate_flyer(session, event_details)

    reg.register(
        _RegisteredTool(
            name="generate_flyer",
            description=inspect.getdoc(generate_flyer)
            or "Write an HTML flyer for the event to workspace/flyer.html.",
            fn=_flyer_adapter,
            parameters_schema={
                "type": "object",
                "properties": {"event_details": {"type": "object"}},
                "required": ["event_details"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=False,  # writes a file — MUST be False
            examples=[
                {
                    "input": {
                        "event_details": {
                            "venue_name": "Haymarket Tap",
                            "date": "2026-04-25",
                            "party_size": 6,
                        }
                    },
                    "output": {"path": "workspace/flyer.html"},
                }
            ],
        )
    )

    return reg


__all__ = [
    "build_tool_registry",
    "venue_search",
    "get_weather",
    "calculate_cost",
    "generate_flyer",
]
