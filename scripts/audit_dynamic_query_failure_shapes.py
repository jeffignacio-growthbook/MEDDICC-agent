#!/usr/bin/env python3
"""
Evidence-based audit: what SHAPE of underlying need is actually failing
in dynamic_query, across the full available history — not a guess-based
roadmap ordering.

Reads two tables:

1. query_cost_log (migration 063) — one row per dynamic_query_loop
   invocation, EVERY exit path, regardless of outcome. This table's
   population IS "routed to dynamic_query, not a dedicated handler" by
   construction (dynamic_query_loop is only ever entered when no
   dedicated handler took the question, or a dedicated handler's answer
   was rejected and fell through). outcome is one of:
     answered_cleanly                        (excluded - not a failure)
     answered_after_resynthesis              (needed a self-correction,
                                               reported separately)
     answered_with_unverified_aggregation    (caveated)
     answered_with_unverified_date_labeling  (caveated)
     answered_with_unaddressed_ambiguity     (caveated)
     answered_with_unresolved_zero_row_suspicion (caveated)
     budget_exhausted                        (failed outright)
     other_fallback                          (failed outright)
     exception                               (failed outright)

2. learning_log (migration 021) — assessor-driven signals from the
   DEDICATED-handler correctness-assessment path: wrong_handler,
   wrong_table, missing_join, wrong_time_window, should_be_dynamic,
   data_gap, format_only, or floor_rejection (added later). Included
   because "should_be_dynamic" and "*_retry_dynamic" rows are exactly
   cases where a dedicated handler couldn't serve the real need and
   dynamic_query had to (or should have) rescued it -- the same
   underlying-need signal, reached from the other direction.

For every row that isn't a clean, uncaveated answer, sends the actual
question text to Haiku (role=evaluator, matching this repo's own
"Haiku for classification" house style) for SHAPE classification
against a candidate list, allowing the model to name a shape not on
that list rather than force-fitting. Reports frequency per shape, with
verbatim example questions and a breakdown of which evidence bucket
(failed / caveated / resynthesized / learning_log issue type) each
shape's occurrences came from.

READ-ONLY. Does not modify query_cost_log, learning_log, or anything
else. Report only -- no primitive is designed or built by this script.
"""
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "api"))

from supabase_client import select_all
from db import get_supabase
from llm_client import LLMClient

CANDIDATE_SHAPES = [
    "risk/likelihood judgment",
    "why did we win/lose",
    "forecast trustworthiness",
    "rep coaching",
    "competitive positioning",
    "data hygiene",
]

FAILED_OUTCOMES = {"exception", "budget_exhausted", "other_fallback"}
CAVEATED_OUTCOMES = {
    "answered_with_unverified_aggregation",
    "answered_with_unverified_date_labeling",
    "answered_with_unaddressed_ambiguity",
    "answered_with_unresolved_zero_row_suspicion",
}
RESYNTH_OUTCOMES = {"answered_after_resynthesis"}


def _extract_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        start = text.find("{")
        end = text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def classify_batch(client, items, batch_size=40):
    """items: list of dicts with an 'id' and 'question'. Returns
    {id: shape_string}. Sends the candidate list but explicitly allows
    a NEW shape label the model proposes itself."""
    results = {}
    candidate_text = "\n".join(f"- {s}" for s in CANDIDATE_SHAPES)
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        numbered = "\n".join(
            f"{j}. {it['question']!r}" for j, it in enumerate(batch)
        )
        prompt = f"""Classify each numbered question below by the ROUGH SHAPE of the
underlying business need it represents — not the exact phrasing. Group
similar underlying needs together even if worded very differently.

Candidate shapes (use one of these if it genuinely fits):
{candidate_text}

If a question's underlying need does NOT fit any candidate shape well,
invent a short (2-5 word) new shape label for it instead of force-fitting
— do not use "other" as a label; give the real shape a name so distinct
new needs can be told apart in the report.

Questions:
{numbered}

Respond with a JSON array, one object per question, in the SAME ORDER:
[{{"index": 0, "shape": "..."}}, {{"index": 1, "shape": "..."}}, ...]
JSON only, no explanation."""

        resp = client.complete(
            messages=[{"role": "user", "content": prompt}],
            system="Respond with valid JSON only. No markdown, no backticks, no explanation.",
            max_tokens=4000,
        )
        parsed = _extract_json(resp.text)
        if not parsed:
            print(f"[WARN] batch {i}-{i+len(batch)} failed to parse, "
                  f"raw response: {resp.text[:300]!r}", flush=True)
            for it in batch:
                results[it["id"]] = "UNCLASSIFIED (parse failure)"
            continue
        for entry in parsed:
            idx = entry.get("index")
            shape = entry.get("shape", "UNCLASSIFIED")
            if idx is None or idx >= len(batch):
                continue
            results[batch[idx]["id"]] = shape
        # Fill any indices the model skipped
        for j, it in enumerate(batch):
            if it["id"] not in results:
                results[it["id"]] = "UNCLASSIFIED (missing from response)"
    return results


def main():
    sb = get_supabase()

    print("=" * 80)
    print("PART 1: query_cost_log — full history")
    print("=" * 80)

    qcl_rows = select_all(sb, "query_cost_log",
        columns="id,question,outcome,reason_tag,primitives_fired,created_at")
    print(f"Total query_cost_log rows (all dynamic_query invocations, all time): {len(qcl_rows)}")

    outcome_counts = Counter(r.get("outcome") for r in qcl_rows)
    print("\nOutcome distribution (raw):")
    for outcome, count in outcome_counts.most_common():
        print(f"  {outcome:50s} {count}")

    non_clean = [r for r in qcl_rows if r.get("outcome") != "answered_cleanly"]
    print(f"\nNon-clean rows (failed, caveated, or resynthesized): {len(non_clean)} "
          f"of {len(qcl_rows)} ({100*len(non_clean)/max(len(qcl_rows),1):.1f}%)")

    failed = [r for r in non_clean if r.get("outcome") in FAILED_OUTCOMES]
    caveated = [r for r in non_clean if r.get("outcome") in CAVEATED_OUTCOMES]
    resynth = [r for r in non_clean if r.get("outcome") in RESYNTH_OUTCOMES]
    other_non_clean = [r for r in non_clean
                       if r.get("outcome") not in FAILED_OUTCOMES
                       and r.get("outcome") not in CAVEATED_OUTCOMES
                       and r.get("outcome") not in RESYNTH_OUTCOMES]
    print(f"  Failed outright:  {len(failed)}")
    print(f"  Caveated:         {len(caveated)}")
    print(f"  Resynthesized (self-corrected, reported separately): {len(resynth)}")
    if other_non_clean:
        print(f"  Other/unrecognized outcome value: {len(other_non_clean)} "
              f"({sorted(set(r.get('outcome') for r in other_non_clean))})")

    print("\n" + "=" * 80)
    print("PART 2: learning_log — full history")
    print("=" * 80)

    ll_rows = select_all(sb, "learning_log",
        columns="id,question,handler_used,issue_type,suggested_fix,"
                "retry_succeeded,retries_used,week_of")
    print(f"Total learning_log rows (all time): {len(ll_rows)}")

    issue_counts = Counter(r.get("issue_type") for r in ll_rows)
    print("\nissue_type distribution (raw):")
    for issue, count in issue_counts.most_common():
        print(f"  {str(issue):30s} {count}")

    retry_dynamic_rows = [r for r in ll_rows
                          if (r.get("handler_used") or "").endswith("_retry_dynamic")]
    should_be_dynamic_rows = [r for r in ll_rows if r.get("issue_type") == "should_be_dynamic"]
    floor_rejection_rows = [r for r in ll_rows if r.get("issue_type") == "floor_rejection"]
    other_ll_rows = [r for r in ll_rows
                    if r not in retry_dynamic_rows
                    and r not in should_be_dynamic_rows
                    and r not in floor_rejection_rows]
    print(f"\n  handler_used ending in _retry_dynamic (dedicated handler failed, "
          f"dynamic_query rescued it): {len(retry_dynamic_rows)}")
    print(f"  issue_type == should_be_dynamic (assessor says this SHOULD have "
          f"gone to dynamic_query): {len(should_be_dynamic_rows)}")
    print(f"  issue_type == floor_rejection (classifier confidence too low for "
          f"a dedicated handler): {len(floor_rejection_rows)}")
    print(f"  All other learning_log issue types (wrong_handler/wrong_table/"
          f"missing_join/wrong_time_window/data_gap/format_only/etc — "
          f"a DEDICATED handler's own mistake, not a dynamic_query gap): "
          f"{len(other_ll_rows)}")

    # ── Build the combined evidence set for shape classification ──
    # Only rows that represent an unmet or shaky underlying NEED go into
    # shape classification: dynamic_query failures/caveats, plus the
    # learning_log rows that are specifically about dynamic_query gaps
    # (retry_dynamic, should_be_dynamic, floor_rejection). Ordinary
    # dedicated-handler mistakes (wrong_table, missing_join, etc.) are
    # bugs in an EXISTING handler, not evidence for a NEW primitive, so
    # they're reported above but excluded from shape classification.
    evidence = []
    for r in failed:
        evidence.append({"id": f"qcl_failed_{r['id']}", "question": r.get("question") or "",
                         "bucket": f"failed:{r.get('outcome')}"})
    for r in caveated:
        evidence.append({"id": f"qcl_caveat_{r['id']}", "question": r.get("question") or "",
                         "bucket": f"caveated:{r.get('outcome')}"})
    for r in resynth:
        evidence.append({"id": f"qcl_resynth_{r['id']}", "question": r.get("question") or "",
                         "bucket": "resynthesized"})
    for r in retry_dynamic_rows:
        evidence.append({"id": f"ll_retrydyn_{r['id']}", "question": r.get("question") or "",
                         "bucket": "learning_log:retry_dynamic"})
    for r in should_be_dynamic_rows:
        evidence.append({"id": f"ll_shoulddyn_{r['id']}", "question": r.get("question") or "",
                         "bucket": "learning_log:should_be_dynamic"})
    for r in floor_rejection_rows:
        evidence.append({"id": f"ll_floor_{r['id']}", "question": r.get("question") or "",
                         "bucket": "learning_log:floor_rejection"})

    evidence = [e for e in evidence if e["question"].strip()]
    print(f"\nTotal evidence rows with non-empty question text going into "
          f"shape classification: {len(evidence)}")

    if not evidence:
        print("\nNo evidence rows to classify — nothing further to report.")
        return

    print("\n" + "=" * 80)
    print("PART 3: shape classification (Haiku, role=evaluator)")
    print("=" * 80)

    client = LLMClient.from_config(role="evaluator")
    id_to_shape = classify_batch(client, evidence)

    shape_counter = Counter(id_to_shape.values())
    shape_examples = defaultdict(list)
    shape_bucket_breakdown = defaultdict(Counter)
    id_to_evidence = {e["id"]: e for e in evidence}

    for eid, shape in id_to_shape.items():
        ev = id_to_evidence[eid]
        if len(shape_examples[shape]) < 3:
            shape_examples[shape].append(ev["question"])
        shape_bucket_breakdown[shape][ev["bucket"]] += 1

    print(f"\n{'SHAPE':40s} {'COUNT':>6s}  {'% of evidence':>13s}")
    print("-" * 80)
    total = len(evidence)
    for shape, count in shape_counter.most_common():
        pct = 100 * count / total
        print(f"{shape:40s} {count:>6d}  {pct:>12.1f}%")

    print("\n" + "=" * 80)
    print("DETAIL PER SHAPE")
    print("=" * 80)
    for shape, count in shape_counter.most_common():
        print(f"\n### {shape} ({count} occurrences)")
        print("  Evidence bucket breakdown:")
        for bucket, bcount in shape_bucket_breakdown[shape].most_common():
            print(f"    {bucket:45s} {bcount}")
        print("  Example questions:")
        for q in shape_examples[shape]:
            print(f"    - {q!r}")

    print("\n" + "=" * 80)
    print("DONE")
    print("=" * 80)


if __name__ == "__main__":
    main()
