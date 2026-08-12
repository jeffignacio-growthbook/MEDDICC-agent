#!/usr/bin/env python3
"""
ETL: HubSpot Deals API → Deal Index

Modes:
  --mode active (default): Fetches active deals only, writes to memory/deals/index.json and Supabase
  --mode history: Fetches ALL deals including closed, writes to Supabase only for CRO history queries

Auto-detects pipeline stages to exclude (closed won/lost, meeting set) in active mode.
"""
import json
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime
import re

# Add parent directory to path for imports
REPO_ROOT = Path(__file__).parent.parent
DEALS_DIR = REPO_ROOT / 'memory' / 'deals'
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from utils import slugify

DEALS_DIR.mkdir(parents=True, exist_ok=True)

# Exclude Renewal Pipeline (both by name and ID)
EXCLUDED_PIPELINES = ['renewal', '866608541']

# Exclude Disqualified stage
DISQUALIFIED_STAGES = ['68509551']

# Exclude Meeting Set stages (always filter these out in active mode)
# '79653122' = Meeting Set (numeric ID)
# NOTE: 'appointmentscheduled' is Discovery stage, NOT Meeting Set - do not exclude
MEETING_SET_STAGES = ['79653122']

# Closed stage IDs for history mode deal_status tagging
CLOSED_WON_STAGES = ['closedwon', '1297321623']
CLOSED_LOST_STAGES = ['closedlost', '1297321624']


def get_deal_status(stage: str) -> str:
    """Determine deal status for history mode."""
    if stage in CLOSED_WON_STAGES:
        return 'won'
    if stage in CLOSED_LOST_STAGES:
        return 'lost'
    return 'active'


def calculate_days_to_close(create_date_str: str, close_date_str: str) -> int:
    """Calculate days from create to close for closed deals."""
    try:
        if not create_date_str or not close_date_str:
            return None
        create_date = datetime.fromisoformat(create_date_str.split('T')[0])
        close_date = datetime.fromisoformat(close_date_str.split('T')[0])
        return (close_date - create_date).days
    except Exception:
        return None


def _excluded_stages_from_pipeline_config(config: dict) -> dict:
    """
    Extract excluded stages from NEW pipeline config shape.

    New shape (pipeline.pipelines[] with per-stage flags):
      pipeline:
        pipelines:
          - id: "default"
            name: "Sales Pipeline"
            stages:
              - id: "79653122"
                name: "Meeting Set"
                order: 1
                exclude_from_analysis: true  # Too early
              - id: "68509551"
                name: "Disqualified"
                order: 99
                is_lost: true
                exclude_from_analysis: true
              - id: "closedwon"
                name: "Closed Won"
                order: 100
                is_won: true

    RULE: Disqualified stages get BOTH is_lost=true AND exclude_from_analysis=true.
    Lost stages (is_lost=true) are included in waterfall unless exclude_from_analysis=true.
    """
    meeting_set = []
    disqualified = []
    closed_won = []
    closed_lost = []
    excluded_pipelines = []

    pipeline_config = config.get('pipeline', {})

    # Extract stage exclusions from pipeline.pipelines[] structure
    for pipeline in pipeline_config.get('pipelines', []):
        pipeline_id = pipeline.get('id', '')

        # Derive excluded_pipelines from analyze: false
        if pipeline.get('analyze', True) is False:
            if pipeline_id and 'YOUR_' not in str(pipeline_id):
                excluded_pipelines.append(pipeline_id)

        for stage in pipeline.get('stages', []):
            stage_id = stage.get('id', '')
            if not stage_id or 'YOUR_' in str(stage_id):
                continue

            # Closed won stages (aggregate across ALL pipelines for terminal detection)
            if stage.get('is_won', False):
                closed_won.append(stage_id)

            # Closed lost stages (aggregate across ALL pipelines; exclude disqualified)
            if stage.get('is_lost', False) and not stage.get('exclude_from_analysis', False):
                closed_lost.append(stage_id)

            # Disqualified stages (BOTH is_lost AND exclude_from_analysis)
            if stage.get('is_lost', False) and stage.get('exclude_from_analysis', False):
                disqualified.append(stage_id)

            # Meeting set stages (exclude_from_analysis but not is_lost)
            if stage.get('exclude_from_analysis', False) and not stage.get('is_lost', False):
                meeting_set.append(stage_id)

    return {
        'meeting_set': meeting_set,
        'disqualified': disqualified,
        'closed_won': closed_won or CLOSED_WON_STAGES,
        'closed_lost': closed_lost or CLOSED_LOST_STAGES,
        'excluded_pipelines': excluded_pipelines or EXCLUDED_PIPELINES,
    }


def _excluded_stages_from_legacy_config(config: dict) -> dict:
    """
    Extract excluded stages from LEGACY config shape (for backward compatibility).

    Legacy shape (excluded_stages.meeting_set[], etc.):
      excluded_stages:
        meeting_set:
          - name: "Meeting Set"
            id: "79653122"
        disqualified:
          - name: "Disqualified"
            id: "68509551"
        closed_won:
          - name: "Closed Won"
            id: "closedwon"
    """
    excluded = config.get('excluded_stages', {})

    def get_ids(section):
        stages = excluded.get(section, [])
        if isinstance(stages, list):
            return [s.get('id') for s in stages if s.get('id')
                    and 'YOUR_' not in str(s.get('id', ''))]
        return []

    excluded_pipelines = []
    for pipeline in config.get('pipelines', {}).get('excluded', []):
        pipeline_id = pipeline.get('id', '')
        if pipeline_id and 'YOUR_' not in str(pipeline_id):
            excluded_pipelines.append(pipeline_id)

    return {
        'meeting_set': get_ids('meeting_set'),
        'disqualified': get_ids('disqualified'),
        'closed_won': get_ids('closed_won') or CLOSED_WON_STAGES,
        'closed_lost': get_ids('closed_lost') or CLOSED_LOST_STAGES,
        'excluded_pipelines': excluded_pipelines or EXCLUDED_PIPELINES,
    }


def get_excluded_stages() -> dict:
    """
    Load stage exclusions from config/client.yaml.

    Supports TWO config shapes:
    1. NEW: pipeline.pipelines[] with per-stage flags (Phase A analytics)
    2. LEGACY: excluded_stages.meeting_set[] (backward compatible)

    The new shape wins if both exist. Falls back to legacy if only legacy exists.
    Falls back to hardcoded defaults if config doesn't exist.

    Returns:
        dict: {
            'meeting_set': [stage_ids],
            'disqualified': [stage_ids],
            'closed_won': [stage_ids],
            'closed_lost': [stage_ids],
            'excluded_pipelines': [pipeline_ids]
        }
    """
    try:
        import yaml
        config_path = REPO_ROOT / 'config' / 'client.yaml'
        if not config_path.exists():
            print("  ⚠️  config/client.yaml not found")
            print("     Run: python scripts/discover_stages.py")
            print("     Then configure your stage IDs in client.yaml")
            return {
                'meeting_set': MEETING_SET_STAGES,
                'disqualified': DISQUALIFIED_STAGES,
                'closed_won': CLOSED_WON_STAGES,
                'closed_lost': CLOSED_LOST_STAGES,
                'excluded_pipelines': EXCLUDED_PIPELINES,
            }

        with open(config_path) as f:
            config = yaml.safe_load(f)

        # NEW SHAPE: Check for pipeline.pipelines[] structure
        if 'pipeline' in config and 'pipelines' in config['pipeline']:
            pipelines = config['pipeline'].get('pipelines', [])
            if pipelines and isinstance(pipelines, list) and len(pipelines) > 0:
                # Has new shape - use it
                return _excluded_stages_from_pipeline_config(config)

        # LEGACY SHAPE: Fall back to excluded_stages.*
        if 'excluded_stages' in config:
            return _excluded_stages_from_legacy_config(config)

        # No config - use defaults
        return {
            'meeting_set': MEETING_SET_STAGES,
            'disqualified': DISQUALIFIED_STAGES,
            'closed_won': CLOSED_WON_STAGES,
            'closed_lost': CLOSED_LOST_STAGES,
            'excluded_pipelines': EXCLUDED_PIPELINES,
        }

    except Exception as e:
        print(f"  ⚠️  Could not load client.yaml: {e}")
        return {
            'meeting_set': MEETING_SET_STAGES,
            'disqualified': DISQUALIFIED_STAGES,
            'closed_won': CLOSED_WON_STAGES,
            'closed_lost': CLOSED_LOST_STAGES,
            'excluded_pipelines': EXCLUDED_PIPELINES,
        }


def get_meeting_set_stages(hubspot):
    """
    Fetch pipeline stages and auto-detect Meeting Set stages.
    Returns list of stage IDs.
    """
    # Start with hardcoded Meeting Set stages
    meeting_set_stages = list(MEETING_SET_STAGES)

    try:
        endpoint = "/crm/v3/pipelines/deals"
        response = hubspot._get(endpoint)
        pipelines = response.get('results', [])

        for pipeline in pipelines:
            stages = pipeline.get('stages', [])
            for stage in stages:
                stage_label = stage.get('label', '').lower()
                stage_id = stage.get('id', '')

                # Auto-detect additional meeting set stages by label
                if 'meeting set' in stage_label and stage_id not in meeting_set_stages:
                    meeting_set_stages.append(stage_id)

        return meeting_set_stages

    except Exception as e:
        print(f"⚠️  Could not fetch stages: {e}")
        return MEETING_SET_STAGES


def main():
    parser = argparse.ArgumentParser(description="ETL HubSpot deals to memory/Supabase")
    parser.add_argument(
        '--mode',
        type=str,
        choices=['active', 'history', 'analytics'],
        default='active',
        help=('active (default): active deals for MEDDICC agent\n'
              'history: all deals including closed (Supabase only)\n'
              'analytics: ALL deals all stages (Supabase only, '
              'for snapshot/waterfall/qualification-rate)')
    )
    parser.add_argument(
        '--file',
        type=str,
        help='Deals CSV file path (for history/analytics mode bulk import from HubSpot export)'
    )
    parser.add_argument(
        '--companies-file',
        type=str,
        help='Companies CSV file path (optional, for joining employee counts in analytics mode)'
    )
    args = parser.parse_args()

    # Validate: --file requires --mode history or analytics
    if args.file and args.mode == 'active':
        print("ERROR: --file can only be used with --mode history or --mode analytics")
        print("       Active mode fetches live data from HubSpot API")
        return

    print("=" * 80)
    print(f"HUBSPOT DEALS ETL - MODE: {args.mode.upper()}")
    print("=" * 80)

    # Load stage exclusions from config
    excluded = get_excluded_stages()

    # Initialize HubSpot client (skip if using CSV mode)
    hubspot = None
    if not args.file:
        print("\n1. Connecting to HubSpot API...")
        try:
            from hubspot_deals import get_hubspot_deals_client
            hubspot = get_hubspot_deals_client()
        except Exception as e:
            print(f"❌ Failed to initialize HubSpot client: {e}")
            print("\nMake sure HUBSPOT_API_KEY environment variable is set.")
            return
    else:
        print("\n1. CSV Mode - skipping HubSpot API connection")

    # Determine which deals to fetch based on mode
    if args.mode == 'active':
        # Auto-detect Meeting Set stages
        print("\n2. Auto-detecting Meeting Set stages...")
        meeting_set_stages = get_meeting_set_stages(hubspot)
        print(f"   Meeting Set stages: {meeting_set_stages}")

        # Fetch active deals only (excludes closed stages via dynamic filtering)
        print("\n3. Fetching active deals from HubSpot API...")
        try:
            all_deals_api = hubspot.get_active_deals()
            closed_stages = hubspot._get_closed_stage_ids()
            print(f"   Fetched {len(all_deals_api)} deals")
            print(f"   Auto-excluded closed stages: {closed_stages}")
        except Exception as e:
            print(f"❌ Failed to fetch deals: {e}")
            return
    elif args.mode == 'analytics':
        # Analytics mode: fetch ALL deals (no stage exclusions)
        meeting_set_stages = []
        closed_stages = []

        if args.file:
            # Load from CSV export(s)
            print("\n2. Loading from CSV export (analytics mode)...")
            from csv_loader import load_deals_from_csv

            try:
                all_deals_api, csv_stats = load_deals_from_csv(
                    args.file,
                    args.companies_file
                )

                # For CSV mode, pre-populate company data from the CSV join
                # (no API calls needed)
                deal_to_company = {}
                company_properties = {}

                for deal in all_deals_api:
                    deal_id = deal.get('id')
                    company_id = deal.get('company_id')
                    company_name = deal.get('company_name', '')
                    employee_count = deal.get('company_numberofemployees', '')

                    deal_to_company[deal_id] = company_id
                    if company_id:
                        company_properties[company_id] = {
                            'name': company_name,
                            'numberofemployees': employee_count
                        }

                print(f"\n  CSV Mode: {len(all_deals_api)} deals loaded with pre-joined company data")

            except Exception as e:
                print(f"❌ Failed to load CSV: {e}")
                import traceback
                traceback.print_exc()
                return

        else:
            # Fetch from HubSpot API
            print("\n2. Fetching ALL deals from HubSpot API (analytics mode)...")
            try:
                all_deals_api = hubspot.get_all_deals_including_closed()
                print(f"   Fetched {len(all_deals_api)} deals (all stages)")
            except Exception as e:
                print(f"❌ Failed to fetch deals: {e}")
                return

            # Batch fetch company associations and employee counts for segmentation
            print("\n3. Batch fetching company associations and employee counts...")
            deal_ids = [d.get('id') for d in all_deals_api if d.get('id')]
            print(f"   Fetching company associations for {len(deal_ids)} deals...")

            # Step 1: Batch get company IDs for all deals
            deal_to_company = hubspot.batch_get_deal_company_associations(deal_ids)
            companies_found = sum(1 for cid in deal_to_company.values() if cid)
            print(f"   Found {companies_found}/{len(deal_ids)} deals with company associations")

            # Step 2: Get unique company IDs
            unique_company_ids = list(set(cid for cid in deal_to_company.values() if cid))
            print(f"   Fetching employee counts for {len(unique_company_ids)} unique companies...")

            # Step 3: Batch fetch company properties
            company_properties = hubspot.batch_get_companies(
                unique_company_ids,
                properties=['name', 'numberofemployees']
            )
            print(f"   Retrieved properties for {len(company_properties)} companies")

            # API call estimate
            assoc_calls = (len(deal_ids) + 99) // 100
            company_calls = (len(unique_company_ids) + 99) // 100
            print(f"   API calls: {assoc_calls} association batches + {company_calls} company batches = {assoc_calls + company_calls} total")
            print(f"   (vs {len(deal_ids) * 2} individual calls = {100 - int(100 * (assoc_calls + company_calls) / (len(deal_ids) * 2))}% reduction)")
    else:  # history mode
        meeting_set_stages = []
        closed_stages = []

        if args.file:
            # Load from CSV export
            print(f"\n2. Loading deals from CSV: {args.file}...")
            try:
                import csv
                all_deals_api = []
                with open(args.file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Convert CSV row to deal object format
                        deal_obj = {
                            'id': row.get('Record ID') or row.get('deal_id'),
                            'properties': {
                                'dealname': row.get('Deal Name') or row.get('dealname', ''),
                                'pipeline': row.get('Pipeline') or row.get('pipeline', ''),
                                'dealstage': row.get('Deal Stage') or row.get('dealstage', ''),
                                'incremental_arr': row.get('Incremental ARR') or row.get('amount', '0'),
                                'closedate': row.get('Close Date') or row.get('closedate', ''),
                                'createdate': row.get('Create Date') or row.get('createdate', ''),
                                'hubspot_owner_id': row.get('Deal owner') or row.get('hubspot_owner_id', ''),
                                'hs_object_id': row.get('Record ID') or row.get('deal_id'),
                            }
                        }
                        all_deals_api.append(deal_obj)
                print(f"   Loaded {len(all_deals_api)} deals from CSV")
            except Exception as e:
                print(f"❌ Failed to load CSV: {e}")
                print("   Make sure CSV has columns: Record ID, Deal Name, Pipeline, Deal Stage, Close Date, Create Date")
                return
        else:
            # Fetch ALL deals including closed from API
            print("\n2. Fetching ALL deals (including closed) from HubSpot API...")
            print("   Note: For large datasets, use --file with a CSV export instead")
            try:
                # Use search API without stage filters
                all_deals_api = hubspot.get_all_deals_including_closed()
                print(f"   Fetched {len(all_deals_api)} deals (active + closed)")
            except Exception as e:
                print(f"❌ Failed to fetch deals: {e}")
                print("   Try exporting from HubSpot and using --file instead")
                return

    # Process deals
    print_step = "\n5" if args.mode == 'analytics' else "\n4"
    print(f"{print_step}. Processing deals and fetching company info...")
    deals = {}
    skipped = {
        'renewal_pipeline': 0,
        'meeting_set': 0,
        'disqualified': 0,
        'no_company': 0,
        'no_slug': 0
    }

    for i, deal_obj in enumerate(all_deals_api, 1):
        if i % 50 == 0:
            print(f"   Processed {i}/{len(all_deals_api)} deals...")

        deal_id = deal_obj.get('id')
        props = deal_obj.get('properties', {})

        deal_name = props.get('dealname', '')
        pipeline = props.get('pipeline') or ''
        stage = props.get('dealstage') or ''
        arr = props.get('incremental_arr') or props.get('amount', '0')
        close_date = props.get('closedate', '')
        create_date = props.get('createdate', '')
        owner_id = props.get('hubspot_owner_id', '')

        if not deal_id:
            continue

        # Apply filters based on mode
        if args.mode == 'active':
            # Active mode: apply stage filters
            # Filter: exclude Renewal pipeline (by ID or name)
            if pipeline in excluded['excluded_pipelines'] or any(excl in pipeline.lower() for excl in excluded['excluded_pipelines'] if excl.isalpha()):
                skipped['renewal_pipeline'] += 1
                continue

            # Filter: exclude Disqualified stage
            if stage in excluded['disqualified']:
                skipped['disqualified'] += 1
                continue

            # Filter: exclude Meeting Set stages
            if stage in meeting_set_stages:
                skipped['meeting_set'] += 1
                continue
        elif args.mode == 'analytics':
            # Analytics mode: include ALL pipelines and stages (no exclusions)
            # Renewal pipeline is now included for GRR/NRR metrics
            pass
        # history mode: include everything, no filters

        # Get company - use batch data in analytics mode, individual calls otherwise
        if args.mode == 'analytics':
            # Use pre-fetched batch data
            company_id = deal_to_company.get(deal_id)
            company_props = company_properties.get(company_id, {}) if company_id else {}
            company_name = company_props.get('name', '') if company_id else ''

            # Don't skip deals without companies - they'll get segment='Unknown'
            # and we'll track the reason in segment_reason field

        else:
            # Active/history mode: individual API calls
            try:
                company_obj = hubspot.get_deal_company(deal_id)
                if not company_obj:
                    skipped['no_company'] += 1
                    continue

                company_name = company_obj.get('properties', {}).get('name', '')
                if not company_name.strip():
                    skipped['no_company'] += 1
                    continue

            except Exception as e:
                skipped['no_company'] += 1
                continue

        # Generate slug (handle missing company name)
        slug = slugify(company_name) if company_name else 'unknown'

        # Build deal object with mode-specific fields
        deal_dict = {
            'deal_id': deal_id,
            'deal_name': deal_name,
            'company_name': company_name,
            'company_slug': slug,
            'pipeline': pipeline,
            'stage': stage,
            'arr': arr,
            'close_date': close_date,
            'owner_id': owner_id,
            'last_modified': datetime.now().isoformat(),
        }

        # Add history-specific fields
        if args.mode == 'history':
            deal_status = get_deal_status(stage)
            deal_dict['deal_status'] = deal_status
            deal_dict['create_date'] = create_date

            # Calculate days_to_close for closed deals
            if deal_status in ('won', 'lost'):
                days = calculate_days_to_close(create_date, close_date)
                deal_dict['days_to_close'] = days

        # Add analytics-specific fields
        if args.mode == 'analytics':
            from utils import (is_won_stage, is_lost_stage, get_stage_order,
                             get_pipeline_config, compute_deal_value, load_client_config,
                             get_segment)

            # Determine deal_status using pipeline config
            if is_won_stage(stage):
                deal_status = 'won'
            elif is_lost_stage(stage):
                deal_status = 'lost'
            else:
                deal_status = 'active'

            # Compute deal value using NULL-safe ARR component sum
            config = load_client_config()
            deal_value = compute_deal_value(props, config)

            # Compute segmentation from company employee count
            company_employee_count = None
            segment = 'Unknown'
            segment_reason = None

            if not company_id:
                # No company association at all
                segment_reason = 'no_company'
            elif company_id:
                emp_raw = company_props.get('numberofemployees')
                try:
                    if emp_raw and emp_raw != '':
                        # Handle decimal strings from CSV (e.g., "8521.0")
                        company_employee_count = int(float(emp_raw))
                except (ValueError, TypeError):
                    pass

                if company_employee_count is None:
                    # Has company but no employee count
                    segment_reason = 'no_employee_count'

            # Get segment from employee count
            segment, expected_cycle_days = get_segment(company_employee_count, config)

            # Parse ARR components (NULL-safe)
            def safe_numeric(val):
                if val in (None, '', 'null'):
                    return None
                try:
                    return float(str(val).replace('$', '').replace(',', '').strip())
                except (ValueError, TypeError):
                    return None

            new_arr = safe_numeric(props.get('new_revenue'))
            expansion_arr = safe_numeric(props.get('expansion_revenue'))
            prior_arr = safe_numeric(props.get('prior_arr'))

            # Parse SAO (boolean)
            sao_raw = props.get('sao')
            if isinstance(sao_raw, bool):
                sao = sao_raw
            elif isinstance(sao_raw, str):
                sao = sao_raw.lower() in ('true', '1', 'yes')
            else:
                sao = None

            # Forecast category (string)
            forecast_category = props.get('hs_manual_forecast_category')

            deal_dict['deal_status'] = deal_status
            deal_dict['create_date'] = create_date
            deal_dict['pipeline_id'] = pipeline if pipeline else 'default'
            deal_dict['stage'] = stage
            deal_dict['deal_value'] = deal_value
            deal_dict['new_arr'] = new_arr
            deal_dict['expansion_arr'] = expansion_arr
            deal_dict['prior_arr'] = prior_arr
            deal_dict['sao'] = sao
            deal_dict['forecast_category'] = forecast_category

            # Segmentation fields
            deal_dict['company_id'] = company_id
            deal_dict['company_employee_count'] = company_employee_count
            deal_dict['segment'] = segment
            deal_dict['segment_reason'] = segment_reason  # Diagnostic: 'no_company' or 'no_employee_count'

            # Get current stage order
            current_order = get_stage_order(stage) or 0
            deal_dict['current_stage_order'] = current_order

            # highest_stage_order_reached will be computed during Supabase write
            # by comparing current_order with existing value

            # Capture lost_reason if deal is lost
            if deal_status == 'lost':
                pipeline_config = get_pipeline_config()
                lost_reason_field = pipeline_config.get('lost_reason_field', 'closed_lost_reason')
                deal_dict['lost_reason'] = props.get(lost_reason_field, '')

            deal_dict['stage_source'] = 'prospective'

        deals[deal_id] = deal_dict

    # In active mode, write memory/deals/index.json. In history/analytics mode, skip (Supabase only).
    if args.mode == 'active':
        # Build index
        print(f"\n5. Building index...")
        index = {
            'last_etl_date': datetime.now().isoformat(),
            'total_deals': len(deals),
            'excluded_closed_stages': closed_stages,
            'excluded_meeting_set_stages': meeting_set_stages,
            'excluded_disqualified_stages': excluded['disqualified'],
            'excluded_renewal_pipeline': excluded['excluded_pipelines'],
            'deals': deals,
        }

        out = DEALS_DIR / 'index.json'
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

        print(f'\n✓ Deal index built: {len(deals)} active deals')
        print(f'  Skipped breakdown:')
        print(f'    {skipped["renewal_pipeline"]} Renewal pipeline')
        print(f'    {skipped["disqualified"]} Disqualified')
        print(f'    {skipped["meeting_set"]} Meeting Set stage')
        print(f'    {skipped["no_company"]} No company')
        print(f'    {skipped["no_slug"]} Invalid slug')
        print(f'  Output: {out}')
    elif args.mode == 'analytics':
        print(f"\n5. Analytics mode: {len(deals)} deals fetched")
        # Count by status
        status_counts = {'active': 0, 'won': 0, 'lost': 0}
        qualified_count = 0
        unmapped_stages = set()
        from utils import get_stage_order, get_pipeline_config

        pipeline_config = get_pipeline_config()
        qualified_order = pipeline_config.get('qualified_stage_order', 3)

        for d in deals.values():
            status = d.get('deal_status', 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1

            # Count qualified deals
            current_order = d.get('current_stage_order', 0)
            if current_order >= qualified_order:
                qualified_count += 1

            # Track unmapped stages
            if current_order == 0 and d.get('stage_id'):
                unmapped_stages.add(d.get('stage_id'))

        print(f'  {status_counts.get("active", 0)} active, '
              f'{status_counts.get("won", 0)} won, '
              f'{status_counts.get("lost", 0)} lost')
        print(f'  {qualified_count} qualified (stage order >= {qualified_order})')
        if unmapped_stages:
            print(f'  ⚠️  {len(unmapped_stages)} stage IDs not in config: {sorted(unmapped_stages)}')
        if len(deals) > 0:
            print(f'  Qualification rate: {qualified_count}/{len(deals)} '
                  f'({100*qualified_count/len(deals):.1f}%)')
        else:
            print(f'  ⚠️  No deals processed - check skipped breakdown')
    else:  # history mode
        print(f"\n5. Processed {len(deals)} deals (active + closed)")
        # Count by status
        status_counts = {}
        for d in deals.values():
            status = d.get('deal_status', 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
        print(f'  Status breakdown:')
        for status, count in sorted(status_counts.items()):
            print(f'    {status}: {count} deals')

    # Write to Supabase if configured
    if os.getenv('SUPABASE_URL'):
        print(f'\n6. Writing to Supabase...')
        try:
            sys.path.insert(0, str(REPO_ROOT / 'scripts'))
            from supabase_client import SupabaseWriter
            sb = SupabaseWriter()
            count = 0
            for deal_id, deal in deals.items():
                try:
                    sb.upsert_deal(deal)
                    count += 1
                except Exception as e:
                    print(f'  ⚠️  Supabase upsert failed for '
                          f'{deal.get("company_name")}: {e}')
            print(f'  ✓ Supabase: {count} deals upserted')
        except Exception as e:
            print(f'  ⚠️  Supabase write failed: {e}')
    else:
        print(f'\n  ⏭️  SUPABASE_URL not set — skipping Supabase write')

    # Print first 10 for verification
    print('\nFirst 10 active deals:')
    for i, (did, d) in enumerate(list(deals.items())[:10], 1):
        print(f'  [{i}] {d["company_name"]} | {d["stage"]} | '
              f'{d["pipeline"]} | ${d["arr"]}')

    # Print unique stages
    stages = sorted(set(d['stage'] for d in deals.values()))
    print(f'\nStages in index ({len(stages)} total):')
    for s in stages:
        count = sum(1 for d in deals.values() if d['stage'] == s)
        print(f'  {s}: {count} deals')

    print("\n" + "=" * 80)
    print("✓ ETL Complete")
    print("=" * 80)


if __name__ == '__main__':
    main()
