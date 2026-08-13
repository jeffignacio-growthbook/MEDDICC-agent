#!/usr/bin/env python3
"""
Discovers HubSpot deal properties and builds a data
dictionary mapping HubSpot fields to Supabase columns.

Usage:
  python scripts/discover_properties.py
  python scripts/discover_properties.py --dry-run
  python scripts/discover_properties.py --refresh
"""

import os, json, yaml, requests
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HUBSPOT_API_KEY = os.environ.get("HUBSPOT_API_KEY", "")

HUBSPOT_TO_SUPABASE = {
    "dealname": ("deals", "company_name"),
    "dealstage": ("deals", "stage"),
    "pipeline": ("deals", "pipeline_id"),
    "amount": ("deals", "arr_usd"),
    "closedate": ("deals", "close_date"),
    "hubspot_owner_id": ("deals", "owner_email"),
    "createdate": ("deals", "create_date"),
    "hs_deal_stage_probability": ("deals", "stage_probability"),
    "new_revenue": ("deals", "new_arr"),
    "expansion_revenue": ("deals", "expansion_arr"),
    "prior_arr": ("deals", "prior_arr"),
    "sao": ("deals", "sao"),
    "hs_forecast_category": ("deals", "forecast_category"),
    "hs_closed_lost_reason": ("deals", "lost_reason"),
    "closed_lost_reason": ("deals", "lost_reason"),
    "hs_deal_id": ("deals", "deal_id"),
    "hs_object_id": ("deals", "deal_id"),
    # NOTE: currency and deal_type don't exist in Supabase deals table - removed
}

COMPUTED_COLUMNS = [
    {"supabase_table": "deals", "supabase_column": "deal_value", "data_type": "number",
     "description": "Incremental ARR = new_arr + expansion_arr, NULL-safe. GrowthBook's primary deal value metric.", "source": "computed"},
    {"supabase_table": "deals", "supabase_column": "highest_stage_order_reached", "data_type": "number",
     "description": "High-water mark of deal stage progression (0-based order). Never decreases. Drives win-rate denominator.", "source": "computed"},
    {"supabase_table": "deals", "supabase_column": "segment", "data_type": "text",
     "description": "Company size segment: SMB (<250 employees), Mid-Market (250-2000), Enterprise (2000+).", "source": "computed"},
    {"supabase_table": "deals", "supabase_column": "deal_status", "data_type": "text",
     "description": "Computed from stage: active | won | lost. Used for filtering open vs. closed deals.", "source": "computed"},
    {"supabase_table": "analyses", "supabase_column": "overall_score", "data_type": "number",
     "description": "Composite MEDDICC score 0-100 from nightly AI analysis of call transcripts.", "source": "computed"},
    {"supabase_table": "analyses", "supabase_column": "champion_score", "data_type": "number",
     "description": "MEDDICC Champion component score 0-10 from call analysis.", "source": "computed"},
    {"supabase_table": "analyses", "supabase_column": "economic_buyer_score", "data_type": "number",
     "description": "MEDDICC Economic Buyer component score 0-10 from call analysis.", "source": "computed"},
    {"supabase_table": "analyses", "supabase_column": "decision_criteria_score", "data_type": "number",
     "description": "MEDDICC Decision Criteria component score 0-10 from call analysis.", "source": "computed"},
    {"supabase_table": "analyses", "supabase_column": "decision_process_score", "data_type": "number",
     "description": "MEDDICC Decision Process component score 0-10 from call analysis.", "source": "computed"},
    {"supabase_table": "analyses", "supabase_column": "pain_score", "data_type": "number",
     "description": "MEDDICC Identified Pain component score 0-10 from call analysis.", "source": "computed"},
    {"supabase_table": "analyses", "supabase_column": "competition_score", "data_type": "number",
     "description": "MEDDICC Competition component score 0-10 from call analysis.", "source": "computed"},
    {"supabase_table": "analyses", "supabase_column": "deal_id", "data_type": "text",
     "description": "Deal ID — join key to deals table.", "source": "computed"},
]

# Supabase-only tables (ETL-generated, not HubSpot properties)
SUPABASE_ONLY_TABLES = [
    {"source": "computed", "supabase_table": "objections", "supabase_column": "category", "data_type": "enumeration",
     "description": "Objection category extracted from calls", "is_queryable": True, "hubspot_name": None,
     "enum_values": [{"value": "budget", "label": "Budget"}, {"value": "technical", "label": "Technical"},
         {"value": "timing", "label": "Timing"}, {"value": "product_gap", "label": "Product Gap"},
         {"value": "switching_cost", "label": "Switching Cost"}, {"value": "trust", "label": "Trust"},
         {"value": "internal_politics", "label": "Internal Politics"}, {"value": "other", "label": "Other"}]},
    {"source": "computed", "supabase_table": "objections", "supabase_column": "verbatim_quote", "data_type": "text",
     "description": "Close paraphrase of what the prospect said", "is_queryable": True, "hubspot_name": None},
    {"source": "computed", "supabase_table": "objections", "supabase_column": "rep_response", "data_type": "text",
     "description": "How the rep addressed it. NULL = unaddressed", "is_queryable": True, "hubspot_name": None},
    {"source": "computed", "supabase_table": "objections", "supabase_column": "stage_when_raised", "data_type": "text",
     "description": "Pipeline stage when this objection occurred", "is_queryable": True, "hubspot_name": None},
    {"source": "computed", "supabase_table": "objections", "supabase_column": "company_name", "data_type": "text",
     "description": "Company that raised the objection", "is_queryable": True, "hubspot_name": None},
    {"source": "computed", "supabase_table": "objections", "supabase_column": "deal_id", "data_type": "text",
     "description": "Deal ID — join to deals table", "is_queryable": True, "hubspot_name": None},
    {"source": "computed", "supabase_table": "feature_gaps", "supabase_column": "category", "data_type": "enumeration",
     "description": "Feature gap category", "is_queryable": True, "hubspot_name": None,
     "enum_values": [{"value": "platform_capability", "label": "Platform Capability"},
         {"value": "integration", "label": "Integration"}, {"value": "reporting", "label": "Reporting"},
         {"value": "permissions_security", "label": "Permissions/Security"},
         {"value": "pricing_packaging", "label": "Pricing/Packaging"}, {"value": "other", "label": "Other"}]},
    {"source": "computed", "supabase_table": "feature_gaps", "supabase_column": "severity", "data_type": "enumeration",
     "description": "How much this gap affects the deal", "is_queryable": True, "hubspot_name": None,
     "enum_values": [{"value": "blocker", "label": "Blocker"}, {"value": "nice_to_have", "label": "Nice to Have"},
         {"value": "workaround_exists", "label": "Workaround Exists"}]},
    {"source": "computed", "supabase_table": "feature_gaps", "supabase_column": "competitor_mentioned", "data_type": "text",
     "description": "Competitor named when gap was raised. NULL if none.", "is_queryable": True, "hubspot_name": None},
    {"source": "computed", "supabase_table": "feature_gaps", "supabase_column": "feature_description", "data_type": "text",
     "description": "Description of the missing feature", "is_queryable": True, "hubspot_name": None},
    {"source": "computed", "supabase_table": "feature_gaps", "supabase_column": "company_name", "data_type": "text",
     "description": "Company that raised the feature gap", "is_queryable": True, "hubspot_name": None},
    {"source": "computed", "supabase_table": "feature_gaps", "supabase_column": "deal_id", "data_type": "text",
     "description": "Deal ID — join to deals table", "is_queryable": True, "hubspot_name": None},
    {"source": "computed", "supabase_table": "win_loss_narratives", "supabase_column": "outcome", "data_type": "enumeration",
     "description": "Deal outcome", "is_queryable": True, "hubspot_name": None,
     "enum_values": [{"value": "won", "label": "Won"}, {"value": "lost", "label": "Lost"}]},
    {"source": "computed", "supabase_table": "win_loss_narratives", "supabase_column": "company_name", "data_type": "text",
     "description": "Company name for the closed deal", "is_queryable": True, "hubspot_name": None},
    {"source": "computed", "supabase_table": "win_loss_narratives", "supabase_column": "stated_reason", "data_type": "text",
     "description": "Rep-entered close reason from CRM", "is_queryable": True, "hubspot_name": None},
    {"source": "computed", "supabase_table": "win_loss_narratives", "supabase_column": "competitor_mentioned", "data_type": "text",
     "description": "Competitor mentioned in the win/loss narrative", "is_queryable": True, "hubspot_name": None},
]

def fetch_all_properties():
    url = "https://api.hubapi.com/crm/v3/properties/deals"
    resp = requests.get(url, params={"limit": 1000, "archived": False},
        headers={"Authorization": f"Bearer {HUBSPOT_API_KEY}"}, timeout=30)
    resp.raise_for_status()
    return resp.json().get("results", [])

def build_entry(prop):
    name = prop.get("name", "")
    label = prop.get("label", "")
    ptype = prop.get("type", "string")
    desc = prop.get("description", "") or label
    type_map = {"string": "text", "number": "number", "bool": "boolean",
                "date": "date", "datetime": "date", "enumeration": "enumeration"}
    data_type = type_map.get(ptype, "text")
    enum_values = None
    if ptype == "enumeration":
        options = prop.get("options", [])
        if options:
            enum_values = [{"value": o["value"], "label": o["label"]}
                for o in options if not o.get("hidden", False)]
    supabase_table, supabase_col = HUBSPOT_TO_SUPABASE.get(name, (None, None))
    return {"source": "hubspot", "hubspot_name": name, "hubspot_label": label,
        "supabase_table": supabase_table, "supabase_column": supabase_col,
        "data_type": data_type, "enum_values": enum_values,
        "description": desc[:500], "is_queryable": supabase_col is not None,
        "last_refreshed": datetime.utcnow().isoformat()}

def write_yaml(entries):
    path = REPO_ROOT / "config" / "data_dictionary.yaml"
    organized = {}
    for e in entries:
        table = e.get("supabase_table") or "hubspot_only"
        organized.setdefault(table, []).append({
            "hubspot": e.get("hubspot_name"), "column": e.get("supabase_column"),
            "type": e.get("data_type"), "label": e.get("hubspot_label"),
            "description": e.get("description", "")[:120]})
    with open(path, "w") as f:
        yaml.dump(organized, f, allow_unicode=True, default_flow_style=False, sort_keys=True)
    print(f"✓ Wrote {path}")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    print("Fetching HubSpot deal properties...")
    props = fetch_all_properties()
    print(f"Found {len(props)} properties")
    entries = [build_entry(p) for p in props if build_entry(p)]
    for c in COMPUTED_COLUMNS:
        c["last_refreshed"] = datetime.utcnow().isoformat()
        entries.append(c)
    for t in SUPABASE_ONLY_TABLES:
        t["last_refreshed"] = datetime.utcnow().isoformat()
        entries.append(t)
    queryable = [e for e in entries if e.get("is_queryable")]
    print(f"\nQueryable in Supabase: {len(queryable)}")
    print(f"HubSpot-only (not yet in ETL): {len(entries) - len(queryable)}")
    print("\nQueryable columns:")
    for e in sorted(queryable, key=lambda x: x.get("supabase_table","")):
        print(f"  {e['supabase_table']}.{e['supabase_column']} ← {e.get('hubspot_name','computed')} ({e['data_type']})")
    if args.dry_run:
        print("\nDRY RUN — no writes")
        return
    write_yaml(entries)
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE credentials not set — skipping DB write")
        return
    from supabase import create_client
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    written, errors = 0, 0
    for e in entries:
        if not e.get("supabase_table") or not e.get("supabase_column"):
            continue
        try:
            sb.table("data_dictionary").upsert({**e, "enum_values": json.dumps(e["enum_values"]) if e.get("enum_values") else None},
                on_conflict="supabase_table,supabase_column").execute()
            written += 1
        except Exception as ex:
            print(f"  Error: {e.get('supabase_column')}: {ex}")
            errors += 1
    print(f"\n✓ Wrote {written} entries to data_dictionary table")
    if errors:
        print(f"  {errors} errors — check column names")

if __name__ == "__main__":
    main()
