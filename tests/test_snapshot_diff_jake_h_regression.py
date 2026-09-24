#!/usr/bin/env python3
"""
Regression: "What's changed with Jake H's deals this week?" (Slack thread
1790277383.468379, 2026-09-24 19:21 UTC) shipped
"Total pipeline value: $7.67M → $2.71M (−$4.96M)".

The real figures (deals_snapshot, deal_value, owner jake@growthbook.io):
2026-09-14 $2.91M over 52 deals, 2026-09-21 $2.71M over 53, net -$200K.
Comcast ($350K, Discovery) closed lost; Plusgrade ($50K) moved Scoping ->
Negotiating; Starz ($150K) and grüum ($0) entered at Meeting Set.

The model's first figure, $2.91M, was right. AGGREGATION_VERIFY "corrected"
it to $7.67M, and the recheck after that resynthesis passed, because both
compared against the same pool: every raw row the loop had fetched, summed
as one population. That pool was the 2026-09-21 snapshot ($2.71M), the
2026-09-14 snapshot ($2.91M) and the same 20 deals-table rows fetched twice
($1.025M each): $7.67M, which is no real population at all.

Three bugs, each fixed here:
  1. filter_table dropped snapshot_date from rows filtered on it when the
     model didn't select it (the 2026-09-14 query). The code-level diff,
     the anchor check and the verifier all tell snapshots apart by that
     field, so the loop believed 2026-09-14 was never queried
     ("ENRICHMENT_LOOKUP blocked ... not yet queried"), the deterministic
     diff never ran, and the model tried to diff two 20-row samples by
     hand: the "unfinished narration" and the duplicate call came from that.
  2. AGGREGATION_VERIFY summed across populations. It now checks a stated
     total against each population (one table, one snapshot_date, rows
     deduplicated) and accepts it if one matches; if none does and there
     is more than one, it hands the model every population's labeled total
     instead of one invented "correct" number. The recheck after a
     resynthesis uses the same populations.
  3. The completeness retry re-ran the lookup with the model's own limit
     (20), keeping 20 of 54 deals while logging "Model will proceed with
     ALL 54 deal_ids". Its limit now covers every id.

The replay runs the REAL dynamic_query_loop and the REAL filter_table over
tests/strict_supabase.StrictSupabase holding the real rows
(tests/fixtures/snapshot_diff_jake_h_2026_09_14_21.json), with the model's
side scripted from the production trace, turn for turn.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
for p in ("tests", "", "api", "scripts"):
    sys.path.insert(0, str(REPO / p))

import api.router as router  # noqa: E402
import api.tools as T  # noqa: E402
import api.table_classifier as table_classifier  # noqa: E402
import api.schema_context as schema_context  # noqa: E402
from api.aggregation_verification import extract_stated_totals_from_answer  # noqa: E402
from strict_supabase import with_data_dictionary, real_filter_table_on, StrictSupabase  # noqa: E402

try:
    from api.aggregation_verification import row_populations, verify_aggregation_by_population
except ImportError:                  # pre-fix: the tests fail, not the import
    row_populations = verify_aggregation_by_population = None

FX = json.loads((REPO / "tests" / "fixtures" / "snapshot_diff_jake_h_2026_09_14_21.json").read_text())
S14 = [r for r in FX["snapshots"] if r["snapshot_date"] == "2026-09-14"]
S21 = [r for r in FX["snapshots"] if r["snapshot_date"] == "2026-09-21"]

# ── the model's side of the production run, turn for turn ──────────────────
NINE = ["63433850647", "58798224498", "54956375177", "64885894788", "64434424673",
        "53466496122", "64524556101", "54169480766", "43491034751"]
SEP21 = {"tool": "filter_table", "params": {"table": "deals_snapshot", "columns": [
    "deal_id", "stage_id", "stage_order", "owner_email", "deal_value", "close_date",
    "snapshot_date", "pipeline_id", "forecast_category"],
    "filters": [["eq", "owner_email", "jake@growthbook.io"], ["eq", "snapshot_date", "2026-09-21"]]}}
SEP14 = {"tool": "filter_table", "params": {"table": "deals_snapshot", "columns": [   # no snapshot_date
    "deal_id", "stage_id", "stage_order", "deal_value", "close_date", "pipeline_id", "forecast_category"],
    "filters": [["eq", "owner_email", "jake@growthbook.io"], ["eq", "snapshot_date", "2026-09-14"]]}}
NAMES_A = {"tool": "filter_table", "params": {"table": "deals", "columns": [
    "deal_id", "company_name", "stage", "deal_value", "deal_status", "pipeline_id", "close_date"],
    "filters": [["in_", "deal_id", NINE]], "limit": 20}}
NAMES_B = {"tool": "filter_table", "params": {"table": "deals", "columns": [
    "deal_id", "company_name", "deal_value", "deal_status", "stage", "pipeline_id"],
    "filters": [["in_", "deal_id", NINE]], "limit": 20}}
FIRST_ANSWER = ("Jake H's deals, 2026-09-14 → 2026-09-21: Deal count 52 → 53. "
                "Total pipeline value: $2.91M → $2.71M (−$200K).")
FORCED_ANSWER = ("Jake H's deals, 2026-09-14 → 2026-09-21: Deal count 52 → 53. "
                 "Total pipeline value: $7.67M → $2.71M (−$4.96M).")
# The model's turns, in production order, by kind: the steps it took when
# asked for a step, and the two answers it wrote when asked to write one
# (its correct first answer, then the $7.67M it was made to write). The
# fixed loop asks for fewer steps; each request is served the next turn of
# its kind, so the replay follows the production run as far as the loop
# still asks the same things.
STEPS = [json.dumps(SEP21),
         "I have the current snapshot (2026-09-21) with 53 deals. I still need the prior snapshot.\n"
         + json.dumps(SEP14),
         "Now I have both snapshots. Let me look up the names.\n" + json.dumps(NAMES_A),
         "I already have both snapshots.\n" + json.dumps(NAMES_B),
         "I have both snapshots already — step 1 returned 2026-09-21 (53 rows) and the most recent "
         "tool result returned 2026-09-14 (52 rows). Both are in hand. Let me now diff them "
         "properly using ALL sample rows",
         json.dumps(SEP14)]
ANSWERS = [json.dumps({"answer": FIRST_ANSWER}), json.dumps({"answer": FORCED_ANSWER})]
# what the loop sends when it wants an answer written, not a step taken
_WRITE_REQUESTS = ("write a clean, finished Slack answer to",
                   "Stop calling tools. Using ONLY the data already gathered",
                   "Your aggregation was WRONG")


class _Resp:
    def __init__(self, text):
        self.text, self.input_tokens, self.output_tokens = text, 1000, 100


class _Client:
    def __init__(self, steps=STEPS, answers=ANSWERS):
        self.steps, self.answers, self.prompts, self.served = list(steps), list(answers), [], []

    def complete(self, messages=None, system=None, max_tokens=None, **kw):
        last = str((messages or [{}])[-1].get("content", ""))
        self.prompts.append("\n".join(str(m.get("content", "")) for m in (messages or [])))
        queue = self.answers if any(w in last for w in _WRITE_REQUESTS) else self.steps
        text = queue.pop(0) if queue else json.dumps({"answer": FIRST_ANSWER})
        self.served.append(text)
        return _Resp(text)


class _Logs(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _replay(answers=None, steps=None):
    strict = with_data_dictionary({"deals_snapshot": FX["snapshots"], "deals": FX["deals"]})
    calls = []
    real = real_filter_table_on(strict, None)

    async def filter_table(sb_passed=None, table=None, columns=None, filters=None, limit=200,
                           order_by=None, *, sb=None):
        calls.append({"table": table, "filters": filters, "limit": limit})
        return await real(table=table, columns=columns, filters=filters, limit=limit, order_by=order_by)

    saved = (T.filter_table, table_classifier.classify_relevant_tables, schema_context.get_schema_context)
    T.filter_table = filter_table
    table_classifier.classify_relevant_tables = lambda q, c: ["deals", "deals_snapshot"]
    schema_context.get_schema_context = (lambda sb, tables_with_descriptions=None, lightweight=False:
                                         "TABLE: deals_snapshot\nTABLE: deals\n")
    logs = _Logs()
    logging.getLogger().addHandler(logs)
    logging.getLogger().setLevel(logging.INFO)
    client = _Client(steps=steps or STEPS, answers=answers or ANSWERS)
    try:
        result = asyncio.run(router.dynamic_query_loop(
            question="What's changed with Jake H's deals this week?", history=[],
            params={"time_window": {"label": "this week", "start": "2026-09-17", "end": "2026-09-24"},
                    "owner_email": "jake@growthbook.io"},
            sb=strict, client=client))
    finally:
        T.filter_table, table_classifier.classify_relevant_tables, schema_context.get_schema_context = saved
        logging.getLogger().removeHandler(logs)
    return result, client, calls, logs.lines


# ── the fixture is the real data ────────────────────────────────────────────

def test_fixture_is_the_real_diff():
    assert (len(S14), sum(r["deal_value"] for r in S14)) == (52, 2_910_000)
    assert (len(S21), sum(r["deal_value"] for r in S21)) == (53, 2_710_000)
    a, b = {r["deal_id"]: r for r in S14}, {r["deal_id"]: r for r in S21}
    name = {d["deal_id"]: d["company_name"] for d in FX["deals"]}
    assert [name[i] for i in sorted(set(a) - set(b))] == ["Comcast"]
    assert sorted(name[i] for i in set(b) - set(a)) == ["Starz", "grüum"]
    assert [(name[i], a[i]["stage_id"], b[i]["stage_id"]) for i in sorted(set(a) & set(b))
            if a[i]["stage_id"] != b[i]["stage_id"]] == [("Plusgrade", "qualifiedtobuy", "24682892")]
    assert sum(d["deal_value"] for d in FX["deals"][:20]) == 1_025_000
    print("✓ fixture = the real rows: $2.91M (52) → $2.71M (53); Comcast out, Starz and grüum in, "
          "Plusgrade Scoping → Negotiating; the 20 rows production's truncated lookup got sum to $1.025M")


# ── bug 1: a snapshot row says which snapshot it is ────────────────────────

def test_filter_table_returns_the_snapshot_date_it_filtered_on():
    T._VALID_COLUMNS.clear()
    sb = with_data_dictionary({"deals_snapshot": FX["snapshots"]})
    r = asyncio.run(T.filter_table(sb, "deals_snapshot", columns=SEP14["params"]["columns"],
                                   filters=SEP14["params"]["filters"]))
    assert len(r["rows"]) == 52 and {row.get("snapshot_date") for row in r["rows"]} == {"2026-09-14"}, \
        r["rows"][:1]
    r = asyncio.run(T.filter_table(sb, "deals_snapshot", columns=["deal_id"],
                                   filters=[["eq", "owner_email", "jake@growthbook.io"]]))
    assert "snapshot_date" not in r["rows"][0], "only added when the query filters on it"
    print("✓ filter_table: rows filtered on snapshot_date carry it even when it wasn't selected")


# ── bug 2: a stated total is checked per population ────────────────────────

def _trace_populations():
    return {"deals_snapshot on 2026-09-21": S21, "deals_snapshot on 2026-09-14": S14,
            "deals": FX["deals"][:20]}


# ── the production run, replayed ────────────────────────────────────────────


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} tests passed")
