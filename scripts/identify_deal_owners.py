"""
Identify Rep Owners for Validation Deals

For each of the 16 boundary case deals, identify the owning rep
so natural pipeline check-in questions can be sent to the right person.
"""

import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Supabase setup
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 16 boundary case deals
validation_deals = [
    'Rippling',
    'DocPlanner',
    'TRT',
    'Deel',
    'GitLab Inc.',
    'Amazon',
    'Hy-Vee',
    'Electronic Arts',
    'Expedia Group',
    'Virgin Media O2 UK Limited',
    'Zynga',
    'Guidepoint',
    'Zurich Insurance Group',
    'Zurich Insurance',
    'ATrack Solutions',
    'Robinhood'
]

def get_deal_owner(company_name):
    """Get deal owner from deals table"""
    response = sb.table('deals').select(
        'deal_id, company_name, owner, stage, segment, deal_status'
    ).eq('company_name', company_name).eq('deal_status', 'active').execute()

    if response.data:
        return response.data[0]
    return None

print("=" * 80)
print("REP OWNERS FOR VALIDATION DEALS")
print("=" * 80)

print("\nIdentifying owners for 16 boundary case deals...\n")

owners_found = {}
owners_missing = []

for company in validation_deals:
    deal = get_deal_owner(company)

    if deal:
        owner = deal.get('owner', 'Unknown')
        owners_found[company] = {
            'owner': owner,
            'stage': deal['stage'],
            'segment': deal.get('segment', 'Unknown')
        }
    else:
        owners_missing.append(company)

# Group by owner
by_owner = {}
for company, info in owners_found.items():
    owner = info['owner']
    if owner not in by_owner:
        by_owner[owner] = []
    by_owner[owner].append({
        'company': company,
        'stage': info['stage'],
        'segment': info['segment']
    })

print("=" * 80)
print("DEALS GROUPED BY OWNER")
print("=" * 80)

for owner, deals in sorted(by_owner.items()):
    print(f"\n{owner} ({len(deals)} deals):")
    for deal in deals:
        print(f"  - {deal['company']} ({deal['segment']}, {deal['stage']})")

if owners_missing:
    print("\n" + "=" * 80)
    print("DEALS WITHOUT OWNER FOUND")
    print("=" * 80)
    for company in owners_missing:
        print(f"  - {company}")

print("\n" + "=" * 80)
print("SLACK MESSAGE TEMPLATE")
print("=" * 80)

print("\nSend one message per owner with their deals:\n")

print("\n⚠️  IMPORTANT: Do NOT include day counts in questions sent to reps.")
print("Let them answer unprompted. Questions below have NO numbers.\n")

for owner, deals in sorted(by_owner.items()):
    print(f"@{owner}:")
    for deal in deals:
        # Unprompted questions - NO day counts
        company = deal['company']
        if 'Zurich' in company:
            print(f"  • Where are we at with {company}?")
        elif company in ['GitLab Inc.', 'Electronic Arts', 'Expedia Group']:
            print(f"  • What's the status on {company}?")
        elif company in ['Deel', 'Rippling', 'Hy-Vee', 'TRT', 'Guidepoint']:
            print(f"  • Hey, where's {company} at?")
        elif company in ['Amazon', 'Virgin Media O2 UK Limited', 'Robinhood']:
            print(f"  • How's {company} looking - still live?")
        elif company in ['DocPlanner']:
            print(f"  • How's {company} looking?")
        else:
            print(f"  • What's happening with {company}?")
    print()

print("=" * 80)
print("RESPONSE TRACKING")
print("=" * 80)

print("\nFor each deal, record rep answer:")
print("  - Still moving")
print("  - Stalled")
print("  - Not sure")
print("\nThen compare against system classification.")
