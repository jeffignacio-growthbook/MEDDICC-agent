#!/usr/bin/env python3
"""
Trigger 4: Stale Precomputed Tables Monitor

SPEC: "forecast_weekly was 21 days old when it was first read. Alert when
computed_at exceeds its refresh interval."
"""
import os, sys, yaml, json, requests
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))
from db import get_supabase

def load_config():
    with open(Path(__file__).parent.parent / 'config' / 'monitoring.yaml') as f:
        return yaml.safe_load(f)['monitoring']['data_integrity']['stale_precomputed_tables']

def check_table_freshness(sb, table_name, table_config):
    col = table_config['computed_at_column']
    result = sb.table(table_name).select(col).order(col, desc=True).limit(1).execute()
    
    if not result.data:
        return None
    
    computed_at_str = result.data[0][col]
    computed_at = datetime.fromisoformat(computed_at_str.replace('Z', '+00:00'))
    age_days = (datetime.now(computed_at.tzinfo) - computed_at).days
    
    if age_days <= table_config['max_age_days']:
        return None
    
    return {'table': table_name, 'computed_at': computed_at_str, 'age_days': age_days, 'max_age_days': table_config['max_age_days']}

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    
    config = load_config()
    if not config['enabled']:
        print("Disabled")
        return
    
    print("Checking precomputed table freshness...")
    sb = get_supabase()
    stale_tables = []
    
    for table_name, table_config in config['tables'].items():
        evidence = check_table_freshness(sb, table_name, table_config)
        if evidence:
            stale_tables.append(evidence)
    
    if not stale_tables:
        print("✓ All tables fresh")
        return
    
    for evidence in stale_tables:
        msg = f"⚠️ Stale Table Alert\\n\\nTable: {evidence['table']}\\nLast computed: {evidence['computed_at']}\\nAge: {evidence['age_days']} days (max: {evidence['max_age_days']})\\n\\n**Next steps:**\\n1. Check ETL job status\\n2. Run manual refresh\\n3. Verify data pipeline"
        
        payload = {"type": "monitoring_alert", "monitor": "stale_precomputed_tables", "fired_at": datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), "threshold_config": config, "evidence": evidence, "message": msg}
        
        url = os.getenv('ZAPIER_MONITORING_WEBHOOK_URL') if not args.dry_run else None
        if url:
            requests.post(url, json=payload, timeout=10)
        else:
            print(json.dumps(payload, indent=2))
        
        print(f"⚠️ STALE TABLE: {evidence['table']} ({evidence['age_days']} days old)")

if __name__ == '__main__':
    main()
