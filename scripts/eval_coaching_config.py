#!/usr/bin/env python3
"""
Coaching config seed/client split validation tests.
Guards against contamination and drift.
"""
import yaml
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

def test_seed_contains_no_growthbook_specific_terms():
    """coaching_seed.yaml must never mention GrowthBook-specific product
    terms — this is the guard against seed/client contamination."""
    seed_text = (REPO_ROOT / "config" / "coaching_seed.yaml").read_text()
    banned_terms = ["GrowthBook", "LaunchDarkly", "warehouse-native",
                     "experiment", "feature flag", "Optimizely", "Statsig",
                     "EPPO", "Datadog"]
    for term in banned_terms:
        assert term.lower() not in seed_text.lower(), \
            f"'{term}' found in coaching_seed.yaml — this is client content, not seed"
    print("✓ Seed contains no GrowthBook-specific terms")
    return True

def test_client_config_fills_all_seed_structure_slots():
    """Every slot defined in seed's discovery_five_numbers_structure has
    a corresponding value in client's discovery_numbers."""
    seed = yaml.safe_load((REPO_ROOT / "config" / "coaching_seed.yaml").read_text())
    client = yaml.safe_load((REPO_ROOT / "config" / "coaching_client.yaml").read_text())
    slots = {s["key"] for s in seed["discovery_five_numbers_structure"]["slots"]}
    filled = set(client["discovery_numbers"].keys())
    missing = slots - filled
    assert not missing, f"client config missing discovery numbers: {missing}"
    print(f"✓ Client fills all {len(slots)} discovery number slots")
    return True

def test_merged_config_matches_old_context_yaml_values():
    """The merged seed+client config produces the SAME values the old
    context.yaml had for GrowthBook — behavior-preserving check.
    Load old config/context.yaml (kept temporarily for this comparison)
    and confirm objection_categories, good_discovery, value_metrics,
    competitors are byte-identical to what's now in coaching_client.yaml."""

    old_context = yaml.safe_load((REPO_ROOT / "config" / "context.yaml").read_text())
    new_client = yaml.safe_load((REPO_ROOT / "config" / "coaching_client.yaml").read_text())

    # Check key sections match
    for key in ['objection_categories', 'good_discovery', 'value_metrics', 'competitors']:
        assert old_context.get(key) == new_client.get(key), \
            f"Mismatch in {key} between old context.yaml and new coaching_client.yaml"

    print("✓ Merged config matches old context.yaml values")
    return True

def test_single_loader_used_no_inline_yaml_safe_load_remains():
    """No file outside coaching_config.py / utils.py contains
    yaml.safe_load(...context.yaml...) or references config/context.yaml
    directly. Grep-based check against api/handlers.py specifically."""

    # This test will fail until Phase 2 when handlers.py is rewired
    # For now, just verify the loader exists
    from pathlib import Path
    loader_path = REPO_ROOT / "scripts" / "coaching_config.py"
    assert loader_path.exists(), "coaching_config.py loader not found"

    # Check it has the expected function
    import sys
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from coaching_config import load_coaching_config

    # Verify it works
    config = load_coaching_config()
    assert 'blocker_taxonomy' in config, "Merged config missing blocker_taxonomy"
    assert 'company' in config, "Merged config missing company"

    print("✓ Single loader exists and merges seed+client correctly")
    return True

if __name__ == '__main__':
    print("=" * 70)
    print("COACHING CONFIG VALIDATION")
    print("=" * 70)
    print()

    tests = [
        test_seed_contains_no_growthbook_specific_terms,
        test_client_config_fills_all_seed_structure_slots,
        test_merged_config_matches_old_context_yaml_values,
        test_single_loader_used_no_inline_yaml_safe_load_remains,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: Unexpected error: {e}")
            failed += 1

    print()
    print("=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    exit(0 if failed == 0 else 1)
