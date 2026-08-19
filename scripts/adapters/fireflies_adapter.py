"""
FirefliesAdapter — CallSourceAdapter wrapper for Fireflies.

Wraps the existing FirefliesClient (scripts/fireflies_client.py) to conform
to the CallSourceAdapter interface. Does not rewrite the internal logic —
just adapts the surface to return NormalizedCall.
"""
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Optional

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.call_source import CallSourceAdapter, NormalizedCall
from fireflies_client import FirefliesClient


class FirefliesAdapter(CallSourceAdapter):
    """
    Fireflies conversation intelligence adapter.

    Wraps FirefliesClient. Fireflies is a recorder (not a dialer) so
    summaries are rich and transcripts are available via the API.
    """

    source_name = "fireflies"

    def __init__(self, api_key: str = None):
        """Initialize with Fireflies API key."""
        self._client = FirefliesClient(api_key=api_key)

    def fetch_recent(self, limit: int = 50, skip: int = 0,
                     since: Optional[datetime] = None) -> List[NormalizedCall]:
        """
        Return recent calls as list[NormalizedCall]. Paginated.

        Args:
            limit: Number of transcripts to fetch
            skip: Number to skip for pagination
            since: Optional datetime filter (not applied by Fireflies API,
                   filtered in-memory after fetch)

        Returns:
            List of NormalizedCall objects
        """
        # Fetch raw transcripts from Fireflies
        transcripts = self._client.get_transcripts(limit=limit, skip=skip)

        # Filter by date if specified
        if since:
            since_timestamp = since.timestamp() * 1000  # Fireflies uses ms
            transcripts = [
                t for t in transcripts
                if isinstance(t.get('date'), (int, float)) and
                   t.get('date', 0) >= since_timestamp
            ]

        # Normalize each transcript
        return [self._normalize(t) for t in transcripts]

    def fetch_by_company(self, company_name: str, max_results: int = 100,
                         since: Optional[datetime] = None) -> List[NormalizedCall]:
        """
        Return calls for a company as list[NormalizedCall].

        Args:
            company_name: Company name to search for
            max_results: Maximum number of results
            since: Optional datetime filter

        Returns:
            List of NormalizedCall objects sorted by date ascending
        """
        # Use existing search_by_company
        transcripts = self._client.search_by_company(
            company_name=company_name,
            max_results=max_results,
            since_date=since
        )

        # Normalize each transcript
        return [self._normalize(t) for t in transcripts]

    def test_connection(self) -> bool:
        """
        True if credentials work and Fireflies is reachable.

        Tests by fetching 1 transcript.
        """
        try:
            result = self._client.get_transcripts(limit=1, skip=0)
            return result is not None
        except Exception:
            return False

    def supports_transcripts(self) -> bool:
        """Fireflies is a recorder, transcripts available."""
        return True

    def _normalize(self, transcript: dict) -> NormalizedCall:
        """
        Convert a Fireflies transcript dict to NormalizedCall.

        Uses the existing format_summary_for_meddicc method to produce
        the rich summary text.
        """
        # Parse date
        date_raw = transcript.get('date')
        if isinstance(date_raw, (int, float)):
            date_obj = datetime.fromtimestamp(date_raw / 1000)
            call_date = date_obj.strftime('%Y-%m-%d')
        elif isinstance(date_raw, str):
            try:
                date_obj = datetime.fromisoformat(date_raw.replace('Z', '+00:00'))
                call_date = date_obj.strftime('%Y-%m-%d')
            except:
                call_date = date_raw
        else:
            call_date = 'unknown'

        # Get participant emails
        organizer = transcript.get('organizer_email', '')
        participants = transcript.get('participants', []) or []
        participant_emails = []

        if organizer:
            participant_emails.append(organizer)

        # Extract emails from participants (might be "Name <email>" format)
        for p in participants:
            if isinstance(p, str):
                if '<' in p and '>' in p:
                    email = p.split('<')[1].split('>')[0]
                    participant_emails.append(email)
                elif '@' in p:
                    participant_emails.append(p)

        # Deduplicate
        participant_emails = list(dict.fromkeys(participant_emails))

        # Get summary using existing formatter
        summary = self._client.format_summary_for_meddicc(transcript)

        # Check summary quality
        summary_obj = transcript.get('summary') or {}
        has_content = bool(
            summary_obj.get('short_summary') or
            summary_obj.get('overview')
        )

        return NormalizedCall(
            source=self.source_name,
            source_call_id=str(transcript.get('id', '')),
            title=transcript.get('title', 'Untitled'),
            call_date=call_date,
            summary=summary,
            duration_minutes=transcript.get('duration', 0),
            participant_emails=participant_emails,
            participant_count=len(participant_emails),
            raw_transcript=None,  # Fireflies doesn't include raw in list response
            summary_quality='good' if has_content else 'empty'
        )
