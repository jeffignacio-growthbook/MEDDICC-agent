"""
Test Hypothesis 1: Were the 4 closed-won deals with MEDDICC scores analyzed
BEFORE or AFTER they closed?

If analyzed_at > close_date for most/all, the reverse correlation (Champion/EB
drop in won deals) is explained by post-close analysis, not framework failure.
"""
import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load .env file
load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from supabase_client import create_resilient_supabase_client

sb = create_resilient_supabase_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_KEY"]
)

# Get closed-won deals with MEDDICC scores
won_deals_query = sb.table("deals").select(
    "deal_id, company_name, close_date, stage"
).ilike("stage", "%closedwon%").execute()

won_deal_ids = [str(d["deal_id"]) for d in won_deals_query.data]

print(f"Found {len(won_deal_ids)} closed-won deals total")

# Get MEDDICC analyses for those deals
analyses = sb.table("analyses").select(
    "deal_id, analyzed_at, overall_score, "
    "champion_score, economic_buyer_score, decision_criteria_score, "
    "decision_process_score, pain_score, competition_score, metrics_score"
).in_("deal_id", won_deal_ids).order("deal_id, analyzed_at", desc=True).execute()

print(f"Found {len(analyses.data)} MEDDICC analyses for closed-won deals")
print()

# For each won deal with scores, compare analyzed_at vs close_date
results = []
for analysis in analyses.data:
    deal_id = analysis["deal_id"]
    # Find the deal record
    deal = next((d for d in won_deals_query.data if str(d["deal_id"]) == str(deal_id)), None)
    if not deal:
        continue

    close_date = deal["close_date"]
    analyzed_at = analysis["analyzed_at"]

    # Parse timestamps (handle both date-only and datetime strings)
    if "T" in close_date:
        close_dt = datetime.fromisoformat(close_date.replace("Z", "+00:00"))
    else:
        # Date-only string, convert to datetime at midnight UTC
        close_dt = datetime.fromisoformat(close_date + "T00:00:00+00:00")

    analyzed_dt = datetime.fromisoformat(analyzed_at.replace("Z", "+00:00"))

    # Calculate difference
    diff_days = (analyzed_dt - close_dt).days
    timing = "AFTER" if diff_days > 0 else ("BEFORE" if diff_days < 0 else "SAME DAY")

    results.append({
        "deal_id": deal_id,
        "company_name": deal.get("company_name"),
        "close_date": close_date[:10],
        "analyzed_at": analyzed_at[:10],
        "diff_days": diff_days,
        "timing": timing,
        "champion_score": analysis.get("champion_score"),
        "economic_buyer_score": analysis.get("economic_buyer_score"),
        "overall_score": analysis.get("overall_score")
    })

print("=" * 80)
print("MEDDICC TIMING ANALYSIS: Closed-Won Deals")
print("=" * 80)
print()

for r in results:
    print(f"Deal: {r['company_name']} ({r['deal_id']})")
    print(f"  Close Date:   {r['close_date']}")
    print(f"  Analyzed At:  {r['analyzed_at']}")
    print(f"  Timing:       {r['timing']} ({r['diff_days']:+d} days)")
    print(f"  Champion:     {r['champion_score']}/10")
    print(f"  Econ Buyer:   {r['economic_buyer_score']}/10")
    print(f"  Overall:      {r['overall_score']}/100")
    print()

print("=" * 80)
print("SUMMARY")
print("=" * 80)
after_count = sum(1 for r in results if r["timing"] == "AFTER")
before_count = sum(1 for r in results if r["timing"] == "BEFORE")
same_count = sum(1 for r in results if r["timing"] == "SAME DAY")

print(f"Total won deals with scores: {len(results)}")
print(f"  Analyzed AFTER close:  {after_count}")
print(f"  Analyzed BEFORE close: {before_count}")
print(f"  Analyzed SAME DAY:     {same_count}")
print()

if after_count >= len(results) * 0.75:
    print("CONCLUSION: ≥75% analyzed POST-CLOSE")
    print("The reverse correlation (low Champion/EB on won deals) is likely")
    print("explained by analyzing deals after they closed, not framework failure.")
    print("Post-close scoring naturally differs from active-deal dynamics.")
else:
    print("CONCLUSION: Majority analyzed PRE-CLOSE or mixed timing")
    print("The low scores on won deals remain unexplained by timing alone.")
