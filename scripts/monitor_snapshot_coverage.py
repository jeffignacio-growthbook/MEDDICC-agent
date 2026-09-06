#!/usr/bin/env python3
"""
Trigger 6: Snapshot Coverage Monitor

SPEC: "A week-3 grid with 192 rows against a typical 475 — that is what forced
excluding Q2 from the conversion rate, and it was found weeks later."

REFINED DESIGN: Per-pipeline comparison against same week-of-quarter position
across prior quarters (not flat trailing median).
"""
import os, sys, yaml, json, requests
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))
from db import get_supabase

def load_config():
    with open(Path(__file__).parent.parent / 'config' / 'monitoring.yaml') as f:
        return yaml.safe_load(f)['monitoring']['correctness']['snapshot_coverage']

def get_current_quarter_info():
    sys.path.insert(0, str(Path(__file__).parent))
    from utils import get_fiscal_quarter
    from datetime import date
    today = date.today()
    q_start, q_end, fiscal_quarter = get_fiscal_quarter(today)
    days_into_quarter = (today - q_start).days
    week_of_quarter = min((days_into_quarter // 7) + 1, 13)
    return fiscal_quarter, week_of_quarter

def get_prior_quarters(fiscal_quarter, count=3):
    """Get N prior fiscal quarters."""
    # Parse quarter: "FY2027 Q1" -> (2027, 1)
    parts = fiscal_quarter.split()
    year = int(parts[0][2:])
    q = int(parts[1][1])
    
    prior = []
    for i in range(1, count + 1):
        new_q = q - i
        new_year = year
        while new_q < 1:
            new_q += 4
            new_year -= 1
        prior.append(f"FY{new_year} Q{new_q}")
    return prior

def check_snapshot_coverage(sb, config):
    current_quarter, current_week = get_current_quarter_info()
    
    # Get current week's snapshot
    result = sb.table('deals_snapshot').select('deal_id, pipeline_id').eq('fiscal_quarter', current_quarter).eq('week_of_quarter', current_week).execute()
    
    if not result.data:
        return None
    
    current_snaps = result.data
    
    # Group by pipeline
    current_by_pipeline = defaultdict(int)
    for snap in current_snaps:
        pipeline = snap.get('pipeline_id', 'default')
        current_by_pipeline[pipeline] += 1
    
    # Get same week from prior quarters
    prior_quarters = get_prior_quarters(current_quarter, config['trailing_quarters'])
    prior_by_pipeline = defaultdict(list)
    
    for prior_q in prior_quarters:
        result = sb.table('deals_snapshot').select('pipeline_id').eq('fiscal_quarter', prior_q).eq('week_of_quarter', current_week).execute()
        if result.data:
            for snap in result.data:
                pipeline = snap.get('pipeline_id', 'default')
                prior_by_pipeline[pipeline].append(1)
    
    # Check each pipeline
    coverage_issues = []
    
    for pipeline, current_count in current_by_pipeline.items():
        if pipeline not in prior_by_pipeline or len(prior_by_pipeline[pipeline]) == 0:
            continue
        
        # Calculate median of prior quarters
        import statistics
        typical_count = statistics.median(prior_by_pipeline[pipeline])
        
        if typical_count < config['min_expected_rows']:
            continue
        
        coverage_pct = current_count / typical_count
        
        if coverage_pct < config['min_row_share']:
            coverage_issues.append({
                'pipeline_id': pipeline,
                'current_count': current_count,
                'typical_count': int(typical_count),
                'coverage_pct': coverage_pct * 100,
                'threshold_pct': config['min_row_share'] * 100,
                'current_quarter': current_quarter,
                'week_of_quarter': current_week,
                'prior_quarters': prior_quarters
            })
    
    return coverage_issues if coverage_issues else None

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    
    config = load_config()
    if not config['enabled']:
        print("Disabled")
        return
    
    print("Checking snapshot coverage...")
    sb = get_supabase()
    issues = check_snapshot_coverage(sb, config)
    
    if not issues:
        print("✓ Coverage acceptable")
        return
    
    for evidence in issues:
        msg = f"⚠️ Snapshot Coverage Drop\\n\\n{evidence['current_quarter']} Week {evidence['week_of_quarter']}\\nPipeline: {evidence['pipeline_id']}\\n\\nCurrent: {evidence['current_count']} rows\\nTypical: {evidence['typical_count']} rows (median of {', '.join(evidence['prior_quarters'])})\\nCoverage: {evidence['coverage_pct']:.1f}% (threshold: {evidence['threshold_pct']:.0f}%)\\n\\n**Next steps:**\\n1. Check snapshot job logs\\n2. Verify data pipeline\\n3. Compare deal filters"
        
        payload = {"type": "monitoring_alert", "monitor": "snapshot_coverage", "fired_at": datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), "threshold_config": config, "evidence": evidence, "message": msg}
        
        url = os.getenv('ZAPIER_MONITORING_WEBHOOK_URL') if not args.dry_run else None
        if url:
            requests.post(url, json=payload, timeout=10)
        else:
            print(json.dumps(payload, indent=2))
        
        print(f"⚠️ COVERAGE: {evidence['pipeline_id']} {evidence['current_count']} vs {evidence['typical_count']} ({evidence['coverage_pct']:.0f}%)")

if __name__ == '__main__':
    main()
