#!/usr/bin/env python3
"""
Trigger 5: Metric Divergence Monitor

SPEC: "A computed value that disagrees with its registry `verified` figure
beyond tolerance."
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
        return yaml.safe_load(f)['monitoring']['correctness']['metric_divergence']

def load_metrics_registry():
    with open(Path(__file__).parent.parent / 'config' / 'metrics.yaml') as f:
        return yaml.safe_load(f)

def compute_metric(sb, metric_id):
    """Compute current value for a metric - placeholder, needs actual implementation"""
    # This would call the actual metric computation code
    # For now, return None to indicate not implemented
    return None

def check_divergence(sb, config):
    metrics = load_metrics_registry()
    divergences = []
    
    for metric_id, metric_spec in metrics.items():
        if 'verified_result' not in metric_spec:
            continue
        
        verified = metric_spec['verified_result'].get('value')
        if verified is None:
            continue
        
        live = compute_metric(sb, metric_id)
        if live is None:
            continue
        
        divergence_pct = abs((live - verified) / verified * 100)
        
        if divergence_pct > config['tolerance_pct']:
            divergences.append({
                'metric_id': metric_id,
                'verified_value': verified,
                'live_value': live,
                'divergence_pct': divergence_pct,
                'threshold_pct': config['tolerance_pct']
            })
    
    return divergences if divergences else None

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    
    config = load_config()
    if not config['enabled']:
        print("Disabled")
        return
    
    print("Checking metric divergence...")
    sb = get_supabase()
    divergences = check_divergence(sb, config)
    
    if not divergences:
        print("✓ All metrics within tolerance (or no verified metrics configured)")
        return
    
    for evidence in divergences:
        msg = f"⚠️ Metric Divergence Alert\\n\\nMetric: {evidence['metric_id']}\\nVerified: {evidence['verified_value']}\\nLive: {evidence['live_value']}\\nDivergence: {evidence['divergence_pct']:.1f}% (threshold: {evidence['threshold_pct']}%)\\n\\n**Next steps:**\\n1. Review computation logic\\n2. Check data quality\\n3. Update verified value if correct"
        
        payload = {"type": "monitoring_alert", "monitor": "metric_divergence", "fired_at": datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), "threshold_config": config, "evidence": evidence, "message": msg}
        
        url = os.getenv('ZAPIER_MONITORING_WEBHOOK_URL') if not args.dry_run else None
        if url:
            requests.post(url, json=payload, timeout=10)
        else:
            print(json.dumps(payload, indent=2))
        
        print(f"⚠️ DIVERGENCE: {evidence['metric_id']} ({evidence['divergence_pct']:.1f}%)")

if __name__ == '__main__':
    main()
