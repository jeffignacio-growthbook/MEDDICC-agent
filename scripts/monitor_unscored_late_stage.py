#!/usr/bin/env python3
"""
Trigger 8: Unscored Late Stage Monitor

NOT in original spec - added during build (2026-09-05).
RATIONALE: Late-stage deals without MEDDICC scores is operationally useful.

Alerts when late-stage deals lack MEDDICC scores.
"""
import os, sys, yaml, json, requests
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))
from db import get_supabase

def load_config():
    with open(Path(__file__).parent.parent / 'config' / 'monitoring.yaml') as f:
        return yaml.safe_load(f)['monitoring']['data_integrity']['unscored_late_stage']

def check_unscored_late_stage(sb, config):
    # Query deals in late stages
    late_stages = config['late_stages']

    result = sb.table('deals').select('deal_id, company_name, stage, owner_email').eq('deal_status', 'active').execute()

    if not result.data:
        return None

    # Filter to late stages
    late_stage_deals = [d for d in result.data if d.get('stage') in late_stages]

    if not late_stage_deals:
        return None

    # Get all deal IDs
    deal_ids = [d['deal_id'] for d in late_stage_deals]

    # Query analyses table to find which deals have been scored
    analyses_result = sb.table('analyses').select('deal_id').in_('deal_id', deal_ids).execute()

    scored_deal_ids = set(a['deal_id'] for a in (analyses_result.data or []))

    # Find unscored (deals without any analysis)
    unscored = [d for d in late_stage_deals if d['deal_id'] not in scored_deal_ids]

    if len(unscored) <= config['max_unscored_count']:
        return None

    # Owner distribution
    from collections import Counter
    owner_counts = Counter(d.get('owner_email', 'unassigned') for d in unscored)

    return {
        'unscored_count': len(unscored),
        'threshold': config['max_unscored_count'],
        'total_late_stage': len(late_stage_deals),
        'owner_distribution': dict(owner_counts.most_common(10)),
        'sample_deals': [{'deal_id': d['deal_id'], 'name': d.get('company_name', 'Unknown'), 'stage': d.get('stage'), 'owner': d.get('owner_email', 'unassigned')} for d in unscored[:10]]
    }

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    
    config = load_config()
    if not config['enabled']:
        print("Disabled")
        return
    
    print("Checking for unscored late-stage deals...")
    sb = get_supabase()
    evidence = check_unscored_late_stage(sb, config)
    
    if not evidence:
        print("✓ Late-stage deals have scores")
        return
    
    msg = f"⚠️ Unscored Late-Stage Deals\\n\\n**{evidence['unscored_count']} deals** in late stage without MEDDICC scores\\nThreshold: {evidence['threshold']}\\nTotal late-stage: {evidence['total_late_stage']}\\n\\n**Impact:**\\n• Deal review quality degraded\\n• Forecast confidence unclear\\n• Coaching gaps invisible\\n\\n**Next steps:**\\n1. Review sample deals\\n2. Run MEDDICC agent on unscored deals\\n3. Coach owners on scoring discipline"
    
    payload = {"type": "monitoring_alert", "monitor": "unscored_late_stage", "fired_at": datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), "threshold_config": config, "evidence": evidence, "message": msg}
    
    url = os.getenv('ZAPIER_MONITORING_WEBHOOK_URL') if not args.dry_run else None
    if url:
        requests.post(url, json=payload, timeout=10)
    else:
        print(json.dumps(payload, indent=2))
    
    print(f"⚠️ UNSCORED: {evidence['unscored_count']} late-stage deals without MEDDICC scores")

if __name__ == '__main__':
    main()
