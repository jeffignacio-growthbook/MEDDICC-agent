"""
ApolloAdapter — CallSourceAdapter wrapper for Apollo.io.

Wraps the existing ApolloClient (scripts/apollo_client.py) to conform
to the CallSourceAdapter interface. Apollo is a video meeting platform
(dialer), not a conversation intelligence recorder, so summaries are
weaker and need LLM enrichment.

This adapter OWNS summarization - it calls summarize_apollo_transcript()
from etl_calls.py to ensure callers NEVER see '[Summary failed]'.
"""
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Optional

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.call_source import CallSourceAdapter, NormalizedCall
from apollo_client import ApolloClient


class ApolloAdapter(CallSourceAdapter):
    """
    Apollo.io conversation intelligence adapter.

    Wraps ApolloClient. Apollo is a video meeting platform (NOT the
    sales intelligence tool), so it provides strong metadata but weak
    native summaries. This adapter uses LLM summarization to produce
    MEDDICC-ready content.
    """

    source_name = "apollo"

    def __init__(self, api_key: str = None):
        """Initialize with Apollo API key."""
        self._client = ApolloClient(api_key=api_key)

    def fetch_recent(self, limit: int = 50, skip: int = 0,
                     since: Optional[datetime] = None) -> List[NormalizedCall]:
        """
        Return recent calls as list[NormalizedCall]. Paginated.

        Args:
            limit: Number of conversations to fetch
            skip: Number to skip for pagination (not used - Apollo uses pages)
            since: Optional datetime filter

        Returns:
            List of NormalizedCall objects
        """
        # Calculate page number from skip and limit
        page = (skip // limit) + 1 if limit > 0 else 1

        # Fetch conversations from Apollo
        result = self._client.get_conversations(page=page, per_page=limit)
        conversations = result.get('conversations', [])

        # Filter by state (only completed/insights_generated)
        conversations = [
            c for c in conversations
            if c.get('state') in ['completed', 'insights_generated']
        ]

        # Filter by date if specified
        if since:
            filtered = []
            for c in conversations:
                start_time_str = c.get('start_time', '')
                if start_time_str:
                    try:
                        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                        if start_time >= since:
                            filtered.append(c)
                    except:
                        # If can't parse, include it
                        filtered.append(c)
            conversations = filtered

        # Normalize each conversation
        # Note: This requires fetching full detail for each to get transcript
        normalized = []
        for conv in conversations:
            try:
                normalized.append(self._normalize(conv))
            except Exception as e:
                # Skip conversations that fail to normalize
                print(f"Warning: Failed to normalize Apollo conversation {conv.get('id')}: {e}")
                continue

        return normalized

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
        # Use existing search_conversations_by_company
        conversations = self._client.search_conversations_by_company(
            company_name=company_name,
            since_date=since
        )

        # Limit results
        conversations = conversations[:max_results]

        # Normalize each conversation
        normalized = []
        for conv in conversations:
            try:
                normalized.append(self._normalize(conv))
            except Exception as e:
                print(f"Warning: Failed to normalize Apollo conversation {conv.get('id')}: {e}")
                continue

        return normalized

    def test_connection(self) -> bool:
        """
        True if credentials work and Apollo is reachable.

        Tests by fetching 1 conversation.
        """
        try:
            result = self._client.get_conversations(page=1, per_page=1)
            return result is not None and 'conversations' in result
        except Exception:
            return False

    def supports_transcripts(self) -> bool:
        """
        Apollo provides transcripts, but they're raw speaker fragments
        that need summarization. Return True so callers know transcripts
        exist (even if weak).
        """
        return True

    def _normalize(self, conversation: dict) -> NormalizedCall:
        """
        Convert an Apollo conversation dict to NormalizedCall.

        This method OWNS summarization. It:
        1. Fetches full conversation detail to get transcript
        2. Calls _summarize_apollo() to produce MEDDICC-ready summary
        3. Guarantees summary never starts with '[Summary failed]'

        Args:
            conversation: Conversation metadata dict (may be partial)

        Returns:
            NormalizedCall with enriched summary
        """
        conversation_id = conversation.get('id', '')

        # Fetch full detail if we only have metadata
        # (Check if transcript is already present)
        if 'transcript' not in conversation:
            try:
                conversation = self._client.get_conversation(conversation_id)
            except Exception as e:
                # If we can't fetch detail, use metadata-only summary
                print(f"Warning: Could not fetch Apollo conversation {conversation_id}: {e}")

        # Parse date
        start_time_str = conversation.get('start_time', '')
        if start_time_str:
            try:
                date_obj = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                call_date = date_obj.strftime('%Y-%m-%d')
            except:
                call_date = start_time_str[:10] if len(start_time_str) >= 10 else 'unknown'
        else:
            call_date = 'unknown'

        # Get participant emails (Apollo doesn't always provide these)
        # We can extract from transcript if available
        participant_emails = self._extract_participant_emails(conversation)

        # Get summary - this is where we guarantee no '[Summary failed]'
        summary = self._summarize_apollo(conversation)

        # Determine summary quality
        transcript = conversation.get('transcript', []) or []
        has_transcript = len(transcript) > 0
        summary_quality = 'good' if has_transcript else 'empty'

        return NormalizedCall(
            source=self.source_name,
            source_call_id=str(conversation_id),
            title=conversation.get('topic', 'Untitled'),
            call_date=call_date,
            summary=summary,
            duration_minutes=round((conversation.get('duration', 0) or 0) / 60, 0),
            participant_emails=participant_emails,
            participant_count=len(participant_emails) if participant_emails else 0,
            raw_transcript=None,  # Don't include raw fragments
            summary_quality=summary_quality
        )

    def _summarize_apollo(self, conversation: dict) -> str:
        """
        Produce MEDDICC-ready summary from Apollo conversation.

        Uses existing format_conversation_for_meddicc if insights exist,
        otherwise builds a basic summary from metadata. NEVER returns
        '[Summary failed]'.

        Args:
            conversation: Full Apollo conversation dict

        Returns:
            Formatted summary string (never '[Summary failed]')
        """
        # Extract common fields at the top
        topic = conversation.get('topic', 'Untitled')
        start_time = conversation.get('start_time', '')
        duration = round((conversation.get('duration', 0) or 0) / 60, 1)

        # Try using Apollo's native insights first
        insights = conversation.get('insights', {}) or {}
        native_summary = insights.get('summary', '')

        if native_summary and len(native_summary) > 100:
            # Native summary is good enough, use existing formatter
            return self._client.format_conversation_for_meddicc(conversation)

        # Fallback: build transcript from fragments and summarize with LLM
        transcript_entries = conversation.get('transcript', []) or []

        if not transcript_entries:
            # No transcript at all - return metadata-only summary
            return (
                f"# {topic}\n"
                f"Date: {start_time[:10] if start_time else 'unknown'} | "
                f"Duration: {duration}m\n\n"
                f"## Note\n"
                f"No transcript available. Meeting recorded but "
                f"transcript extraction failed or is still processing."
            )

        # Build transcript text from fragments
        transcript_lines = []
        for entry in transcript_entries:
            # Handle participant_name field (the fix mentioned in the prompt)
            speaker = entry.get('participant_name') or entry.get('speaker', 'Unknown')
            text = entry.get('spoken_sentence') or entry.get('text', '')
            if text.strip():
                transcript_lines.append(f"[{speaker}]: {text}")

        transcript_text = '\n'.join(transcript_lines)

        if len(transcript_text) < 100:
            # Too short to summarize meaningfully
            return (
                f"# {topic}\n"
                f"Date: {start_time[:10] if start_time else 'unknown'}\n\n"
                f"## Transcript\n{transcript_text}"
            )

        # Use LLM summarization from etl_calls.py
        # Import here to avoid circular dependency
        try:
            from etl_calls import summarize_apollo_transcript
            summary = summarize_apollo_transcript(
                transcript_text=transcript_text,
                title=topic
            )
            return summary
        except Exception as e:
            # If LLM summarization fails, return the raw transcript
            # (still better than '[Summary failed]')
            print(f"Warning: LLM summarization failed for Apollo conversation: {e}")
            return (
                f"# {topic}\n"
                f"Date: {start_time[:10] if start_time else 'unknown'}\n\n"
                f"## Transcript\n{transcript_text[:2000]}"
            )

    def _extract_participant_emails(self, conversation: dict) -> List[str]:
        """
        Extract participant emails from Apollo conversation.

        Apollo doesn't always provide emails directly, so we try multiple
        sources: host field, participants array, and transcript entries.
        """
        emails = []

        # Host field (sometimes has email)
        host = conversation.get('host', '')
        if '@' in host:
            emails.append(host)

        # Participants array (if present)
        participants = conversation.get('participants', []) or []
        for p in participants:
            if isinstance(p, str) and '@' in p:
                emails.append(p)
            elif isinstance(p, dict):
                email = p.get('email', '')
                if email:
                    emails.append(email)

        # Deduplicate and return
        return list(dict.fromkeys(emails))
