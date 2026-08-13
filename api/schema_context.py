"""Schema context builder for dynamic queries."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
_cached_context = None

def get_schema_context(sb):
    global _cached_context
    if _cached_context:
        return _cached_context
    from supabase_client import select_all
    rows = select_all(sb, "data_dictionary",
        columns="supabase_table,supabase_column,data_type,description,enum_values,hubspot_name,source",
        filters=[("eq", "is_queryable", True)])
    if not rows:
        return _minimal_fallback_context()
    by_table = {}
    for r in rows:
        by_table.setdefault(r["supabase_table"], []).append(r)
    lines = ["QUERYABLE SUPABASE TABLES AND COLUMNS:", "(Use these exact column names in query tool calls)", ""]
    table_descriptions = {
        "deals": "Active and closed deals. One row per deal.",
        "analyses": "Nightly MEDDICC scores per deal. Latest row = most recent analysis.",
        "objections": "Objections raised in sales calls, extracted by AI. One row per objection instance.",
        "feature_gaps": "Feature gaps mentioned in sales calls. One row per gap instance.",
        "win_loss_narratives": "AI-generated win/loss analysis for closed deals.",
        "waterfall_weekly": "Weekly pipeline movement: new, won, lost, net_change. Precomputed.",
        "rep_targets": "Quota targets by rep/team/period.",
        "arr_by_customer": "VIEW: total ARR per won customer."}
    join_notes = """
TABLE RELATIONSHIPS:
  deals.deal_id → analyses.deal_id (one deal → many analyses; use latest)
  deals.deal_id → objections.deal_id
  deals.deal_id → feature_gaps.deal_id
  deals.company_name ≈ objections.company_name (fuzzy — prefer deal_id)
  deals.owner_email = rep identifier (maps to rep_targets.entity_email)
"""
    for table, cols in sorted(by_table.items()):
        desc = table_descriptions.get(table, "")
        lines.append(f"TABLE: {table}")
        if desc:
            lines.append(f"  Purpose: {desc}")
        for c in cols:
            col, dtype = c["supabase_column"], c["data_type"]
            cdesc = (c.get("description") or "")[:80]
            enum, hs = c.get("enum_values"), c.get("hubspot_name") or ""
            hs_note = f" [HubSpot: {hs}]" if hs and hs != col else ""
            line = f"  {col} ({dtype}){hs_note}: {cdesc}"
            if enum and dtype == "enumeration":
                try:
                    vals = json.loads(enum) if isinstance(enum, str) else enum
                    options = ", ".join(f'"{v["value"]}"' for v in vals[:8])
                    line += f" — values: [{options}]"
                except: pass
            lines.append(line)
        lines.append("")
    lines.append(join_notes)
    _cached_context = "\n".join(lines)
    return _cached_context

def invalidate_cache():
    global _cached_context
    _cached_context = None

def _minimal_fallback_context():
    return """
QUERYABLE TABLES (data dictionary not yet populated — run discover_properties.py):
  deals: company_name, deal_value, stage, deal_status, owner_email,
         create_date, close_date, segment, forecast_category,
         sao, new_arr, expansion_arr, lost_reason, pipeline_id
  analyses: deal_id, overall_score, champion_score, economic_buyer_score,
            decision_criteria_score, decision_process_score, pain_score,
            competition_score, component_details (JSONB), analyzed_at, status
  objections: company_name, category, verbatim_quote, rep_response,
              stage_when_raised, extracted_at
  feature_gaps: company_name, category, severity, competitor_mentioned,
                feature_description, extracted_at
  win_loss_narratives: company_name, outcome, stated_reason, narrative,
                       key_factors, generated_at
  waterfall_weekly: week_ending, pipeline_id, new_pipeline_value,
                    won_value, lost_value, net_change
  arr_by_customer: company_name, total_arr, won_deal_count

TABLE JOINS:
  deals.deal_id → analyses.deal_id, objections.deal_id, feature_gaps.deal_id
"""
