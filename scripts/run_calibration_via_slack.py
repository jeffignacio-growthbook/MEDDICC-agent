#!/usr/bin/env python3
"""
Wave 4 — Calibration Runner (Slack-based)

Posts canonical questions to Slack, collects agent responses via threads,
compares to verified values.

Architecture:
1. Post question to test Slack channel
2. Agent processes via webhook → Railway → Zapier → Slack response
3. Script polls thread for agent response
4. Compare response to verified value
"""
import os
import sys
import json
import yaml
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))

from supabase_client import select_all
from db import get_supabase


class SlackCalibrationRunner:
    def __init__(self):
        self.sb = get_supabase()
        self.slack_token = os.environ.get('SLACK_BOT_TOKEN')
        self.test_channel = os.environ.get('CALIBRATION_CHANNEL', 'C07PZ7ZDH0N')  # Default to test channel

        if not self.slack_token:
            raise ValueError("SLACK_BOT_TOKEN environment variable required")

        self.client = WebClient(token=self.slack_token)
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

    def post_question(self, question: str) -> Optional[str]:
        """
        Post question to Slack test channel.
        Returns thread_ts for tracking response.
        """
        try:
            result = self.client.chat_postMessage(
                channel=self.test_channel,
                text=question,
                username="Calibration Runner"
            )
            return result['ts']  # timestamp serves as thread identifier
        except SlackApiError as e:
            print(f"  Error posting to Slack: {e}")
            return None

    def wait_for_response(self, thread_ts: str, timeout: int = 30) -> Optional[Dict]:
        """
        Poll thread for agent response.
        Returns response dict or None if timeout.
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # Get thread replies
                result = self.client.conversations_replies(
                    channel=self.test_channel,
                    ts=thread_ts,
                    limit=10
                )

                messages = result['messages']

                # Skip first message (the question itself)
                # Look for bot response (will have bot_id or username matching agent)
                for msg in messages[1:]:
                    if msg.get('bot_id') or msg.get('username') == 'Deal Intelligence':
                        return {
                            'text': msg.get('text', ''),
                            'ts': msg.get('ts'),
                            'thread_ts': thread_ts
                        }

                # Wait before polling again
                time.sleep(2)

            except SlackApiError as e:
                print(f"  Error reading thread: {e}")
                return None

        print(f"  Timeout waiting for response (>{timeout}s)")
        return None

    def check_fallback_used(self, question: str) -> bool:
        """Check if this question triggered fallback in the logs."""
        rows = select_all(self.sb, 'fallback_log',
            columns='trigger,fast_path_attempted',
            filters=[('eq', 'question', question)]
        )
        if rows:
            return rows[-1].get('trigger') == 'success'
        return False

    def compare_to_verified(self, q_id: str, question: str, shape: str,
                           verified: Optional[Dict], response: Optional[Dict]) -> str:
        """
        Compare agent response to verified value.
        Returns 'correct', 'wrong', or 'unanswerable'.
        """
        if not response or not response.get('text'):
            return 'unanswerable'

        if not verified:
            return 'unanswerable'

        text = response['text']

        # Extract actual value from response based on shape
        actual = self._extract_value_from_response(text, shape)

        if actual is None:
            return 'unanswerable'

        # Compare based on shape type
        if shape == "count":
            expected = verified.get('count')
            if expected and abs(actual - expected) <= max(1, expected * 0.05):
                return 'correct'
            else:
                return 'wrong'

        elif shape in ["rep_attainment", "team_attainment"]:
            expected_pct = verified.get('attainment_pct')
            expected_won = verified.get('won_arr')

            if actual.get('attainment_pct') and expected_pct:
                if abs(actual['attainment_pct'] - expected_pct) <= 2.0:  # 2% tolerance
                    return 'correct'
                else:
                    return 'wrong'
            elif actual.get('won_arr') is not None and expected_won is not None:
                if abs(actual['won_arr'] - expected_won) <= max(1000, expected_won * 0.05):
                    return 'correct'
                else:
                    return 'wrong'

        elif shape == "conversion_rate":
            expected_pct = verified.get('conversion_pct')
            if actual.get('conversion_pct') and expected_pct:
                if abs(actual['conversion_pct'] - expected_pct) <= 1.5:
                    return 'correct'
                else:
                    return 'wrong'

        # Default: if we extracted something, consider it answered (even if we can't verify)
        return 'unanswerable'

    def _extract_value_from_response(self, text: str, shape: str) -> Optional[Any]:
        """Extract structured value from Slack text response."""
        if not text or len(text) < 10:
            return None

        import re

        # For counts
        if shape == "count":
            matches = re.findall(r'(\d+)\s+(?:deals?|companies|customers)', text, re.IGNORECASE)
            if matches:
                return int(matches[0])

        # For percentages
        if shape in ["rep_attainment", "team_attainment"]:
            # Look for attainment percentage
            pct_matches = re.findall(r'(\d+\.?\d*)\s*%', text)
            # Look for dollar amounts
            dollar_matches = re.findall(r'\$?([\d,]+)(?:K|k)?', text)

            result = {}
            if pct_matches:
                result['attainment_pct'] = float(pct_matches[0])
            if dollar_matches:
                # Clean up and convert (e.g., "197,400" or "197K")
                amt_str = dollar_matches[0].replace(',', '')
                result['won_arr'] = float(amt_str)

            return result if result else None

        if shape == "conversion_rate":
            pct_matches = re.findall(r'(\d+\.?\d*)\s*%', text)
            if pct_matches:
                return {'conversion_pct': float(pct_matches[0])}

        # For lists, check if response has structure
        if shape in ["list_with_count", "renewal_list"]:
            if '•' in text or '|' in text or '\n-' in text or '\n*' in text:
                count_match = re.search(r'(\d+)\s+(?:deals?|companies|customers)', text, re.IGNORECASE)
                if count_match:
                    return {'count': int(count_match.group(1))}

        return None

    def run(self):
        """Execute calibration via Slack."""
        questions = self.load_canonical_set()

        print("=" * 80)
        print("WAVE 4 — CALIBRATION RUN (via Slack)")
        print("=" * 80)
        print(f"Loaded {len(questions)} canonical questions")
        print(f"Test channel: {self.test_channel}")
        print(f"Bot: {self.slack_token[:10]}...")
        print()
        print("⚠️  This will post {len(questions)} questions to Slack")
        print("⚠️  Agent responses will be collected and compared to verified values")
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

            # Post to Slack
            thread_ts = self.post_question(question)
            if not thread_ts:
                print(f"      Status: ✗ Failed to post")
                print()
                continue

            # Wait for response
            response = self.wait_for_response(thread_ts, timeout=30)

            # Check fallback (requires small delay for log to write)
            time.sleep(1)
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
                'response': response.get('text')[:200] if response else None,
                'thread_ts': thread_ts,
                'used_fallback': used_fallback
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

        # Print summary
        total = self.results['total_count']
        correct = len(self.results['correct'])
        wrong = len(self.results['wrong'])
        unanswerable = len(self.results['unanswerable'])

        print("=" * 80)
        print("CALIBRATION SUMMARY")
        print("=" * 80)
        print()
        print(f"✓ CORRECT:        {correct:2d} / {total} ({correct/total*100:.1f}%)")
        print(f"✗ WRONG:          {wrong:2d} / {total} ({wrong/total*100:.1f}%)")
        print(f"? UNANSWERABLE:   {unanswerable:2d} / {total} ({unanswerable/total*100:.1f}%)")
        print()

        fallback_rate = self.results['fallback_count'] / total * 100 if total > 0 else 0
        print(f"Fallback rate: {self.results['fallback_count']}/{total} ({fallback_rate:.1f}%)")
        if fallback_rate > 40:
            print(f"  ⚠️  High fallback rate - semantic layer needs improvement")
        else:
            print(f"  ✓ Low fallback rate - handlers covering most questions")

        # Save detailed results
        output_dir = Path(__file__).parent.parent / 'outputs' / 'calibration'
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / f'calibration_slack_{timestamp}.json'

        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)

        print()
        print(f"Full results saved to: {output_file}")


if __name__ == '__main__':
    runner = SlackCalibrationRunner()
    runner.run()
