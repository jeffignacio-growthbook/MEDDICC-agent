"""
Call intelligence and SDR metrics adapters for different platforms.

Call Intelligence:
- GongAdapter: Call transcripts and AI analysis (CallSourceAdapter interface)
- FirefliesAdapter: Call transcripts and summaries (CallSourceAdapter interface)
- ApolloAdapter: Video meeting transcripts (CallSourceAdapter interface)

SDR Metrics:
- ApolloDialerAdapter: Call metrics from Apollo.io
- SalesloftSequencerAdapter: Email and sequence metrics from Salesloft
- AircallDialerAdapter: Call metrics from Aircall

Each adapter implements a standard interface so ETL and agent
can work with any platform.
"""
import os
import sys
from pathlib import Path
from typing import List

# Ensure scripts path is available
sys.path.insert(0, str(Path(__file__).parent.parent))

from .gong_adapter import GongAdapter
from .apollo_dialer import ApolloDialerAdapter
from .salesloft_sequencer import SalesloftSequencerAdapter
from .aircall_dialer import AircallDialerAdapter

__all__ = [
    'GongAdapter',
    'ApolloDialerAdapter',
    'SalesloftSequencerAdapter',
    'AircallDialerAdapter',
    'get_call_sources',
    'get_source_priority',
]


def get_call_sources(config: dict = None) -> List:
    """
    Return list of CallSourceAdapter instances in priority order.

    Reads config/client.yaml call_sources block to determine which sources
    to instantiate and in what order. Sources that fail to initialize
    (missing credentials, API unreachable) are logged and skipped.

    Args:
        config: Optional config dict. If not provided, loads from
                config/client.yaml

    Returns:
        List of instantiated CallSourceAdapter objects in priority order.
        Empty list if no sources configured or all fail to initialize.

    Example config block:
        call_sources:
          primary: fireflies
          dialer: apollo
          priority: [fireflies, apollo]  # dedup order, best summary first

    Priority order matters: when multiple sources return a call for the same
    deal on the same date, the first source in the priority list wins. For
    GrowthBook: [fireflies, apollo] preserves the existing behavior where
    Fireflies summaries are preferred over Apollo's weaker summaries.
    """
    from adapters.call_source import CallSourceAdapter
    from adapters.fireflies_adapter import FirefliesAdapter
    from adapters.gong_adapter import GongAdapter
    from adapters.apollo_adapter import ApolloAdapter

    # Load config if not provided
    if config is None:
        import yaml
        config_path = Path(__file__).parent.parent.parent / "config" / "client.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

    # Get call_sources block from config
    call_sources_config = config.get('call_sources', {})

    if not call_sources_config:
        print("[WARN] No call_sources config block found, returning empty list")
        return []

    # Map source names to adapter classes
    ADAPTER_REGISTRY = {
        'fireflies': FirefliesAdapter,
        'gong': GongAdapter,
        'apollo': ApolloAdapter,
    }

    # Get priority list (determines dedup order)
    priority = call_sources_config.get('priority', [])

    if not priority:
        print("[WARN] call_sources.priority not set, returning empty list")
        return []

    # Instantiate adapters in priority order
    adapters = []

    for source_name in priority:
        adapter_class = ADAPTER_REGISTRY.get(source_name)

        if not adapter_class:
            print(f"[WARN] Unknown source '{source_name}' in priority list, skipping")
            continue

        # Try to instantiate the adapter
        try:
            adapter = adapter_class()

            # Test connection to verify credentials work
            if not adapter.test_connection():
                print(f"[WARN] {source_name} adapter failed connection test, skipping")
                continue

            adapters.append(adapter)
            print(f"[INFO] {source_name} adapter initialized successfully")

        except Exception as e:
            print(f"[WARN] Failed to initialize {source_name} adapter: {e}")
            continue

    if not adapters:
        print("[WARN] No call source adapters initialized successfully")

    return adapters


def get_source_priority(config: dict = None) -> List[str]:
    """
    Return the configured source priority list.

    Used by the deduplication function to determine which source wins
    when multiple sources return calls for the same deal/date.

    Args:
        config: Optional config dict. If not provided, loads from
                config/client.yaml

    Returns:
        List of source names in priority order, e.g. ['fireflies', 'apollo']
        Empty list if no priority configured.
    """
    if config is None:
        import yaml
        config_path = Path(__file__).parent.parent.parent / "config" / "client.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

    call_sources_config = config.get('call_sources', {})
    return call_sources_config.get('priority', [])
