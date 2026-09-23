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
import time
import argparse
from pathlib import Path
from datetime import datetime
import re

# Add parent directory to path for imports
REPO_ROOT = Path(__file__).parent.parent
DEALS_DIR = REPO_ROOT / 'memory' / 'deals'
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'api'))

from utils import slugify
# Import field_semantics for canonical stage logic
try:
    from field_semantics import is_won, is_lost, STAGE_MAP, label_to_stage_id
except ImportError:
    from api.field_semantics import is_won, is_lost, STAGE_MAP, label_to_stage_id

def _get_won_stage_ids():
    """Get all stage IDs (including aliases) that mean closed won."""
    won_ids = []
    for stage_id, info in STAGE_MAP.items():
        if info.get('bucket') == 'closed_won':
            won_ids.append(stage_id)
            won_ids.extend(info.get('aliases', []))
    return won_ids

def _get_lost_stage_ids():
    """Get all stage IDs (including aliases) that mean closed lost."""
    lost_ids = []
    for stage_id, info in STAGE_MAP.items():
        if info.get('bucket') == 'closed_lost':
            lost_ids.append(stage_id)
            lost_ids.extend(info.get('aliases', []))
    return lost_ids

DEALS_DIR.mkdir(parents=True, exist_ok=True)

# Exclude Renewal Pipeline (both by name and ID)
EXCLUDED_PIPELINES = ['renewal', '866608541']

# Disqualified stages now discovered from HubSpot metadata (no hardcoded fallback)
# See field_semantics.yaml for stage aliases

# NOTE: Closed stage logic now sourced from field_semantics (handles aliases automatically)
# CLOSED_WON_STAGES and CLOSED_LOST_STAGES removed - use is_won/is_lost instead
# _get_meeting_set_stage_ids() removed - use _get_meeting_set_stage_ids() instead

def _get_meeting_set_stage_ids():
    """Get all stage IDs that mean 'Meeting Set' (sourced from field_semantics)."""
    # 'Meeting Set' is stage ID 79653122, defined in field_semantics.yaml
    meeting_set_id = label_to_stage_id('Meeting Set')
    return [meeting_set_id] if meeting_set_id != 'Meeting Set' else []

def get_deal_status(stage: str) -> str:
    """
    Determine deal status for history mode.
    Uses field_semantics for canonical stage logic (handles numeric aliases).
    """
    if is_won(stage):
        return 'won'
    if is_lost(stage):
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
        'closed_won': closed_won or _get_won_stage_ids(),
        'closed_lost': closed_lost or _get_lost_stage_ids(),
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
        'closed_won': get_ids('closed_won') or _get_won_stage_ids(),
        'closed_lost': get_ids('closed_lost') or _get_lost_stage_ids(),
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
                'meeting_set': _get_meeting_set_stage_ids(),
                'disqualified': [],  # Discovered from HubSpot; no hardcoded fallback
                'closed_won': _get_won_stage_ids(),
                'closed_lost': _get_lost_stage_ids(),
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
            'meeting_set': _get_meeting_set_stage_ids(),
            'disqualified': [],  # Discovered from HubSpot; no hardcoded fallback
            'closed_won': _get_won_stage_ids(),
            'closed_lost': _get_lost_stage_ids(),
            'excluded_pipelines': EXCLUDED_PIPELINES,
        }

    except Exception as e:
        print(f"  ⚠️  Could not load client.yaml: {e}")
        return {
            'meeting_set': _get_meeting_set_stage_ids(),
            'disqualified': [],  # Discovered from HubSpot; no hardcoded fallback
            'closed_won': _get_won_stage_ids(),
            'closed_lost': _get_lost_stage_ids(),
            'excluded_pipelines': EXCLUDED_PIPELINES,
        }


def get_meeting_set_stages(hubspot):
    """
    Fetch pipeline stages and auto-detect Meeting Set stages.
    Returns list of stage IDs.
    """
    # Start with hardcoded Meeting Set stages
    meeting_set_stages = list(_get_meeting_set_stage_ids())

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
        return _get_meeting_set_stage_ids()


def fetch_owner_emails(hubspot):
    """
    Fetch all HubSpot owners and return mapping of owner_id -> email.
    Fetches both active and archived owners (archived owners are needed for
    historical SDR attribution when deals were sourced by former team members).
    Returns dict like {"12345": "rep@company.com", ...}
    """
    owner_map = {}

    # Fetch active owners first
    try:
        endpoint = "/crm/v3/owners"
        params = {"limit": 100}

        while True:
            response = hubspot._get(endpoint, params=params)
            results = response.get('results', [])

            for owner in results:
                owner_id = str(owner.get('id', ''))
                email = owner.get('email', '')
                if owner_id and email:
                    owner_map[owner_id] = email

            # Check for pagination
            paging = response.get('paging', {})
            next_link = paging.get('next', {}).get('after')
            if not next_link:
                break
            params['after'] = next_link
            # Rate limiting: small delay between pagination calls
            time.sleep(0.2)

        active_count = len(owner_map)

    except Exception as e:
        # Fatal: an empty owner map would write owner_email='' over every
        # deal's stored owner. Retries (hubspot_deals._request) already ran.
        print(f"❌ Could not fetch active owners: {e}")
        raise

    # Fetch archived owners (for historical SDR attribution)
    try:
        endpoint = "/crm/v3/owners"
        params = {"limit": 100, "archived": "true"}

        while True:
            response = hubspot._get(endpoint, params=params)
            results = response.get('results', [])

            for owner in results:
                owner_id = str(owner.get('id', ''))
                email = owner.get('email', '')
                if owner_id and email:
                    owner_map[owner_id] = email

            # Check for pagination
            paging = response.get('paging', {})
            next_link = paging.get('next', {}).get('after')
            if not next_link:
                break
            params['after'] = next_link
            # Rate limiting: small delay between pagination calls
            time.sleep(0.2)

        archived_count = len(owner_map) - active_count
        print(f"   Fetched {active_count} active + {archived_count} archived = {len(owner_map)} total owners")

    except Exception as e:
        # Fatal for the same reason: deals sourced by former team members
        # would get sdr_owner_email=None written over their attribution.
        print(f"❌ Could not fetch archived owners: {e}")
        raise

    return owner_map


def main():
    parser = argparse.ArgumentParser(description="ETL HubSpot deals to memory/Supabase")
    parser.add_argument(
        '--mode',
        type=str,
        choices=['active', 'history', 'analytics', 'incremental'],
        default='active',
        help=('active (default): active deals for MEDDICC agent\n'
              'history: all deals including closed (Supabase only)\n'
              'analytics: ALL deals all stages (Supabase only, '
              'for snapshot/waterfall/qualification-rate); also sets the '
              'incremental checkpoint on success\n'
              'incremental: only deals modified since the checkpoint minus '
              '30 min, same fields as analytics (Supabase only)')
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
    if args.file and args.mode in ('active', 'incremental'):
        print("ERROR: --file can only be used with --mode history or --mode analytics")
        print("       Active mode fetches live data from HubSpot API")
        return 2

    print("=" * 80)
    print(f"HUBSPOT DEALS ETL - MODE: {args.mode.upper()}")
    print("=" * 80)

    # Load stage exclusions from config
    excluded = get_excluded_stages()

    # Initialize HubSpot client (skip if using CSV mode)
    hubspot = None
    owner_emails = {}
    if not args.file:
        print("\n1. Connecting to HubSpot API...")
        try:
            from hubspot_deals import get_hubspot_deals_client
            hubspot = get_hubspot_deals_client()
            # Fetch owner emails for mapping owner_id -> email
            print("\n1b. Fetching owner emails...")
            owner_emails = fetch_owner_emails(hubspot)
        except Exception as e:
            print(f"❌ Failed to initialize HubSpot client or fetch owners: {e}")
            print("\nMake sure HUBSPOT_API_KEY environment variable is set.")
            return 1
    else:
        print("\n1. CSV Mode - skipping HubSpot API connection")

    # Incremental-sync checkpoint (scripts/deal_sync.py). Used by analytics
    # (sets it) and incremental (reads and advances it); None elsewhere.
    checkpoint_store = checkpoint_before = fetch_start_ms = None
    company_pass_status = 'not used in this mode'
    if args.mode in FULL_FIELD_MODES and not args.file and os.getenv('SUPABASE_URL'):
        from deal_sync import CheckpointStore, JOB_DEALS
        try:
            sys.path.insert(0, str(REPO_ROOT / 'scripts'))
            from supabase_client import SupabaseWriter
            checkpoint_store = CheckpointStore(SupabaseWriter().client)
            checkpoint_before = checkpoint_store.get(JOB_DEALS)
        except Exception as e:
            if args.mode == 'incremental':
                print(f"❌ Could not read the sync checkpoint: {e}")
                return 1
            print(f"⚠️  Could not read the sync checkpoint ({e}); "
                  f"this run won't update it")
            checkpoint_store = None

    # Determine which deals to fetch based on mode
    if args.mode == 'incremental':
        meeting_set_stages = []
        closed_stages = []
        if checkpoint_store is None:
            print("❌ Incremental mode writes Supabase and needs its checkpoint: "
                  "SUPABASE_URL is not set")
            return 1
        from deal_sync import SyncBlocked, fetch_incremental
        print("\n2. Fetching deals modified since the checkpoint (keyset-paged)...")
        try:
            fetched = fetch_incremental(hubspot, checkpoint_store)
            all_deals_api = fetched['deals']
            checkpoint_before = fetched['checkpoint']
            window_start_ms = fetched['window_start_ms']
            fetch_start_ms = fetched['fetch_start_ms']
            company_pass_status = fetched['company_status']
        except SyncBlocked as e:
            print(f"❌ {e}")
            return 1
        except Exception as e:
            print(f"❌ Failed to fetch deals: {e}")
            return 1
        print(f"   Checkpoint {checkpoint_before} ({_ms_iso(checkpoint_before)}); "
              f"window from {window_start_ms} ({_ms_iso(window_start_ms)})")
        print(f"   Fetched {len(all_deals_api)} deals (company pass: {company_pass_status})")
    elif args.mode == 'active':
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
            return 1
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
                    domain = deal.get('company_domain', '')

                    deal_to_company[deal_id] = company_id
                    if company_id:
                        company_properties[company_id] = {
                            'name': company_name,
                            'numberofemployees': employee_count,
                            'domain': domain
                        }

                print(f"\n  CSV Mode: {len(all_deals_api)} deals loaded with pre-joined company data")

            except Exception as e:
                print(f"❌ Failed to load CSV: {e}")
                import traceback
                traceback.print_exc()
                return 1

        else:
            # Fetch from HubSpot API
            print("\n2. Fetching ALL deals from HubSpot API (analytics mode)...")
            try:
                fetch_start_ms = int(time.time() * 1000)
                all_deals_api = hubspot.get_all_deals_including_closed()
                print(f"   Fetched {len(all_deals_api)} deals (all stages)")
            except Exception as e:
                print(f"❌ Failed to fetch deals: {e}")
                return 1
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
                return 1
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
                return 1

    # Batch fetch company associations for all modes (except CSV mode which already has it)
    # This runs for both active and analytics API modes
    if not args.file:
        batch_step = "\n4" if args.mode == 'active' else "\n3"
        print(f"{batch_step}. Batch fetching company associations and employee counts...")
        deal_ids = [d.get('id') for d in all_deals_api if d.get('id')]
        print(f"   Fetching company associations for {len(deal_ids)} deals...")

        # Step 1: Batch get company IDs for all deals
        deal_to_company = hubspot.batch_get_deal_company_associations(deal_ids)
        companies_found = sum(1 for cid in deal_to_company.values() if cid)
        print(f"   Found {companies_found}/{len(deal_ids)} deals with company associations")

        # Step 2: Get unique company IDs
        unique_company_ids = list(set(cid for cid in deal_to_company.values() if cid))
        print(f"   Fetching properties for {len(unique_company_ids)} unique companies...")

        # Step 3: Batch fetch company properties (including domain)
        company_properties = hubspot.batch_get_companies(
            unique_company_ids,
            properties=['name', 'numberofemployees', 'domain']
        )
        print(f"   Retrieved properties for {len(company_properties)} companies")

        # API call estimate
        assoc_calls = (len(deal_ids) + 99) // 100
        company_calls = (len(unique_company_ids) + 99) // 100
        print(f"   API calls: {assoc_calls} association batches + {company_calls} company batches = {assoc_calls + company_calls} total")
        if deal_ids:  # 0 deals is normal for an incremental run with no changes
            print(f"   (vs {len(deal_ids) * 2} individual calls = {100 - int(100 * (assoc_calls + company_calls) / (len(deal_ids) * 2))}% reduction)")

    # Process deals
    print_step = "\n5" if args.mode == 'analytics' else "\n5"
    print(f"{print_step}. Processing deals and writing to Supabase...")
    deals = {}
    skipped = {
        'renewal_pipeline': 0,
        'meeting_set': 0,
        'disqualified': 0,
        'no_company': 0,
        'no_slug': 0
    }
    unmapped_bdr_owners = set()  # Track bdr_owner IDs that fail to map
    company_unknown = set()  # deal_ids whose company batch read failed (see below)
    bdr_owner_stats = {'total': 0, 'email': 0, 'mapped': 0, 'unmapped': 0}  # Track bdr_owner processing

    for i, deal_obj in enumerate(all_deals_api, 1):
        if i % 50 == 0:
            print(f"   Processed {i}/{len(all_deals_api)} deals...")

        deal_id = deal_obj.get('id')
        props = deal_obj.get('properties', {})

        deal_name = props.get('dealname', '')
        pipeline = props.get('pipeline') or ''
        stage = props.get('dealstage') or ''

        # Normalize display names to stage IDs (HubSpot CSV exports return display names)
        # Uses field_semantics.label_to_stage_id() for centralized mapping
        stage = label_to_stage_id(stage)

        arr = props.get('incremental_arr') or props.get('amount', '0')
        close_date = props.get('closedate', '')
        create_date = props.get('createdate', '')
        owner_id = props.get('hubspot_owner_id', '')
        # Look up owner email from mapping
        owner = owner_emails.get(str(owner_id), '') if owner_id else ''

        # SDR/BDR attribution field - may be email or owner_id
        bdr_owner_value = props.get('bdr_owner', '')
        sdr_owner_email = None
        if bdr_owner_value:
            bdr_owner_stats['total'] += 1
            # Check if it's already an email (contains @)
            if '@' in str(bdr_owner_value):
                sdr_owner_email = bdr_owner_value
                bdr_owner_stats['email'] += 1
            else:
                # Try looking it up as an owner_id
                sdr_owner_email = owner_emails.get(str(bdr_owner_value), '')
                if sdr_owner_email:
                    bdr_owner_stats['mapped'] += 1
                else:
                    # Track owner IDs that failed to map
                    bdr_owner_stats['unmapped'] += 1
                    unmapped_bdr_owners.add(str(bdr_owner_value))

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
        elif args.mode in FULL_FIELD_MODES:
            # Analytics/incremental: include ALL pipelines and stages (no exclusions)
            # Renewal pipeline is now included for GRR/NRR metrics
            pass
        # history mode: include everything, no filters

        # Get company - use pre-fetched batch data (available in both active and analytics modes now)
        company_id = deal_to_company.get(deal_id)
        company_props = company_properties.get(company_id, {}) if company_id else {}
        company_name = company_props.get('name', '') if company_id else ''
        company_domain = company_props.get('domain', '') if company_id else ''

        # Don't skip deals without companies in analytics mode
        # In active mode, we used to skip these, but now we include them for consistency
        # They'll get segment='Unknown' and we track the reason in segment_reason field

        # Generate slug (handle missing company name)
        slug = slugify(company_name) if company_name else 'unknown'

        # Compute segmentation from company employee count (needed for deal_dict)
        from utils import (is_won_stage, is_lost_stage, get_stage_order,
                         get_pipeline_config, compute_deal_value, load_client_config,
                         get_segment)

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
        config = load_client_config()
        segment, expected_cycle_days = get_segment(company_employee_count, config)

        # Build deal object with mode-specific fields
        deal_dict = {
            'deal_id': deal_id,
            'deal_name': deal_name,
            'company_name': company_name or None,  # None = don't overwrite; '' would clear existing data
            'company_slug': slug if company_name else None,
            'company_id': company_id,  # Now populated in all modes via batch fetch
            'company_domain': company_domain or None,  # Domain from HubSpot companies
            'company_employee_count': company_employee_count,
            'segment': segment,
            'segment_reason': segment_reason,  # Diagnostic: 'no_company' or 'no_employee_count'
            'pipeline': pipeline,
            'stage': stage,
            'arr': arr,
            'close_date': close_date,
            'owner': owner,  # Owner email (looked up from owner_id)
            'sdr_owner_email': sdr_owner_email or None,  # SDR/BDR who sourced the deal
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

            # Parse renewal_revenue for renewal pipeline deals (same as analytics mode)
            def safe_numeric(val):
                if val in (None, '', 'null'):
                    return None
                try:
                    return float(str(val).replace('$', '').replace(',', '').strip())
                except (ValueError, TypeError):
                    return None

            renewal_revenue = safe_numeric(props.get('renewal_revenue'))
            if renewal_revenue is not None:
                deal_dict['renewal_revenue'] = renewal_revenue

        # Add analytics-specific fields (incremental writes the same set)
        if args.mode in FULL_FIELD_MODES:
            # Determine deal_status using pipeline config
            if is_won_stage(stage):
                deal_status = 'won'
            elif is_lost_stage(stage):
                deal_status = 'lost'
            else:
                deal_status = 'active'

            # Incremental ARR, falling back to amount when every component
            # is blank, plus Renewal ARR for renewal-pipeline deals.
            # pipeline_id is required or renewals are valued as new business.
            deal_value = compute_deal_value(props, config, pipeline_id=pipeline)

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
            incremental_arr = safe_numeric(props.get('incremental_arr'))
            prior_arr = safe_numeric(props.get('prior_arr'))
            renewal_revenue = safe_numeric(props.get('renewal_revenue'))

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
            deal_dict['incremental_arr'] = incremental_arr
            deal_dict['prior_arr'] = prior_arr
            deal_dict['renewal_revenue'] = renewal_revenue
            deal_dict['sao'] = sao
            deal_dict['forecast_category'] = forecast_category

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

        if hubspot is not None and _company_lookup_failed(hubspot, deal_id, company_id):
            _drop_unknown_company_fields(deal_dict)
            company_unknown.add(deal_id)

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
        if company_unknown:
            index['deals'] = _with_previous_company_fields(deals, company_unknown, out)
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
    elif args.mode in FULL_FIELD_MODES:
        print(f"\n5. {args.mode.capitalize()} mode: {len(deals)} deals fetched")
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

    supabase_status = 'not configured (SUPABASE_URL unset) — skipped'
    upserted = upsert_failed = 0
    supabase_fatal = False
    # Write to Supabase if configured
    if os.getenv('SUPABASE_URL'):
        print(f'\n6. Writing to Supabase...')
        try:
            sys.path.insert(0, str(REPO_ROOT / 'scripts'))
            from supabase_client import SupabaseWriter
            sb = SupabaseWriter()
            for deal_id, deal in deals.items():
                try:
                    sb.upsert_deal(deal)
                    upserted += 1
                except Exception as e:
                    upsert_failed += 1
                    print(f'  ⚠️  Supabase upsert failed for '
                          f'{deal.get("company_name")}: {e}')
            print(f'  ✓ Supabase: {upserted} deals upserted')
            supabase_status = f'{upserted} upserted, {upsert_failed} failed'

            # Report BDR owner attribution stats
            print(f'  ℹ️  SDR attribution stats:')
            print(f'      Total deals with bdr_owner: {bdr_owner_stats["total"]}')
            print(f'      Already email format: {bdr_owner_stats["email"]}')
            print(f'      Mapped owner ID→email: {bdr_owner_stats["mapped"]}')
            print(f'      Failed to map: {bdr_owner_stats["unmapped"]}')

            # Report unmapped BDR owner IDs if any
            if unmapped_bdr_owners:
                print(f'  ⚠️  SDR attribution: {len(unmapped_bdr_owners)} bdr_owner IDs failed to map to email:')
                for owner_id in sorted(unmapped_bdr_owners)[:10]:  # Show first 10
                    print(f'      - Owner ID {owner_id} not found in fetched owners')
                if len(unmapped_bdr_owners) > 10:
                    print(f'      ... and {len(unmapped_bdr_owners) - 10} more')

        except Exception as e:
            print(f'  ❌ Supabase write failed: {e}')
            supabase_fatal = True
            supabase_status = f'FAILED before/while writing ({upserted} upserted): {e}'
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

    problems = _collect_problems(hubspot=hubspot, upsert_failed=upsert_failed,
                                 supabase_fatal=supabase_fatal)
    deletion_status = 'not used in this mode'
    if checkpoint_store is not None:
        deletion_status, deletion_problem = _apply_deletions(hubspot, checkpoint_store.sb)
        if deletion_problem:
            problems.append(deletion_problem)
    reconcile_status = 'not used in this mode'
    if checkpoint_store is not None and args.mode == 'analytics':
        if problems:
            reconcile_status = 'skipped: run had failures (orphans would be unreliable)'
        else:
            reconcile_status, reconcile_problem = _reconcile(
                hubspot, checkpoint_store.sb, {str(d.get('id')) for d in all_deals_api})
            if reconcile_problem:
                problems.append(reconcile_problem)
    checkpoint_status, checkpoint_problem = _update_checkpoint(
        checkpoint_store, checkpoint_before, all_deals_api, fetch_start_ms,
        problems, upserted)
    if checkpoint_problem:
        problems.append(checkpoint_problem)
    return _print_run_summary(
        mode=args.mode,
        fetched=len(all_deals_api),
        processed=len(deals),
        hubspot=hubspot,
        company_unknown=company_unknown,
        supabase_status=supabase_status,
        problems=problems,
        checkpoint_status=checkpoint_status,
        deletion_status=deletion_status,
        company_pass_status=company_pass_status,
        reconcile_status=reconcile_status,
    )


# ── partial-failure handling + run summary (2026-09-23) ─────────────────────
#
# Before this, every failure path printed a message and returned None, so the
# process exited 0 and every GitHub Actions run showed green whatever
# happened. A failed company-association batch was worse than silent: its
# deals were recorded as "no company" and written with company_id=None,
# segment='Unknown', segment_reason='no_company' over their good values.
#
# Policy, explicit:
#   fatal (exit 1, nothing written): HubSpot client/owner fetch, deal fetch,
#       CSV load, Supabase writer creation. Usage error: exit 2.
#   partial (exit 1, good data written): an association/company batch or
#       individual Supabase upserts still failing after retries. The affected
#       deals keep their stored company fields (never overwritten with
#       "unknown"); everything else about them is refreshed.

# Modes that fetch every deal field (ARR components, status, stage order)
# and write Supabase; incremental is analytics restricted to recent changes.
FULL_FIELD_MODES = ('analytics', 'incremental')

COMPANY_DERIVED_FIELDS = ('company_id', 'company_domain', 'company_employee_count',
                          'segment', 'segment_reason')


def _company_lookup_failed(hubspot, deal_id, company_id):
    """True if this deal's company data is unknown because a batch read failed
    after retries (as opposed to the deal genuinely having no company)."""
    return (str(deal_id) in hubspot.failed_association_deal_ids
            or (company_id is not None and str(company_id) in hubspot.failed_company_ids))


def _drop_unknown_company_fields(deal_dict):
    """Leave the stored company fields alone for this deal: company_name /
    company_slug set to None are preserved by SupabaseWriter.upsert_deal, and
    the other company-derived keys are omitted so the upsert doesn't send them."""
    deal_dict['company_name'] = None
    deal_dict['company_slug'] = None
    for k in COMPANY_DERIVED_FIELDS:
        deal_dict.pop(k, None)


def _with_previous_company_fields(deals, company_unknown, index_path):
    """The index is rewritten whole each run, so for deals whose company
    lookup failed, carry their company fields over from the previous index."""
    try:
        with open(index_path, encoding='utf-8') as f:
            previous = json.load(f).get('deals', {})
    except (OSError, ValueError):
        previous = {}
    merged = {}
    for did, d in deals.items():
        if did in company_unknown and did in previous:
            d = dict(d)
            for k in ('company_name', 'company_slug') + COMPANY_DERIVED_FIELDS:
                if k in previous[did]:
                    d[k] = previous[did][k]
        merged[did] = d
    return merged


def _collect_problems(*, hubspot, upsert_failed, supabase_fatal):
    """Everything that failed after retries this run ([] = clean)."""
    problems = []
    assoc_failed = len(hubspot.failed_association_deal_ids) if hubspot else 0
    company_failed = len(hubspot.failed_company_ids) if hubspot else 0
    if assoc_failed:
        problems.append(f'{assoc_failed} deals: company-association batch failed')
    if company_failed:
        problems.append(f'{company_failed} companies: company batch read failed')
    if upsert_failed:
        problems.append(f'{upsert_failed} Supabase upserts failed')
    if supabase_fatal:
        problems.append('Supabase write aborted')
    return problems


def _checkpoint_may_advance(problems):
    """The whole rule: only a run with no failures may move the checkpoint.
    Advancing past a failed write is the transcript-ETL bug (its cutoff moved
    on data written before the real write failed, and those calls were
    never retried)."""
    return not problems


def _ms_iso(ms):
    if ms is None:
        return 'none'
    return datetime.utcfromtimestamp(ms / 1000).strftime('%Y-%m-%d %H:%M:%S UTC')


def _update_checkpoint(store, stored, fetched_deals, fetch_start_ms, problems, upserted):
    """(status line, problem or None). Advances only after a clean run, to
    deal_sync.next_watermark(); a failed write is a problem (exit 1), and the
    next run just re-reads the same window."""
    if store is None:
        return 'not used in this mode', None
    if not _checkpoint_may_advance(problems):
        return f'unchanged at {stored} ({_ms_iso(stored)}): run had failures', None
    from deal_sync import JOB_DEALS, next_watermark
    new = next_watermark(stored, fetched_deals, fetch_start_ms)
    if new is None or new == stored:
        return f'unchanged at {stored} ({_ms_iso(stored)}): nothing newer', None
    try:
        store.advance(JOB_DEALS, new, run_id=os.getenv('GITHUB_RUN_ID', 'local'),
                      fetched=len(fetched_deals), upserted=upserted)
    except Exception as e:
        return (f'unchanged at {stored} ({_ms_iso(stored)})',
                f'checkpoint write failed: {e}')
    return f'advanced {stored} ({_ms_iso(stored)}) → {new} ({_ms_iso(new)})', None


def _apply_deletions(hubspot, sb):
    """Tombstone every deal HubSpot has deleted or merged away that is still
    in `deals` (migration 070 tombstone_deal(), atomic per deal; reuses the
    067 deleted_deals table). (status line, problem or None): any failure is
    a run failure, so the checkpoint isn't advanced past it."""
    source = f"deal_sync_{os.getenv('GITHUB_RUN_ID', 'local')}"
    try:
        archived = hubspot.list_archived_deals()
        merged = hubspot.merged_away_deal_ids()
    except Exception as e:
        return 'failed listing HubSpot deletions', f'deletion check failed: {e}'
    candidates = [(a['id'], a.get('archivedAt'), 'deleted_in_hubspot', source)
                  for a in archived]
    candidates += [(mid, None, 'merged_away', f'{source} (merged into {survivor})')
                   for mid, survivor in merged]
    tombstoned = []
    try:
        for deal_id, archived_at, reason, src in candidates:
            result = sb.rpc('tombstone_deal', {
                'p_deal_id': deal_id, 'p_archived_at': archived_at,
                'p_reason': reason, 'p_source': src}).execute().data
            if result == 'tombstoned':
                tombstoned.append(f'{deal_id} ({reason})')
    except Exception as e:
        return (f'{len(tombstoned)} tombstoned before failure',
                f'tombstone_deal failed: {e}')
    status = (f'{len(tombstoned)} tombstoned'
              + (f': {", ".join(tombstoned)}' if tombstoned else '')
              + f' (checked {len(archived)} deleted + {len(merged)} merged-away ids)')
    return status, None


# More orphans than this in one full sync means the HubSpot listing itself is
# suspect (partial response, filter/permission problem), not that this many
# deals were purged. Tombstone nothing and fail the run: a bad listing must
# never turn into a mass deletion.
MAX_RECONCILE_ORPHANS = 25


def _reconcile(hubspot, sb, fetched_ids):
    """Full-sync safety net: deals in Supabase that the complete HubSpot
    listing didn't return, after the deletion pass. Each one is looked up
    directly:
      404 -> purged from HubSpot (gone from the recycle bin too): tombstone it
             as purged_from_hubspot. The deletion date is unknown, so its
             snapshots stay.
      200 with a different id -> merged into that survivor: tombstone as
             merged_away.
      200, same id -> exists but missing from the listing: a real gap, so
             report it (exit 1) and don't touch it.
    (status line, problem or None)."""
    import requests
    from supabase_client import select_all
    source = f"deal_sync_reconcile_{os.getenv('GITHUB_RUN_ID', 'local')}"
    try:
        supa_ids = {str(r['deal_id']) for r in select_all(sb, 'deals', 'deal_id')}
    except Exception as e:
        return 'failed reading Supabase deal ids', f'reconciliation failed: {e}'
    orphans = sorted(supa_ids - set(fetched_ids))
    if not orphans:
        return f'clean: Supabase {len(supa_ids)} deals, all in the HubSpot listing', None
    if len(orphans) > MAX_RECONCILE_ORPHANS:
        return (f'{len(orphans)} orphans (> {MAX_RECONCILE_ORPHANS}): listing suspect, nothing touched',
                f'reconciliation found {len(orphans)} deals missing from the HubSpot listing '
                f'(> {MAX_RECONCILE_ORPHANS}); treated as a bad listing, nothing tombstoned: '
                f'{", ".join(orphans[:10])}{" ..." if len(orphans) > 10 else ""}')
    purged, merged, missing = [], [], []
    try:
        for did in orphans:
            try:
                record = hubspot._get(f"/crm/v3/objects/deals/{did}",
                                      params={'properties': 'hs_object_id'})
            except requests.HTTPError as e:
                if getattr(e.response, 'status_code', None) != 404:
                    raise
                sb.rpc('tombstone_deal', {'p_deal_id': did, 'p_archived_at': None,
                                          'p_reason': 'purged_from_hubspot',
                                          'p_source': source}).execute()
                purged.append(did)
                continue
            survivor = str(record.get('id'))
            if survivor and survivor != did:
                sb.rpc('tombstone_deal', {'p_deal_id': did, 'p_archived_at': None,
                                          'p_reason': 'merged_away',
                                          'p_source': f'{source} (merged into {survivor})'}).execute()
                merged.append(did)
            else:
                missing.append(did)
    except Exception as e:
        return (f'{len(purged)} purged, {len(merged)} merged before failure',
                f'reconciliation failed: {e}')
    status = (f'Supabase {len(supa_ids)} vs listing {len(fetched_ids)}: '
              f'{len(purged)} purged{": " + ", ".join(purged) if purged else ""}, '
              f'{len(merged)} merged{": " + ", ".join(merged) if merged else ""}, '
              f'{len(missing)} missing from the full listing'
              f'{": " + ", ".join(missing) if missing else ""}')
    problem = (f'{len(missing)} deals exist in HubSpot but were missing from the full listing: '
               f'{", ".join(missing)}') if missing else None
    return status, problem


def _print_run_summary(*, mode, fetched, processed, hubspot, company_unknown,
                       supabase_status, problems, checkpoint_status,
                       deletion_status='not used in this mode',
                       company_pass_status='not used in this mode',
                       reconcile_status='not used in this mode'):
    """Counts of what succeeded and failed, then the exit code: 0 only when
    nothing failed after retries."""
    retries = hubspot.retry_count if hubspot else 0
    print("\n" + "=" * 80)
    print(f"RUN SUMMARY ({mode} mode)")
    print(f"  Deals fetched from HubSpot:        {fetched}")
    print(f"  Deals processed:                   {processed}")
    print(f"  Company data unknown (preserved):  {len(company_unknown)}")
    print(f"  Supabase:                          {supabase_status}")
    print(f"  HubSpot request retries taken:     {retries}")
    print(f"  Company pass:                      {company_pass_status}")
    print(f"  Deletions:                         {deletion_status}")
    print(f"  Reconciliation:                    {reconcile_status}")
    print(f"  Checkpoint:                        {checkpoint_status}")
    if problems:
        print("❌ ETL finished with failures (exit 1):")
        for p in problems:
            print(f"   - {p}")
    else:
        print("✓ ETL Complete — no failures")
    print("=" * 80)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
