#!/usr/bin/env python3
"""
Trigger 3: Forecast Category Coverage Monitor

SPEC: "Three deals in COMMIT out of 432. That is a process finding and it
degrades quietly."

Alerts when COMMIT forecast category coverage is too low.
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
        return yaml.safe_load(f)['monitoring']['data_integrity']['forecast_category_coverage']

def check_commit_coverage(sb, config):
    result = sb.table('deals').select('deal_id, company_name, forecast_category, deal_value, owner_email').eq('deal_status', 'active').execute()
    if not result.data or len(result.data) < config['min_deals']:
        return None

    active_deals = result.data
    # Case-insensitive match: HubSpot stores as 'COMMIT' (uppercase)
    commit_deals = [d for d in active_deals if (d.get('forecast_category') or '').upper() == 'COMMIT']
    commit_share = len(commit_deals) / len(active_deals)
    
    if commit_share >= config['min_commit_share']:
        return None
    
    return {
        'total_active': len(active_deals),
        'commit_count': len(commit_deals),
        'commit_share_pct': commit_share * 100,
        'threshold_pct': config['min_commit_share'] * 100,
        'commit_arr': sum(d.get('deal_value', 0) or 0 for d in commit_deals),
        'total_arr': sum(d.get('deal_value', 0) or 0 for d in active_deals)
    }

def send_alert(evidence, config, dry_run):
    msg = f"⚠️ Forecast Category Coverage Alert\\n\\n**{evidence['commit_count']} deals** ({evidence['commit_share_pct']:.1f}%) in COMMIT\\nThreshold: {evidence['threshold_pct']:.0f}%\\nTotal active: {evidence['total_active']}\\n\\nCommit ARR: ${evidence['commit_arr']:,.0f} / ${evidence['total_arr']:,.0f}\\n\\n**Next steps:**\\n1. Review pipeline rigor\\n2. Coach reps on COMMIT criteria\\n3. Update forecast categories"
    
    payload = {"type": "monitoring_alert", "monitor": "forecast_category_coverage", "fired_at": datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), "threshold_config": config, "evidence": evidence, "message": msg}
    
    url = os.getenv('ZAPIER_MONITORING_WEBHOOK_URL') if not dry_run else None
    if url:
        try:
            requests.post(url, json=payload, timeout=10)
            print("✓ Alert sent")
        except Exception as e:
            print(f"⚠️ Failed: {e}")
    else:
        print(json.dumps(payload, indent=2))

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    
    config = load_config()
    if not config['enabled']:
        print("Disabled")
        return
    
    print("Checking forecast category coverage...")
    sb = get_supabase()
    evidence = check_commit_coverage(sb, config)
    
    if not evidence:
        print("✓ Coverage acceptable")
        return
    
    if args.dry_run:
        print("DRY RUN:")
    send_alert(evidence, config, args.dry_run)
    print(f"⚠️ COMMIT COVERAGE: {evidence['commit_count']} deals ({evidence['commit_share_pct']:.1f}%)")

if __name__ == '__main__':
    main()
