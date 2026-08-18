"""
Call intelligence and SDR metrics adapters for different platforms.

Call Intelligence:
- GongAdapter: Call transcripts and AI analysis

SDR Metrics:
- ApolloDialerAdapter: Call metrics from Apollo.io
- SalesloftSequencerAdapter: Email and sequence metrics from Salesloft
- AircallDialerAdapter: Call metrics from Aircall

Each adapter implements a standard interface so ETL and agent
can work with any platform.
"""

from .gong_adapter import GongAdapter
from .apollo_dialer import ApolloDialerAdapter
from .salesloft_sequencer import SalesloftSequencerAdapter
from .aircall_dialer import AircallDialerAdapter

__all__ = [
    'GongAdapter',
    'ApolloDialerAdapter',
    'SalesloftSequencerAdapter',
    'AircallDialerAdapter'
]
