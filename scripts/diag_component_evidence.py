#!/usr/bin/env python3
"""
Read-only diagnostic: is per-component EVIDENCE populated in analyses for the
deals Ryan asked about? Answers step 1 of the evidence-wiring fix — if evidence
exists, the gap is the handler (doesn't select component_details); if it's
null/missing, the gap is the nightly scorer.

Prints, per company (Zalando / Natera / Ecco), the latest analysis row's
component_details: for each MEDDICC component, the score and whether an evidence
string is present (and its length). Champion + Economic Buyer are called out
because those are the reds driving "most urgent".

No writes. Needs SUPABASE_URL + SUPABASE_SERVICE_KEY.
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

COMPANIES = ["Zalando", "Natera", "Ecco"]
COMPONENTS = ["metrics", "economic_buyer", "decision_criteria",
              "decision_process", "pain", "champion", "competition"]
_SCORE_COL = {c: f"{c}_score" for c in COMPONENTS}


def main():
    import json
    from api.db import get_supabase
    from supabase_client import select_all
    sb = get_supabase()

    print("=" * 78)
    print("COMPONENT EVIDENCE DIAGNOSTIC — analyses.component_details")
    print("=" * 78)

    for name in COMPANIES:
        deals = select_all(sb, "deals", columns="deal_id,company_name",
                           filters=[("ilike", "company_name", f"%{name}%")])
        if not deals:
            print(f"\n[{name}] no deal matched company_name ilike %{name}%")
            continue
        deal_ids = [d["deal_id"] for d in deals]
        rows = select_all(sb, "analyses",
            columns="deal_id,company_name,overall_score,passed,analyzed_at,"
                    "component_details," + ",".join(_SCORE_COL.values()),
            filters=[("in_", "deal_id", deal_ids)])
        # latest per deal
        latest = {}
        for a in rows:
            did = a.get("deal_id")
            if (did not in latest or
                    str(a.get("analyzed_at") or "") > str(latest[did].get("analyzed_at") or "")):
                latest[did] = a

        for d in deals:
            a = latest.get(d["deal_id"])
            print(f"\n[{name}] {d['company_name']} (deal {d['deal_id']})")
            if not a:
                print("   no analysis row")
                continue
            print(f"   overall={a.get('overall_score')} passed={a.get('passed')} "
                  f"analyzed_at={a.get('analyzed_at')}")
            cd = a.get("component_details")
            if isinstance(cd, str):
                try:
                    cd = json.loads(cd)
                except Exception:
                    cd = None
            if not cd:
                print("   component_details: NULL / empty  <-- evidence NOT stored "
                      "(nightly scorer gap)")
                continue
            for comp in COMPONENTS:
                cell = cd.get(comp) or {}
                score = cell.get("score", a.get(_SCORE_COL[comp]))
                ev = (cell.get("evidence") or "").strip()
                flag = "  <<<" if comp in ("champion", "economic_buyer") else ""
                if ev:
                    print(f"   {comp:16} score={score} evidence[{len(ev)}]: "
                          f"{ev[:90]}{'…' if len(ev) > 90 else ''}{flag}")
                else:
                    print(f"   {comp:16} score={score} evidence: (none){flag}")
    print("\n" + "=" * 78)
    print("If evidence strings are present above -> handler fix (select "
          "component_details). If NULL/none -> nightly scorer gap.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
