#!/usr/bin/env python3
"""
Task B3: Validate stage-aware risk logic against real production data.

Shows old-flags vs new-flags side-by-side for the 10 deals from live test:
USIM, MedCof, Zoro, Box, Zalando, BESTSELLER, Square, ECCO, Chaos, OpenTable
"""

import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def validate_stage_aware_logic():
    """Compare old flat-threshold logic vs new stage-aware logic on real deals."""
    import asyncio
    from scripts.supabase_client import select_all
    from supabase import create_client
    from api.stage_requirements import get_requirements_for_stage, _get_stage_by_id

    # Connect to production Supabase
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_KEY')
    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        sys.exit(1)

    sb = create_client(url, key)

    print("="*80)
    print("TASK B3: STAGE-AWARE RISK VALIDATION AGAINST PRODUCTION DATA")
    print("="*80)
    print()

    # The 10 deals from live test
    target_companies = [
        "USIM", "MedCof", "Zoro", "Box", "Zalando",
        "BESTSELLER", "Square", "ECCO", "Chaos", "OpenTable"
    ]

    print(f"Fetching deals for: {', '.join(target_companies)}")
    print()

    # Fetch analyses and deals for these companies
    analyses = select_all(sb, "analyses",
        columns="deal_id,company_name,overall_score,"
                "champion_score,economic_buyer_score,"
                "pain_score,metrics_score,decision_criteria_score,"
                "decision_process_score,competition_score,analyzed_at")

    # Keep most recent analysis per deal
    latest_analyses = {}
    for a in analyses:
        deal_id = a["deal_id"]
        analyzed_at = a.get("analyzed_at", "")
        if deal_id not in latest_analyses or analyzed_at > latest_analyses[deal_id].get("analyzed_at", ""):
            latest_analyses[deal_id] = a

    analyses = list(latest_analyses.values())

    # Filter to target companies
    target_analyses = [a for a in analyses
                      if any(company.lower() in a["company_name"].lower()
                            for company in target_companies)]

    # Fetch deal stage data
    deal_ids = [a["deal_id"] for a in target_analyses]
    deals = select_all(sb, "deals",
        columns="deal_id,company_name,stage,deal_value",
        filters=[("in_", "deal_id", deal_ids)])

    deal_map = {d["deal_id"]: d for d in deals}

    # Component name mapping
    component_fields = {
        "pain": "pain_score",
        "champion": "champion_score",
        "metrics": "metrics_score",
        "economic_buyer": "economic_buyer_score",
        "decision_criteria": "decision_criteria_score",
        "decision_process": "decision_process_score",
        "competition": "competition_score",
    }

    # Build comparison table
    print(f"{'Company':<20} | {'Stage':<15} | {'OLD Flags':<35} | {'NEW Flags'}")
    print("-" * 120)

    for a in target_analyses[:10]:  # Cap at 10 for readability
        d = deal_map.get(a["deal_id"])
        if not d:
            continue

        company = a["company_name"][:18]
        stage_id = d.get("stage", "unknown")
        stage_info = _get_stage_by_id(stage_id)
        stage_name = stage_info["name"][:13] if stage_info else "Unknown"

        # OLD LOGIC: Flat thresholds (score < 40 OR champ < 4)
        score = a.get("overall_score", 0) or 0
        champ = a.get("champion_score", 0) or 0
        eb = a.get("economic_buyer_score", 0) or 0

        old_flags = []
        if score < 40:
            old_flags.append("low overall")
        if champ < 4:
            old_flags.append("no champ")
        if eb < 4:
            old_flags.append("no EB")

        old_flags_str = ", ".join(old_flags) if old_flags else "-"

        # NEW LOGIC: Stage-aware requirements
        requirements = get_requirements_for_stage(stage_id)
        new_flags = []

        if not requirements:
            new_flags_str = "(terminal/excluded stage)"
        else:
            for component, required_threshold in requirements.items():
                field_name = component_fields.get(component)
                if not field_name:
                    continue

                actual_score = a.get(field_name, 0) or 0

                if actual_score < required_threshold:
                    comp_display = component.replace("_", " ").title()[:12]
                    new_flags.append(
                        f"{comp_display} {actual_score}/{required_threshold}"
                    )

            new_flags_str = ", ".join(new_flags) if new_flags else "-"

        print(f"{company:<20} | {stage_name:<15} | {old_flags_str:<35} | {new_flags_str}")

    print()
    print("="*80)
    print("INTERPRETATION")
    print("="*80)
    print()
    print("OLD Flags: Flat thresholds (champ < 4, overall < 40, EB < 4)")
    print("  - Flags deals for components not yet due at their stage")
    print("  - Example: Discovery deal flagged for 'no EB' when EB not required")
    print()
    print("NEW Flags: Stage-aware requirements from config/client.yaml")
    print("  - Only flags components required to advance FROM current stage")
    print("  - Example: Discovery deal with EB=0 but Champion=5 → NOT flagged")
    print("           (EB not required until Scoping→Proposal)")
    print()
    print("Expected changes:")
    print("  - FEWER false positives (e.g., USIM 'no EB' at Discovery → removed)")
    print("  - MORE accurate signals (flags only overdue components)")
    print("  - POSSIBLE new flags (deals 'fine' under old logic but behind")
    print("    on a truly required component)")
    print()

if __name__ == "__main__":
    validate_stage_aware_logic()
