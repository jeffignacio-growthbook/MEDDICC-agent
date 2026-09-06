#!/usr/bin/env python3
"""Check current values for all canonical questions with verified_value."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'api'))

from dotenv import load_dotenv
load_dotenv()

from db import get_supabase
import yaml

sb = get_supabase()

# Load canonical questions
with open('config/canonical_questions.yaml') as f:
    canonical = yaml.safe_load(f)

print("=" * 100)
print("CANONICAL QUESTIONS - VERIFIED VALUE AUDIT")
print("=" * 100)
print()

questions_to_check = [
    {
        'id': 'q003',
        'question': 'Which deals have no ARR recorded?',
        'check': lambda: check_no_arr_deals()
    },
    {
        'id': 'q004',
        'question': 'How is Christian tracking?',
        'check': lambda: check_christian_attainment()
    },
    {
        'id': 'q005',
        'question': 'What is team attainment for Q3?',
        'check': lambda: check_team_attainment()
    },
    {
        'id': 'q006',
        'question': 'How many deals are in COMMIT forecast category?',
        'check': lambda: check_commit_deals()
    }
]

def check_no_arr_deals():
    result = sb.table('deals').select('deal_id, deal_value, arr_usd').eq('deal_status', 'active').execute()
    no_arr = [d for d in result.data if (d.get('deal_value') or d.get('arr_usd') or 0) == 0]
    return {
        'count': len(no_arr),
        'total_deals': len(result.data),
        'pct': (len(no_arr) / len(result.data)) * 100
    }

def check_christian_attainment():
    # Get Q3 FY2027 bounds
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent / 'scripts'))
    from utils import get_fiscal_quarter
    from datetime import date

    # Q3 FY2027: Aug 1 - Oct 31, 2026
    q_start, q_end, label = get_fiscal_quarter(date(2026, 9, 1))

    result = sb.table('deals').select('deal_value, owner_email, close_date').eq('deal_status', 'won').execute()

    christian_won = [
        d for d in result.data
        if d.get('owner_email') == 'christian@growthbook.io'
        and d.get('close_date')
        and q_start.isoformat() <= d['close_date'] <= q_end.isoformat()
    ]

    won_arr = sum(d.get('deal_value', 0) or 0 for d in christian_won)

    return {
        'won_arr': won_arr,
        'deal_count': len(christian_won),
        'target': 250000,
        'attainment_pct': (won_arr / 250000) * 100
    }

def check_team_attainment():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent / 'scripts'))
    from utils import get_fiscal_quarter
    from datetime import date

    q_start, q_end, label = get_fiscal_quarter(date(2026, 9, 1))

    result = sb.table('deals').select('deal_value, close_date').eq('deal_status', 'won').execute()

    q3_won = [
        d for d in result.data
        if d.get('close_date')
        and q_start.isoformat() <= d['close_date'] <= q_end.isoformat()
    ]

    won_arr = sum(d.get('deal_value', 0) or 0 for d in q3_won)

    return {
        'won_arr': won_arr,
        'deal_count': len(q3_won),
        'target': 1550000,
        'attainment_pct': (won_arr / 1550000) * 100
    }

def check_commit_deals():
    result = sb.table('deals').select('deal_id, company_name, forecast_category, deal_value').eq('deal_status', 'active').execute()

    commit_deals = [d for d in result.data if (d.get('forecast_category') or '').upper() == 'COMMIT']
    commit_arr = sum(d.get('deal_value', 0) or 0 for d in commit_deals)

    return {
        'count': len(commit_deals),
        'total_deals': len(result.data),
        'commit_arr': commit_arr,
        'deals': [{'name': d.get('company_name'), 'value': d.get('deal_value', 0)} for d in commit_deals]
    }

# Check each question
for q in questions_to_check:
    print(f"{'='*100}")
    print(f"{q['id']}: {q['question']}")
    print(f"{'='*100}")

    # Get verified value from yaml
    verified = next((item['verified_value'] for item in canonical['questions'] if item['id'] == q['id']), None)

    print(f"\nVERIFIED VALUE (in canonical_questions.yaml):")
    if verified:
        for k, v in verified.items():
            print(f"  {k}: {v}")
    else:
        print("  null")

    print(f"\nCURRENT VALUE (from database):")
    try:
        current = q['check']()
        for k, v in current.items():
            if isinstance(v, float):
                print(f"  {k}: {v:,.2f}")
            elif isinstance(v, (int, str)):
                print(f"  {k}: {v}")
            elif isinstance(v, list):
                print(f"  {k}: {len(v)} items")
                for item in v[:3]:  # Show first 3
                    print(f"    - {item}")
    except Exception as e:
        print(f"  ERROR: {e}")

    print()

print("=" * 100)
print("RECOMMENDATIONS")
print("=" * 100)
print()
print("1. q003 (no ARR deals): Update from 127 to current count")
print("2. q006 (COMMIT deals): Update from '3 of 432' to current '2 of 444, $170K'")
print("3. q004 (Christian): Verify if still 0 or has changed")
print("4. q005 (Team): Verify if still 12.7% or has changed")
