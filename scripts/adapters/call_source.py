"""
CallSourceAdapter — the interface every conversation-intelligence source
implements. Fireflies, Gong, Apollo present the SAME methods and return
the SAME normalized shape, so calling code never branches on which tool
it is. Adding a source = implement this + register in factory + config.
No caller changes.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class NormalizedCall:
    """Canonical call shape. Every adapter returns this regardless of the
    source's native format. This is what the calls table stores and the
    context builder consumes."""
    source: str                       # 'fireflies' | 'gong' | 'apollo'
    source_call_id: str
    title: str
    call_date: str                    # ISO 'YYYY-MM-DD'
    summary: str                      # rich, MEDDICC-ready, NEVER '[Summary failed]'
    duration_minutes: int = 0
    participant_emails: list = field(default_factory=list)
    participant_count: int = 0
    raw_transcript: Optional[str] = None
    summary_quality: str = "unknown"  # 'good' | 'empty' | 'corrupted'

    def to_row(self) -> dict:
        """Shape for the calls table upsert."""
        return {
            "source": self.source,
            "call_id": self.source_call_id,
            "title": self.title,
            "call_date": self.call_date,
            "summary": self.summary,
            "duration_minutes": self.duration_minutes,
            "participant_emails": self.participant_emails,
            "participant_count": self.participant_count,
            "summary_quality": self.summary_quality,
        }


class CallSourceAdapter(ABC):
    """Interface for a CI source. Recorders (Fireflies, Gong) have rich
    summaries and transcripts. Dialers (Apollo) have strong metadata but
    weak/absent summaries — the adapter is responsible for producing a
    usable summary so callers NEVER see '[Summary failed]'."""

    source_name: str = "unknown"

    @abstractmethod
    def fetch_recent(self, limit: int = 50, skip: int = 0,
                     since: Optional[datetime] = None) -> list:
        """Return recent calls as list[NormalizedCall]. Paginated."""

    @abstractmethod
    def fetch_by_company(self, company_name: str, max_results: int = 100,
                         since: Optional[datetime] = None) -> list:
        """Return calls for a company as list[NormalizedCall]."""

    @abstractmethod
    def test_connection(self) -> bool:
        """True if credentials work and the source is reachable."""

    def supports_transcripts(self) -> bool:
        """Recorders return True; used to decide whether to trust the
        summary or re-summarize."""
        return True
