"""
Historical Snapshot Backfill — Method 2, Phase 4.

Reconstructs weekly pipeline snapshots for elapsed quarters from HubSpot
property history and writes them to deals_snapshot.

POPULATION comes from point_in_time.reconstruct_open_rows — the SAME function
the Phase 3 dry-run calls. Neither reimplements population selection, so the
writer and the dry-run cannot diverge on who is in a snapshot. Driving the
population from the deals table (not property_history.keys()) and writing a
null-stage row instead of dropping it is the Phase 2a fix: iterating history
keys and dropping null-stage deals was the ~291 cap.

VALUE and CLOSE_DATE are reconstructed point-in-time (Phase 2b). deal_value is
None, never 0.0, when no component resolved at the date — writing a 0 would
swap a proxy for a fabrication.

WEEKLY SAMPLING drops a fast-mover's intermediate stages: a deal that moves
through four stages in four days appears in the weekly grid as though it
jumped straight to its final stage. Inherent to weekly sampling, not a bug;
stage-to-stage conversion computed from this grid undercounts fast deals.

The write is BATCHED, RESUMABLE and IDEMPOTENT: a durable checkpoint records
each (quarter, week) done, restart skips them, and the upsert key
(deal_id, snapshot_date) makes re-running a completed date a no-op. Ordering
is deterministic (quarters in order, weeks in order, deal_id ascending) so a
resumed run reproduces the same sequence.

Requires: property history cache (hubspot_history.py --all), migration 038
(NOT NULL fiscal_quarter).

Usage:
    python scripts/analytics/backfill_snapshots.py --report-only   # numbers, no write
    python scripts/analytics/backfill_snapshots.py                 # write
    python scripts/analytics/backfill_snapshots.py --quarters "FY2026 Q3,FY2026 Q4"
"""
import os
import sys
import json
import yaml
import argparse
from collections import Counter
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'api'))

try:
    from field_semantics import is_won, is_lost
except ImportError:
    from api.field_semantics import is_won, is_lost

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from supabase import create_client
from supabase_client import select_all

# Shared reconstruction — population, value, close_date live in one module.
from point_in_time import (get_field_at_date as _get_field_at_date,
                           reconstruct_open_rows)
from hubspot_history import HISTORY_KEYS
from utils import compute_deal_value, get_value_properties, get_fiscal_quarter

# Elapsed quarters this backfill targets, per the Method 2 spec.
DEFAULT_QUARTERS = ['FY2026 Q3', 'FY2026 Q4', 'FY2027 Q1', 'FY2027 Q2']


class SnapshotBackfiller:
    """Reconstructs historical snapshots from property history."""

    def __init__(self, property_history_cache: str = 'property_history_cache.json'):
        self.supabase_url = os.environ['SUPABASE_URL']
        self.supabase_key = os.environ['SUPABASE_SERVICE_KEY']
        self.client = create_client(self.supabase_url, self.supabase_key)

        config_path = REPO_ROOT / 'config/client.yaml'
        with open(config_path) as f:
            config = yaml.safe_load(f)
        self.config = config

        self.stage_map = {}
        for pipeline in config['pipeline']['pipelines']:
            for stage in pipeline['stages']:
                self.stage_map[str(stage['id'])] = {
                    'name': stage['name'], 'order': stage['order'],
                    'pipeline_id': pipeline['id'],
                    'pipeline_name': pipeline['name'],
                }

        cache_path = Path(property_history_cache)
        if not cache_path.exists():
            raise FileNotFoundError(
                f"Property history cache not found: {property_history_cache}\n"
                f"Run hubspot_history.py --all first"
            )
        with open(cache_path) as f:
            cache = json.load(f)
        self.property_history = cache['deals']

        # Per-property history, shaped for point_in_time.get_field_at_date.
        self.field_history = {}
        for prop, key in HISTORY_KEYS.items():
            self.field_history[prop] = {
                deal_id: {'history': rec.get(key) or []}
                for deal_id, rec in cache['deals'].items()
            }

        self.value_properties = get_value_properties(config)
        missing = [p for p in self.value_properties if p not in HISTORY_KEYS]
        if missing:
            raise ValueError(
                f"Value properties {missing} are not tracked in the property "
                f"history cache. Add them to hubspot_history.TRACKED_PROPERTIES "
                f"and re-fetch, or deal_value falls back to a proxy again."
            )
        print(f"Loaded property history for {len(self.property_history)} deals")

        # Population comes from the deals table — create_date and pipeline_id
        # are what the shared inclusion rule needs. create_date is REQUIRED:
        # without it a deal cannot be placed in time and is excluded (counted).
        all_deals = select_all(
            self.client, 'deals',
            columns='deal_id,stage,company_name,close_date,owner_email,'
                    'pipeline_id,create_date')
        self.current_deals = {d['deal_id']: d for d in all_deals}

        self.population = {}
        self.no_create_date = []
        for d in all_deals:
            cd = self._parse_date(d.get('create_date'))
            if cd is None:
                self.no_create_date.append(d['deal_id'])
                continue
            self.population[str(d['deal_id'])] = {
                'create': cd, 'pipeline': str(d.get('pipeline_id') or 'default')}
        print(f"Population with create_date: {len(self.population)} "
              f"(excluded, no create_date: {len(self.no_create_date)})")

    @staticmethod
    def _parse_date(raw):
        if raw in (None, '', 'null'):
            return None
        s = str(raw).strip()
        if s.lstrip('-').isdigit():
            try:
                return datetime.utcfromtimestamp(int(s) / 1000).date()
            except (ValueError, OSError, OverflowError):
                return None
        try:
            return datetime.fromisoformat(s.replace('Z', '+00:00')).date()
        except ValueError:
            return None

    def get_stage_order(self, stage_id: str) -> Optional[int]:
        if not stage_id or str(stage_id) not in self.stage_map:
            return None
        return self.stage_map[str(stage_id)]['order']

    def get_deal_status(self, stage_id: str) -> str:
        if is_won(stage_id):
            return 'won'
        if is_lost(stage_id):
            return 'lost'
        return 'active'

    def get_close_date_at_date(self, deal_id, snapshot_date):
        """Point-in-time close_date (a forecast that moves). None if unknown."""
        raw, conf = _get_field_at_date(
            self.field_history['closedate'], deal_id, snapshot_date)
        if raw in (None, '', 'null'):
            return None, conf
        return str(raw)[:10], conf

    def quarter_weeks(self, quarter_label: str) -> List[date]:
        """Weekly Monday snapshot dates whose fiscal quarter is quarter_label.

        Labelled via get_fiscal_quarter rather than hardcoding the fiscal
        layout, so the calendar cannot be got wrong here.
        """
        start = date(2022, 1, 3)  # a Monday, before all history
        weeks = []
        for i in range(0, 320):
            d = start + timedelta(weeks=i)
            _, _, label = get_fiscal_quarter(d, self.config)
            if label == quarter_label:
                weeks.append(d)
        return weeks

    def week_of_quarter(self, snapshot_date: date) -> Tuple[str, int]:
        """(fiscal_quarter_label, week 1..13) for a date. Both NOT NULL."""
        q_start, _, label = get_fiscal_quarter(snapshot_date, self.config)
        week = ((snapshot_date - q_start).days // 7) + 1
        return label, max(1, min(week, 13))

    def build_rows_for_date(self, snapshot_date: date) -> Tuple[List[Dict], List[str], Counter]:
        """Reconstruct all snapshot rows for one date via the shared function.

        Returns (db_rows, unclassifiable_deal_ids, tally). Row shaping (stage
        order, status, fiscal_quarter, week) is here; population and value are
        the shared function's.
        """
        open_rows, unclassifiable = reconstruct_open_rows(
            self.population, self.property_history, self.field_history,
            snapshot_date, self.config, self.value_properties,
            compute_deal_value)

        fq_label, week = self.week_of_quarter(snapshot_date)
        Ddt = datetime(snapshot_date.year, snapshot_date.month, snapshot_date.day)
        db_rows, tally = [], Counter()
        for r in open_rows:
            deal_id = r['deal_id']
            stage_id = r['stage_id']
            close_date, close_conf = self.get_close_date_at_date(deal_id, Ddt)
            current = self.current_deals.get(deal_id, {})
            db_rows.append({
                'deal_id': deal_id,
                'snapshot_date': snapshot_date.isoformat(),
                'pipeline_id': r['pipeline'],
                'stage_id': stage_id,
                'stage_order': self.get_stage_order(stage_id),
                'deal_value': r['deal_value'],          # point-in-time, None if unknown
                'close_date': close_date,               # point-in-time
                'owner_email': current.get('owner_email'),   # current: no owner history
                'deal_status': self.get_deal_status(stage_id),
                'snapshot_source': 'backfilled',
                'fiscal_quarter': fq_label,             # NOT NULL (migration 038)
                'week_of_quarter': week,
                'backfill_confidence': r['stage_confidence'],
                'value_confidence': r['value_confidence'],
                'close_date_confidence': close_conf,
                'has_property_history': r['stage_confidence'] != 'no_history',
            })
            tally['rows'] += 1
            tally[f"stage_{r['stage_confidence']}"] += 1
            tally[f"value_{r['value_confidence']}"] += 1
        return db_rows, unclassifiable, tally

    def backfill_quarters(self, quarters: List[str], report_only: bool,
                          batch_size: int = 1000,
                          checkpoint_path: str = 'backfill_checkpoint.json',
                          out_path: str = 'backfill_reconstruction.json') -> Dict:
        """Reconstruct and (unless report_only) write the given quarters.

        Resumable via a durable checkpoint of completed dates; idempotent via
        the (deal_id, snapshot_date) upsert key. Deterministic ordering means
        a resumed run reproduces the same sequence.
        """
        ckpt = self._load_checkpoint(checkpoint_path) if not report_only else {'done': []}
        done = set(tuple(x) for x in ckpt.get('done', []))

        summary, all_rows, total_unclassifiable = [], [], []
        skipped_done = 0
        for quarter in quarters:
            weeks = self.quarter_weeks(quarter)
            if not weeks:
                print(f"  ⚠ {quarter}: no weeks resolved for this label")
                continue
            for D in weeks:
                key = (quarter, D.isoformat())
                if key in done:
                    skipped_done += 1
                    continue
                rows, unclassifiable, tally = self.build_rows_for_date(D)
                total_unclassifiable.extend(unclassifiable)
                # Scoped coverage computed here from the rows already built,
                # so main() never re-reconstructs a date just to score it.
                usable, denom = _scoped_coverage(rows, self.config)
                tally['usable'], tally['denom'] = usable, denom

                if not report_only:
                    self._write_batch(rows, batch_size)
                    done.add(key)
                    ckpt['done'] = sorted(done)
                    self._save_checkpoint(checkpoint_path, ckpt)
                else:
                    all_rows.extend(rows)

                summary.append((quarter, D, tally))

        if report_only:
            Path(out_path).write_text(json.dumps(all_rows, indent=1, default=str))

        return {'summary': summary, 'unclassifiable': total_unclassifiable,
                'skipped_done': skipped_done, 'report_only': report_only,
                'out_path': out_path}

    def _write_batch(self, rows: List[Dict], batch_size: int):
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            self.client.table('deals_snapshot').upsert(
                batch, on_conflict='deal_id,snapshot_date').execute()

    @staticmethod
    def _load_checkpoint(path):
        p = Path(path)
        if p.exists():
            ckpt = json.loads(p.read_text())
            print(f"Resuming: {len(ckpt.get('done', []))} (quarter, week) "
                  f"already done in {path}")
            return ckpt
        return {'done': []}

    @staticmethod
    def _save_checkpoint(path, ckpt):
        Path(path).write_text(json.dumps(ckpt, indent=1))

    def snapshot_row_count(self) -> int:
        """Current deals_snapshot row count, for before/after backup."""
        rows = select_all(self.client, 'deals_snapshot', columns='deal_id')
        return len(rows)


def _scoped_coverage(rows, config):
    """Per the Phase 3 definition: denominator scoped by pipeline, numerator
    also requires a known qualified stage; unknown-stage deals in a
    non-excluded pipeline count against coverage."""
    from point_in_time import load_scope_config, is_deal_in_analytics_scope
    excl, stage_cfg = load_scope_config(config)
    denom = usable = 0
    for r in rows:
        stage = r['stage_id']
        if r['pipeline_id'] in excl:
            continue
        is_usable = is_deal_in_analytics_scope(stage, r['pipeline_id'], excl, stage_cfg)
        if is_usable or stage is None:
            denom += 1
            if is_usable:
                usable += 1
    return usable, denom


def main():
    parser = argparse.ArgumentParser(description='Reconstruct historical snapshots')
    parser.add_argument('--report-only', action='store_true',
                        help='Compute per-quarter coverage and row counts, '
                             'write nothing to deals_snapshot')
    parser.add_argument('--quarters', default=','.join(DEFAULT_QUARTERS),
                        help='Comma-separated fiscal-quarter labels')
    parser.add_argument('--cache-file', default='property_history_cache.json')
    parser.add_argument('--batch-size', type=int, default=1000)
    parser.add_argument('--checkpoint', default='backfill_checkpoint.json')
    args = parser.parse_args()

    quarters = [q.strip() for q in args.quarters.split(',') if q.strip()]
    print("=" * 92)
    print("METHOD 2 PHASE 4 — HISTORICAL RECONSTRUCTION"
          + ("  (REPORT ONLY, no write)" if args.report_only else "  (WRITING)"))
    print("=" * 92)
    print(f"Quarters: {quarters}\n")

    b = SnapshotBackfiller(property_history_cache=args.cache_file)
    gate = b.config['forecast_analysis'].get('min_scoped_snapshot_coverage_pct', 80)

    before = None
    if not args.report_only:
        before = b.snapshot_row_count()
        print(f"deals_snapshot rows before: {before}\n")

    result = b.backfill_quarters(quarters, args.report_only,
                                 batch_size=args.batch_size,
                                 checkpoint_path=args.checkpoint)

    # Per-quarter aggregation.
    print(f"\n{'quarter':<12} {'week':<12} {'rows':>6} {'exact':>7} {'pre_h':>6} "
          f"{'no_h':>6} {'usable%':>8} {'gate':>6}")
    print("-" * 92)
    per_quarter = {}
    for quarter, D, tally in result['summary']:
        usable, denom = tally.get('usable', 0), tally.get('denom', 0)
        pct = (usable / denom * 100) if denom else 0.0
        verdict = 'PASS' if pct >= gate else 'FAIL'
        q = per_quarter.setdefault(quarter, {'rows': 0, 'week_pass': 0,
                                             'week_total': 0, 'min_pct': 999,
                                             'exact': 0, 'pre': 0, 'no': 0})
        q['rows'] += tally['rows']
        q['week_total'] += 1
        q['week_pass'] += (verdict == 'PASS')
        q['min_pct'] = min(q['min_pct'], pct)
        q['exact'] += tally.get('stage_exact', 0)
        q['pre'] += tally.get('stage_pre_history', 0)
        q['no'] += tally.get('stage_no_history', 0)
        print(f"{quarter:<12} {D.isoformat():<12} {tally['rows']:>6} "
              f"{tally.get('stage_exact', 0):>7} {tally.get('stage_pre_history', 0):>6} "
              f"{tally.get('stage_no_history', 0):>6} {pct:>7.1f}% {verdict:>6}")

    print("\n" + "=" * 92)
    print("PER-QUARTER SUMMARY (coverage gate: "
          f"{gate}% scoped)")
    print("=" * 92)
    print(f"{'quarter':<12} {'rows':>7} {'weeks pass':>12} {'min week %':>12} "
          f"{'stage exact/pre/no':>22}")
    for quarter in quarters:
        if quarter not in per_quarter:
            continue
        q = per_quarter[quarter]
        verdict = 'PASS' if q['week_pass'] == q['week_total'] else 'FAIL'
        weeks_str = f"{q['week_pass']}/{q['week_total']}"
        conf_str = f"{q['exact']}/{q['pre']}/{q['no']}"
        print(f"{quarter:<12} {q['rows']:>7} {weeks_str:>12} "
              f"{q['min_pct']:>11.1f}% {conf_str:>22}  {verdict}")

    if result['unclassifiable']:
        u = sorted(set(result['unclassifiable']))
        print(f"\n✗ {len(u)} deal(s) raised on an unclassifiable stage: {u[:10]}")
        print("  Resolve in field_semantics before writing.")

    if args.report_only:
        print(f"\nReport only — nothing written. Reconstruction in "
              f"{result['out_path']}.")
        print("Quarters failing the gate are EXCLUDED from conversion analysis, "
              "not a threshold to revisit.")
    else:
        after = b.snapshot_row_count()
        print(f"\ndeals_snapshot rows: {before} -> {after}  (+{after - before})")
        print(f"Resumed-skipped dates: {result['skipped_done']}")

    print("\nDOLLAR-BASIS CAVEAT: forecast_analyses still zero-fills null "
          "deal_value (ledger).")
    print("No dollar-basis conversion number until that is worked off; "
          "basis: count is unaffected.")
    return 1 if result['unclassifiable'] else 0


if __name__ == '__main__':
    sys.exit(main())
