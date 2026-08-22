#!/usr/bin/env python3
"""
ETL: Extract call transcripts and build call cache.

Modes:
  - backfill: Read from CSV files (for historical import)
  - incremental: Fetch from APIs since last cache update (for daily runs)

Outputs:
  - memory/calls/<company-slug>.json (one file per company with all calls)

Call Intelligence Adapters:
  - Fireflies: summary_text directly (AI-generated)
  - Apollo: summarized via Claude Haiku (transcript_text → summary)
  - Gong: basic metadata mode (title, date, duration, participants)
    * To enable rich data (transcripts, topics, action items):
      1. Contact Gong admin to enable transcript API access
      2. Requires Technical Admin role
      3. Set GongAdapter.ACCESS_LEVEL = 'rich' in code
    * Or use CSV export mode for transcript ETL if API access unavailable
"""

import os
import sys
import csv
import json
import argparse
import re
import yaml
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone as _stdlib_tz

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add revops-metrics to path for API clients
REPO_ROOT = Path(__file__).parent.parent
REVOPS_METRICS = REPO_ROOT.parent / 'revops-metrics'
if REVOPS_METRICS.exists():
    sys.path.insert(0, str(REVOPS_METRICS))

# Add local adapters to path
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

# Import timezone utilities
from sdr_utils import utc_to_reporting_date
from llm_client import LLMClient


def slugify(company_name: str) -> str:
    """Convert company name to slug (e.g., 'Acme Corp' -> 'acme-corp')."""
    slug = company_name.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    return slug


def get_external_domains(meeting_attendees: list, internal_domains: list) -> list:
    """
    Extract prospect email domains from meeting attendees.
    Excludes organizer's own company domains and common personal email providers.
    """
    skip_domains = set(internal_domains + [
        'gmail.com', 'outlook.com', 'hotmail.com',
        'yahoo.com', 'icloud.com',
        'resource.calendar.google.com',
        'calendar.google.com',
        'group.calendar.google.com',
    ])
    domains = set()
    for attendee in (meeting_attendees or []):
        email = (attendee.get('email') or '').lower().strip()
        if '@' in email:
            domain = email.split('@')[1]
            if domain and domain not in skip_domains:
                domains.add(domain)
    return sorted(list(domains))


def extract_company_from_title(title: str) -> str:
    """
    Extract company name from call title.

    Common patterns:
    - "Company Name - Topic"
    - "Topic - Company Name"
    - "Company Name: Topic"
    - "First Last (Company Name)"
    """
    if not title:
        return "Unknown"

    # Try dash separator
    if ' - ' in title:
        parts = title.split(' - ')
        # Take first part if it looks like a company (>3 chars, not generic)
        if len(parts[0]) > 3 and not parts[0].lower().startswith(('demo', 'call', 'meeting')):
            return parts[0].strip()
        # Otherwise try second part
        if len(parts) > 1:
            return parts[1].strip()

    # Try colon separator
    if ': ' in title:
        parts = title.split(': ')
        return parts[0].strip()

    # Try parentheses
    paren_match = re.search(r'\(([^)]+)\)$', title)
    if paren_match:
        return paren_match.group(1).strip()

    # Fallback: use first 3 words
    words = title.split()[:3]
    return ' '.join(words)


def get_last_cache_date(cache_dir: Path) -> datetime:
    """Get the most recent call date from existing cache files."""
    latest_date = None

    for cache_file in cache_dir.glob('*.json'):
        try:
            with open(cache_file) as f:
                data = json.load(f)
                for call in data.get('calls', []):
                    call_date_str = call.get('date')
                    if call_date_str:
                        try:
                            call_date = datetime.fromisoformat(call_date_str.replace('Z', '+00:00'))
                            if latest_date is None or call_date > latest_date:
                                latest_date = call_date
                        except:
                            pass
        except:
            continue

    # Default to 7 days ago if no cache exists
    return latest_date or (datetime.now() - timedelta(days=7))


def get_call_adapter():
    """
    Load call intelligence adapter based on config/client.yaml.

    Returns:
        Adapter instance (GongAdapter or FirefliesClient)
    """
    # Load config
    config_path = REPO_ROOT / 'config' / 'client.yaml'
    if not config_path.exists():
        print("   ⚠️  config/client.yaml not found, defaulting to Fireflies")
        call_tool = 'fireflies'
    else:
        with open(config_path) as f:
            config = yaml.safe_load(f)
            call_tool = config.get('call_tools', {}).get('primary', 'fireflies')

    # Import and return appropriate adapter
    if call_tool == 'gong':
        from adapters.gong_adapter import GongAdapter
        return GongAdapter()
    elif call_tool == 'fireflies':
        from fireflies_client import FirefliesClient
        return FirefliesClient()
    else:
        raise ValueError(f"Unknown call tool: {call_tool}. Must be 'gong' or 'fireflies'")


def fetch_call_intelligence_incremental(since_date: datetime, calls_by_company: dict):
    """
    Fetch new calls from configured call intelligence sources.

    Uses source-agnostic factory to get all configured adapters,
    fetches from each, deduplicates by source priority, and builds
    call cache. No type-checks, no adapter_type branches.
    """
    # Get all configured call sources in priority order
    from adapters import get_call_sources

    adapters = get_call_sources()

    if not adapters:
        print("   ⚠️  No call source adapters available")
        return

    # Load internal domains from config for participant filtering
    config_path = REPO_ROOT / 'config' / 'client.yaml'
    internal_domains = ['growthbook.io']  # default
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
                internal_domains = config.get('organization', {}).get('internal_domains', ['growthbook.io'])
        except Exception as e:
            print(f"   ⚠️  Could not load internal_domains from config: {e}")

    print(f"\n🎙️  Fetching new calls from {len(adapters)} source(s) since {since_date.strftime('%Y-%m-%d')}")

    # Fetch from all sources
    all_calls = []  # list of NormalizedCall objects
    MAX_FETCH = 1000  # safety limit per source

    for adapter in adapters:
        source_name = adapter.source_name
        print(f"   📡 Fetching from {source_name}...")

        skip = 0
        limit = 50
        source_calls = 0

        while True:
            try:
                batch = adapter.fetch_recent(limit=limit, skip=skip, since=since_date)

                if not batch:
                    break

                all_calls.extend(batch)
                source_calls += len(batch)

                if len(batch) < limit:
                    break

                skip += limit
                if skip > MAX_FETCH:
                    print(f"      Hit MAX_FETCH limit ({MAX_FETCH}), stopping")
                    break

            except Exception as e:
                print(f"      ✗ Error fetching from {source_name}: {e}")
                break

        print(f"      Found {source_calls} calls from {source_name}")

    print(f"   Total fetched: {len(all_calls)} calls")

    # Deduplicate by source priority
    deduped = deduplicate_calls_by_source_priority(all_calls)
    print(f"   After dedup: {len(deduped)} calls")

    # Convert NormalizedCall objects to cache format
    total_new = 0

    for normalized_call in deduped:
        # Parse call_date to date object
        try:
            call_date = datetime.fromisoformat(normalized_call.call_date).date()
        except:
            continue

        # Skip if before cutoff
        if call_date <= since_date.date():
            continue

        # Extract company from title
        company = extract_company_from_title(normalized_call.title)
        slug = slugify(company)

        if slug not in calls_by_company:
            calls_by_company[slug] = {
                "company": company,
                "slug": slug,
                "calls": []
            }

        # Build cache-format call dict from NormalizedCall
        call_dict = {
            "id": normalized_call.source_call_id,
            "source": normalized_call.source,
            "title": normalized_call.title,
            "date": normalized_call.call_date,
            "duration_minutes": normalized_call.duration_minutes,
            "summary": normalized_call.summary,
            "organizer": normalized_call.participant_emails[0] if normalized_call.participant_emails else '',
            "participants": normalized_call.participant_count,
        }

        # Add source-specific fields if available
        # (keywords/action_items for fireflies, participant_domains for fireflies)
        # These are in the summary text now, so we don't need separate fields

        calls_by_company[slug]["calls"].append(call_dict)
        total_new += 1

    print(f"   Added {total_new} new calls to cache")


def fetch_apollo_incremental(since_date: datetime, calls_by_company: dict, total_summarized: list):
    """Fetch new Apollo calls since date via API."""
    try:
        from apollo_client import get_apollo_client
    except ImportError:
        print("   ⚠️  apollo_client not available, skipping Apollo incremental fetch")
        return

    print(f"\n📞 Fetching new Apollo calls since {since_date.strftime('%Y-%m-%d')}")

    client = get_apollo_client()

    # Fetch all conversations (auto-paginated)
    all_convos = client.get_all_conversations(max_pages=10)

    new_calls = []
    for convo in all_convos:
        # Parse date
        start_time = convo.get('start_time')
        if not start_time:
            continue

        try:
            convo_date_utc = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            if convo_date_utc.tzinfo is None:
                convo_date_utc = convo_date_utc.replace(tzinfo=_stdlib_tz.utc)
            convo_date = utc_to_reporting_date(convo_date_utc)
            if convo_date is None:
                continue
        except:
            continue

        # Skip if before cutoff or not completed
        if convo_date <= since_date.date():
            continue
        if convo.get('state') not in ['completed', 'insights_generated']:
            continue

        new_calls.append(convo)

    print(f"   Found {len(new_calls)} new Apollo calls")

    # Fetch full transcripts and summarize
    for i, convo in enumerate(new_calls, 1):
        convo_id = convo.get('id')
        title = convo.get('topic', '')

        try:
            # Get full conversation with transcript
            detail = client.get_conversation(convo_id)
            transcript_list = detail.get('transcript', [])

            # DIAGNOSTIC: Log transcript structure
            logger.debug(
                f"[APOLLO] convo_id={convo_id} "
                f"transcript_list type={type(transcript_list)} "
                f"len={len(transcript_list) if transcript_list else 0} "
                f"first_entry={str(transcript_list[0])[:100] if transcript_list else 'empty'}"
            )

            # DIAGNOSTIC: Log sample entry structure
            if transcript_list:
                sample = transcript_list[0]
                logger.debug(
                    f"[APOLLO] sample entry keys={list(sample.keys()) if isinstance(sample, dict) else type(sample)}"
                )

            # Build transcript text
            # Apollo format: participant_name + spoken_sentence (not speaker + words)
            transcript_text = '\n'.join(
                f"[{entry.get('participant_name', entry.get('speaker', 'Unknown'))}]: "
                f"{entry.get('spoken_sentence', entry.get('words', entry.get('text', entry.get('content', ''))))}"
                for entry in transcript_list
                if isinstance(entry, dict)
            )

            if not transcript_text or len(transcript_text) < 50:
                continue

            # Extract company
            company = extract_company_from_title(title)
            slug = slugify(company)

            # Summarize with Haiku
            print(f"   [{i}/{len(new_calls)}] Summarizing: {title[:50]}...")
            try:
                summary = summarize_apollo_transcript(transcript_text, title)
                total_summarized[0] += 1
            except Exception as e:
                # summarize_apollo_transcript handles its own errors, but just in case
                logger.error(f"[APOLLO] Unexpected error summarizing {title[:30]}: {e}")
                summary = f"[Summarization error — raw transcript]\n{transcript_text[:2500]}"

            # Add to company dict
            if slug not in calls_by_company:
                calls_by_company[slug] = {
                    "company": company,
                    "slug": slug,
                    "calls": []
                }

            start_time = convo.get('start_time', '')
            start_time_utc = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            if start_time_utc.tzinfo is None:
                start_time_utc = start_time_utc.replace(tzinfo=_stdlib_tz.utc)
            call_date_reporting = utc_to_reporting_date(start_time_utc)
            call_date = call_date_reporting.isoformat() if call_date_reporting else ''

            calls_by_company[slug]["calls"].append({
                "id": convo_id,
                "source": "apollo",
                "title": title,
                "date": call_date,
                "duration_minutes": int(convo.get('duration', 0) / 60) if convo.get('duration') else 0,
                "summary": summary,
                "host": convo.get('host', ''),
                "participants": len(transcript_list)
            })

        except Exception as e:
            print(f"      ✗ Error processing {title[:30]}: {e}")
            continue


def summarize_apollo_transcript(transcript_text: str, title: str) -> str:
    """
    Summarize Apollo transcript using Claude Haiku.

    Handles two input formats:
    1. Full transcript text (preferred) — structured speaker/sentence entries
    2. Speaker fragments (fallback) — when Apollo doesn't provide full transcript
       e.g. "[logan]: David.\n[David Gregory]: Hey, Christian."

    For very short transcripts (< 1500 chars), returns the text as-is
    rather than summarizing — it's already short enough for the context builder.

    Never returns [Summary failed] — always returns usable content.
    """
    # Strip [Summary failed] prefix if present from a prior failed attempt
    clean_text = transcript_text
    if clean_text.startswith("[Summary failed]"):
        clean_text = clean_text[len("[Summary failed]"):].strip()
        logger.info(f"[APOLLO] Stripped [Summary failed] prefix from {title[:30]}")

    if not clean_text or len(clean_text) < 100:
        return f"[Insufficient transcript data — {len(clean_text)} chars]"

    if len(clean_text) < 1500:
        logger.debug(f"[APOLLO] Short transcript ({len(clean_text)} chars), returning as-is")
        return clean_text  # Short enough, return as-is

    client = LLMClient.from_config("enrichment")

    system = (
        "Summarize this sales call for MEDDICC analysis. "
        "Extract: attendees and titles, quantifiable outcomes "
        "(metrics, ROI, time savings), budget authority signals, "
        "technical requirements, decision process and timeline, "
        "specific pain points, champion signals, competitors "
        "mentioned, and next steps. "
        "Write in past tense, 400-600 words. "
        f"Start with: 'Call on [date] with [attendees].'"
    )

    try:
        resp = client.complete(
            messages=[{
                'role': 'user',
                'content': f'Title: {title}\n\nTranscript:\n{clean_text[:8000]}'
            }],
            system=system,
            max_tokens=800
        )
        return resp.text
    except Exception as e:
        logger.warning(f'[APOLLO] Haiku summarization failed for {title[:30]}: {e}')
        # Return raw transcript truncated — better than [Summary failed]
        # The context builder can work with raw transcript fragments
        return f"[Auto-summary failed — raw transcript]\n{clean_text[:2500]}"


def process_apollo_csv(csv_path: Path, calls_by_company: dict, total_summarized: list):
    """Process Apollo CSV and add calls to company dict."""
    print(f"\n📞 Processing Apollo calls from {csv_path}")

    if not csv_path.exists():
        print(f"   ⚠️  File not found, skipping")
        return

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"   Found {len(rows)} Apollo calls")

    for i, row in enumerate(rows, 1):
        title = row.get('title', '')
        transcript_text = row.get('transcript_text', '')

        # Skip if no transcript
        if not transcript_text or len(transcript_text) < 50:
            continue

        # Extract company
        company = extract_company_from_title(title)
        slug = slugify(company)

        # Summarize with Haiku
        print(f"   [{i}/{len(rows)}] Summarizing: {title[:50]}...")
        try:
            summary = summarize_apollo_transcript(transcript_text, title)
            total_summarized[0] += 1
        except Exception as e:
            print(f"      ✗ Error: {e}")
            summary = f"[Summary failed] {transcript_text[:200]}"

        # Add to company dict
        if slug not in calls_by_company:
            calls_by_company[slug] = {
                "company": company,
                "slug": slug,
                "calls": []
            }

        calls_by_company[slug]["calls"].append({
            "id": row.get('transcript_id', ''),
            "source": "apollo",
            "title": title,
            "date": row.get('date', ''),
            "duration_minutes": int(float(row.get('duration_minutes', 0) or 0)),
            "summary": summary,
            "host": row.get('host', ''),
            "participants": int(float(row.get('participant_count', 0) or 0))
        })


def process_fireflies_csv(csv_path: Path, calls_by_company: dict):
    """Process Fireflies CSV and add calls to company dict."""
    print(f"\n🔥 Processing Fireflies calls from {csv_path}")

    if not csv_path.exists():
        print(f"   ⚠️  File not found, skipping")
        return

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"   Found {len(rows)} Fireflies calls")

    for i, row in enumerate(rows, 1):
        title = row.get('title', '')
        summary_text = row.get('summary_text', '')

        # Skip if no summary
        if not summary_text:
            continue

        # Extract company
        company = extract_company_from_title(title)
        slug = slugify(company)

        # Add to company dict
        if slug not in calls_by_company:
            calls_by_company[slug] = {
                "company": company,
                "slug": slug,
                "calls": []
            }

        calls_by_company[slug]["calls"].append({
            "id": row.get('transcript_id', ''),
            "source": "fireflies",
            "title": title,
            "date": row.get('date', ''),
            "duration_minutes": int(float(row.get('duration_minutes', 0) or 0)),
            "summary": summary_text,
            "organizer": row.get('organizer_email', ''),
            "participants": int(float(row.get('participants_count', 0) or 0)),
            "keywords": row.get('keywords', ''),
            "action_items": row.get('action_items', '')
        })

        if (i % 50) == 0:
            print(f"   [{i}/{len(rows)}] Processed")


def deduplicate_calls_prefer_fireflies(calls: list, slug: str) -> list:
    """
    When multiple calls exist for the same deal on the same date,
    prefer Fireflies over Apollo.

    Fireflies has full AI summaries. Apollo frequently returns empty
    or corrupted summaries ([Summary failed]) due to plan limitations.

    Deduplication key: (deal_id, call_date)
    Source priority: fireflies > gong > apollo > unknown
    """
    SOURCE_PRIORITY = {
        "fireflies": 0,   # highest priority
        "gong":      1,
        "apollo":    2,
        "unknown":   3,   # lowest priority
    }

    # Group by (deal_id, call_date)
    seen: dict = {}
    for call in calls:
        # Use 'id' as deal_id for now since calls don't have explicit deal_id
        # The cache is per-company, so same-date calls for same company are deduplicated
        call_date = (call.get('date') or "")[:10]  # YYYY-MM-DD only
        source    = (call.get('source') or "unknown").lower()

        # Use title + date as key (same company, same title, same date = duplicate)
        title = (call.get('title') or "").lower()
        key = (title, call_date)

        if key not in seen:
            seen[key] = call
        else:
            existing_source = (seen[key].get('source') or "unknown").lower()
            existing_priority = SOURCE_PRIORITY.get(existing_source, 99)
            new_priority      = SOURCE_PRIORITY.get(source, 99)

            if new_priority < existing_priority:
                # New call has higher priority source — prefer it
                print(
                    f"     🔄 Preferring {source} over {existing_source} "
                    f"for {slug} on {call_date}"
                )
                seen[key] = call
            elif new_priority == existing_priority:
                # Same source — keep the one with longer summary
                existing_summary = seen[key].get('summary') or ""
                new_summary      = call.get('summary') or ""
                if len(new_summary) > len(existing_summary):
                    seen[key] = call

    result = list(seen.values())

    # Log the deduplication impact
    removed = len(calls) - len(result)
    if removed > 0:
        print(
            f"     ✂️  Deduplication removed {removed} calls "
            f"(Fireflies preferred over Apollo where both existed)"
        )

    return result


def deduplicate_calls_by_source_priority(calls: list, priority: list = None) -> list:
    """
    Deduplicate calls by (title, date), preferring sources higher in priority list.

    Args:
        calls: List of NormalizedCall objects
        priority: List of source names in priority order, e.g. ['fireflies', 'apollo'].
                  If None, reads from config/client.yaml call_sources.priority.
                  Defaults to ['fireflies', 'gong', 'apollo', 'unknown'] if not in config.

    Returns:
        Deduplicated list of NormalizedCall objects.

    Priority list determines which source wins when multiple sources return calls
    for the same deal on the same date. First in list = highest priority.

    Example:
        priority=['fireflies', 'apollo'] means Fireflies summaries preferred
        over Apollo's when both exist for same call.
    """
    # Get priority from config if not provided
    if priority is None:
        from adapters import get_source_priority
        priority = get_source_priority()

    # Default priority if not in config
    if not priority:
        priority = ['fireflies', 'gong', 'apollo', 'unknown']

    # Build priority map: source_name -> priority_rank (lower = higher priority)
    priority_map = {source: idx for idx, source in enumerate(priority)}

    # Group by (title, date)
    seen = {}

    for call in calls:
        # Dedup key: lowercase title + date
        title_lower = (call.title or "").lower()
        call_date = call.call_date  # ISO YYYY-MM-DD
        key = (title_lower, call_date)

        if key not in seen:
            seen[key] = call
        else:
            # Check priority
            existing_source = seen[key].source
            new_source = call.source

            existing_priority = priority_map.get(existing_source, 999)
            new_priority = priority_map.get(new_source, 999)

            if new_priority < existing_priority:
                # New call has higher priority source
                print(
                    f"     🔄 Dedup: Preferring {new_source} over {existing_source} "
                    f"for '{call.title[:30]}...' on {call_date}"
                )
                seen[key] = call
            elif new_priority == existing_priority:
                # Same source — keep the one with longer summary
                existing_summary = seen[key].summary or ""
                new_summary = call.summary or ""
                if len(new_summary) > len(existing_summary):
                    seen[key] = call

    result = list(seen.values())

    # Log deduplication impact
    removed = len(calls) - len(result)
    if removed > 0:
        print(
            f"     ✂️  Deduplication removed {removed} calls "
            f"(priority: {' > '.join(priority[:3])})"
        )

    return result


def validate_call_summary(call: dict) -> dict:
    """
    Flag calls with empty or corrupted summaries.
    Adds a 'summary_quality' field: 'good' | 'empty' | 'corrupted'
    Does NOT drop the call — just marks it so context_builder can
    handle it appropriately.
    """
    summary = call.get("summary") or ""

    # Check for corruption BEFORE checking length
    if summary.startswith("[Summary failed]"):
        call["summary_quality"] = "corrupted"
    elif not summary or len(summary.strip()) < 50:
        call["summary_quality"] = "empty"
    else:
        call["summary_quality"] = "good"

    return call


def write_cache(slug: str, company: str, calls: list, cache_dir: Path):
    """Write cache file, merging with existing data if present."""
    path = cache_dir / f'{slug}.json'

    # Load existing cache if present
    existing_calls = []
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
                existing_calls = existing.get('calls', [])
        except Exception as e:
            print(f'     ⚠️  Could not read existing cache: {e}')

    # Merge by id — new calls take precedence on conflict
    existing_by_id = {c['id']: c for c in existing_calls}
    for call in calls:
        existing_by_id[call['id']] = call

    # Deduplicate by (title, date) with Fireflies preference
    merged_by_id = list(existing_by_id.values())
    deduplicated = deduplicate_calls_prefer_fireflies(merged_by_id, slug)

    # Validate summary quality
    for call in deduplicated:
        validate_call_summary(call)

    # Sort by date
    merged = sorted(deduplicated, key=lambda c: c.get('date', ''))

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({
            'company': company,
            'slug': slug,
            'last_etl_date': datetime.now().isoformat(),
            'calls': merged
        }, f, indent=2, ensure_ascii=False)

    return len(merged)


def save_call_caches(calls_by_company: dict, output_dir: Path):
    """Save one JSON file per company, merging with existing caches."""
    print(f"\n💾 Saving call caches to {output_dir}/")

    output_dir.mkdir(parents=True, exist_ok=True)

    for slug, data in calls_by_company.items():
        total_calls = write_cache(slug, data['company'], data['calls'], output_dir)
        print(f"   ✓ {slug}.json ({total_calls} calls)")

    print(f"\n✅ Processed {len(calls_by_company)} company cache files")


def main():
    parser = argparse.ArgumentParser(description="ETL call transcripts to cache")
    parser.add_argument(
        '--mode',
        type=str,
        choices=['backfill', 'incremental'],
        default='incremental',
        help='backfill: read from CSVs | incremental: fetch from APIs since last cache update'
    )
    parser.add_argument(
        '--apollo',
        type=str,
        default='data/apollo_transcripts.csv',
        help='Path to Apollo CSV file (backfill mode only)'
    )
    parser.add_argument(
        '--fireflies',
        type=str,
        default='data/fireflies_transcripts.csv',
        help='Path to Fireflies CSV file (backfill mode only)'
    )
    parser.add_argument(
        '--since-date',
        type=str,
        help='Override cutoff date (YYYY-MM-DD) for incremental mode'
    )
    args = parser.parse_args()

    # Setup paths
    repo_root = Path(__file__).parent.parent
    output_dir = repo_root / 'memory' / 'calls'

    # Track progress
    calls_by_company = {}
    total_summarized = [0]  # Use list to allow mutation in function

    start_time = datetime.now()

    if args.mode == 'backfill':
        print(f"\n{'='*60}")
        print(f"MODE: Backfill from CSV files")
        print(f"{'='*60}")

        apollo_csv = Path(args.apollo)
        fireflies_csv = Path(args.fireflies)

        process_apollo_csv(apollo_csv, calls_by_company, total_summarized)
        process_fireflies_csv(fireflies_csv, calls_by_company)

    else:  # incremental
        print(f"\n{'='*60}")
        print(f"MODE: Incremental API fetch")
        print(f"{'='*60}")

        # Auto-detect or use provided cutoff date
        if args.since_date:
            since_date = datetime.fromisoformat(args.since_date).replace(hour=0, minute=0, second=0, microsecond=0)
            print(f"Using provided cutoff: {since_date.strftime('%Y-%m-%d')}")
        else:
            since_date = get_last_cache_date(output_dir)
            print(f"Auto-detected cutoff: {since_date.strftime('%Y-%m-%d')}")

        # Fetch from APIs
        fetch_call_intelligence_incremental(since_date, calls_by_company)
        fetch_apollo_incremental(since_date, calls_by_company, total_summarized)

    # Save results
    save_call_caches(calls_by_company, output_dir)

    # Write to Supabase if configured
    if os.getenv('SUPABASE_URL'):
        print(f"\n📤 Writing to Supabase...")
        try:
            import sys
            sys.path.insert(0, str(repo_root / 'scripts'))
            from supabase_client import SupabaseWriter
            sb = SupabaseWriter()
            total = 0
            for slug, data in calls_by_company.items():
                calls = data.get('calls', [])
                if calls:
                    for c in calls:
                        c['company_slug'] = slug
                    n = sb.bulk_upsert_calls(calls, data['company'])
                    total += n
            print(f"  ✓ Supabase: {total} calls upserted")

            # Go-forward transcript persist (STORE_AND_BACKFILL_TRANSCRIPTS):
            # store each newly-ingested call's transcript alongside the call.
            # The calls upsert above committed first, so the FK parent exists.
            # Fully guarded — a transcript fetch/store failure must NOT fail the
            # calls ETL, which is the primary artifact.
            try:
                from transcript_store import fetch_transcript, build_transcript_row
                clients, rows = {}, []
                for slug, data in calls_by_company.items():
                    for c in data.get('calls', []):
                        cid, src = str(c.get('id') or ''), c.get('source') or ''
                        if not cid or not src:
                            continue
                        text, err = fetch_transcript(src, cid, clients)
                        rows.append(build_transcript_row(src, cid, text, error=err))
                stored = sb.bulk_upsert_transcripts(rows)
                have = sum(1 for r in rows if r.get('transcript'))
                print(f"  ✓ Supabase: {stored} transcripts upserted "
                      f"({have} with text, {stored - have} unavailable)")
            except Exception as te:
                print(f"  ⚠️  Transcript persist failed (calls unaffected): {te}")
        except Exception as e:
            print(f"  ⚠️  Supabase write failed: {e}")
    else:
        print(f"\n  ⏭️  SUPABASE_URL not set — skipping Supabase write")

    # Summary
    elapsed = (datetime.now() - start_time).total_seconds()
    total_calls = sum(len(c["calls"]) for c in calls_by_company.values())

    print(f"\n{'='*60}")
    print(f"ETL Complete")
    print(f"{'='*60}")
    print(f"Mode: {args.mode}")
    print(f"Companies updated: {len(calls_by_company)}")
    print(f"Total new calls: {total_calls}")
    print(f"Apollo calls summarized: {total_summarized[0]}")
    print(f"Time: {elapsed:.1f}s")
    print(f"Output: {output_dir}/")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
