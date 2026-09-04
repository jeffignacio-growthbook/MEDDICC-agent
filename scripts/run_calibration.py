#!/usr/bin/env python3
"""
Wave 4 — Calibration Runner

Executes the canonical question set against the agent and compares results
to verified values. Produces three lists:
- Correct: matched verified value within tolerance
- Wrong: disagrees with verified value
- Unanswerable: agent could not produce an answer

Also reports fallback rate as a health metric.
"""
import os
import sys
import json
import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import requests
from dotenv import load_dotenv

# Load environment
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))

from supabase_client import select_all
from db import get_supabase


class CalibrationRunner:
    def __init__(self):
        self.sb = get_supabase()
        self.api_url = os.getenv('RAILWAY_API_URL', 'http://localhost:8080')
        self.results = {
            'correct': [],
            'wrong': [],
            'unanswerable': [],
            'fallback_count': 0,
            'total_count': 0
        }

    def load_canonical_set(self) -> List[Dict]:
        """Load canonical questions from config."""
        config_path = Path(__file__).parent.parent / 'config' / 'canonical_questions.yaml'
        with open(config_path) as f:
            data = yaml.safe_load(f)
        return data['questions']

    def ask_agent(self, question: str) -> Optional[Dict]:
        """
        Ask the agent a question via the /slack/question endpoint.
        Returns the response or None if unreachable.
        """
        try:
            response = requests.post(
                f'{self.api_url}/slack/question',
                json={
                    'question': question,
                    'user_id': 'calibration_runner',
                    'thread_ts': f'calibration_{datetime.utcnow().timestamp()}'
                },
                timeout=30
            )

            if response.status_code == 200:
                return response.json()
            else:
                print(f"  API returned {response.status_code}: {response.text[:100]}")
                return None

        except requests.exceptions.RequestException as e:
            print(f"  API unreachable: {e}")
            return None

    def check_fallback_used(self, question: str) -> bool:
        """
        Check if this question triggered fallback in the logs.
        Returns True if it went to dynamic query tools.
        """
        # Check last 5 minutes of fallback_log for this question
        rows = select_all(self.sb, 'fallback_log',
            columns='trigger,fast_path_attempted',
            filters=[('eq', 'question', question)]
        )

        if rows:
            # Most recent entry for this question
            return rows[-1].get('trigger') == 'success'
        return False

    def compare_to_verified(self, q_id: str, question: str, shape: str,
                           verified: Optional[Dict], response: Dict) -> str:
        """
        Compare agent response to verified value.
        Returns 'correct', 'wrong', or 'unanswerable'.
        """
        if not response or 'error' in response:
            return 'unanswerable'

        if not verified:
            # No verified value to compare - mark as unanswerable for now
            # These need client input
            return 'unanswerable'

        # Extract actual value from response based on shape
        actual = self._extract_value_from_response(response, shape)

        if actual is None:
            return 'unanswerable'

        # Compare based on shape type
        if shape == "count":
            expected = verified.get('count')
            if expected and abs(actual - expected) <= max(1, expected * 0.05):  # 5% tolerance
                return 'correct'
            else:
                return 'wrong'

        elif shape in ["rep_attainment", "team_attainment"]:
            expected_pct = verified.get('attainment_pct')
            expected_won = verified.get('won_arr')

            # Try to extract percentage from response
            if actual.get('attainment_pct') and expected_pct:
                if abs(actual['attainment_pct'] - expected_pct) <= 1.0:  # 1% tolerance
                    return 'correct'
                else:
                    return 'wrong'
            elif actual.get('won_arr') and expected_won:
                if abs(actual['won_arr'] - expected_won) <= expected_won * 0.05:  # 5% tolerance
                    return 'correct'
                else:
                    return 'wrong'

        elif shape == "conversion_rate":
            expected_pct = verified.get('conversion_pct')
            if actual.get('conversion_pct') and expected_pct:
                if abs(actual['conversion_pct'] - expected_pct) <= 1.0:
                    return 'correct'
                else:
                    return 'wrong'

        elif shape == "retention_rate":
            expected_pct = verified.get('grr_pct')
            if actual.get('grr_pct') and expected_pct:
                if abs(actual['grr_pct'] - expected_pct) <= 1.0:
                    return 'correct'
                else:
                    return 'wrong'

        elif shape == "list_with_count":
            expected_count = verified.get('count')
            if actual.get('count') and expected_count:
                if abs(actual['count'] - expected_count) <= max(1, expected_count * 0.05):
                    return 'correct'
                else:
                    return 'wrong'

        # If we can't determine, mark as unanswerable
        return 'unanswerable'

    def _extract_value_from_response(self, response: Dict, shape: str) -> Optional[Any]:
        """
        Extract the relevant value from agent response based on expected shape.
        This is deliberately simple - real extraction would parse the text response.
        For now, we're checking if the agent CAN answer at all.
        """
        text = response.get('text', '')

        if not text or len(text) < 20:
            return None

        # For counts, look for numbers
        if shape == "count":
            import re
            # Look for patterns like "127 deals" or "Total: 127"
            matches = re.findall(r'(\d+)\s+deals?|Total:\s*(\d+)', text, re.IGNORECASE)
            if matches:
                for match in matches:
                    num = next((int(m) for m in match if m), None)
                    if num:
                        return num

        # For percentages, look for % patterns
        if shape in ["rep_attainment", "team_attainment", "conversion_rate", "retention_rate"]:
            import re
            matches = re.findall(r'(\d+\.?\d*)\s*%', text)
            if matches:
                return {'attainment_pct': float(matches[0])} if shape in ["rep_attainment", "team_attainment"] else {'conversion_pct': float(matches[0])} if shape == "conversion_rate" else {'grr_pct': float(matches[0])}

        # For lists, check if response contains actual data
        if shape in ["list_with_count", "renewal_list", "meddicc_filtered_list"]:
            # Very simple: if response has bullet points or table, assume it answered
            if '•' in text or '|' in text or '\n-' in text:
                # Try to extract count
                import re
                count_match = re.search(r'(\d+)\s+(deals?|companies|customers)', text, re.IGNORECASE)
                if count_match:
                    return {'count': int(count_match.group(1))}
                return {'count': 0}  # Has structure but no count found

        # If we got here and there's text, the agent at least tried to answer
        return {'raw_response': text[:100]}

    def run(self, dry_run: bool = False):
        """Execute calibration run."""
        questions = self.load_canonical_set()

        print("=" * 80)
        print("WAVE 4 — CALIBRATION RUN")
        print("=" * 80)
        print(f"Loaded {len(questions)} canonical questions")
        print(f"API endpoint: {self.api_url}")
        print()

        if dry_run:
            print("DRY RUN — Not calling API, just validating question set")
            print()

        for q in questions:
            q_id = q['id']
            question = q['question']
            shape = q['shape']
            verified = q.get('verified_value')

            print(f"[{q_id}] {question[:70]}")
            print(f"      Shape: {shape}")

            if q.get('duplicate_of'):
                print(f"      Skipping (duplicate of {q['duplicate_of']})")
                print()
                continue

            if dry_run:
                status = 'correct' if verified else 'unanswerable'
                print(f"      Status: {status} (dry run)")
                print()
                continue

            # Ask the agent
            response = self.ask_agent(question)

            # Check if fallback was used
            used_fallback = self.check_fallback_used(question)
            if used_fallback:
                self.results['fallback_count'] += 1
            self.results['total_count'] += 1

            # Compare to verified value
            status = self.compare_to_verified(q_id, question, shape, verified, response)

            result_entry = {
                'id': q_id,
                'question': question,
                'shape': shape,
                'verified': verified,
                'response': response,
                'used_fallback': used_fallback,
                'notes': q.get('notes', '')
            }

            if status == 'correct':
                self.results['correct'].append(result_entry)
                print(f"      Status: ✓ CORRECT")
            elif status == 'wrong':
                self.results['wrong'].append(result_entry)
                print(f"      Status: ✗ WRONG")
            else:
                self.results['unanswerable'].append(result_entry)
                print(f"      Status: ? UNANSWERABLE")

            print()

        self._print_summary()

    def _print_summary(self):
        """Print final summary and triage."""
        print("=" * 80)
        print("CALIBRATION SUMMARY")
        print("=" * 80)
        print()

        total = len(self.results['correct']) + len(self.results['wrong']) + len(self.results['unanswerable'])
        correct_pct = (len(self.results['correct']) / total * 100) if total > 0 else 0
        wrong_pct = (len(self.results['wrong']) / total * 100) if total > 0 else 0
        unanswerable_pct = (len(self.results['unanswerable']) / total * 100) if total > 0 else 0

        print(f"✓ CORRECT:       {len(self.results['correct']):3d} / {total} ({correct_pct:.1f}%)")
        print(f"✗ WRONG:         {len(self.results['wrong']):3d} / {total} ({wrong_pct:.1f}%)")
        print(f"? UNANSWERABLE:  {len(self.results['unanswerable']):3d} / {total} ({unanswerable_pct:.1f}%)")
        print()

        # Fallback rate - health metric
        if self.results['total_count'] > 0:
            fallback_pct = (self.results['fallback_count'] / self.results['total_count'] * 100)
            print(f"Fallback rate: {self.results['fallback_count']}/{self.results['total_count']} ({fallback_pct:.1f}%)")

            if fallback_pct > 40:
                print("  ⚠ WARNING: >40% fallback rate indicates badly configured semantic layer")
            elif fallback_pct > 20:
                print("  Note: Moderate fallback usage - some handlers may need tuning")
            else:
                print("  ✓ Low fallback rate - handlers covering most questions")
        print()

        # Detailed wrong list - this is what matters
        if self.results['wrong']:
            print("=" * 80)
            print("WRONG ANSWERS — Requires Triage")
            print("=" * 80)
            print()
            for entry in self.results['wrong']:
                print(f"[{entry['id']}] {entry['question']}")
                print(f"  Expected: {entry['verified']}")
                print(f"  Response: {entry['response'].get('text', 'N/A')[:100]}")
                print(f"  Triage into:")
                print(f"    [ ] Missing semantic fact")
                print(f"    [ ] Handler description problem")
                print(f"    [ ] Code defect")
                print()

        # Save results
        output_dir = Path(__file__).parent.parent / 'outputs' / 'calibration'
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / f'calibration_run_{timestamp}.json'

        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)

        print(f"Full results saved to: {output_file}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Run Wave 4 calibration')
    parser.add_argument('--dry-run', action='store_true',
                       help='Validate question set without calling API')
    args = parser.parse_args()

    runner = CalibrationRunner()
    runner.run(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
