"""
Tests for scope_mismatch detection in the assessor and composer.

Hard invariants:
  1. should_escalate() returns True only for scope_mismatch issues.
  2. scope_mismatch is not retryable via the retry path.
  3. scope_mismatch is not treated as a data_gap (always escalates).
  4. Other issue types do not trigger escalation.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from api.assessor import should_escalate, should_retry


class TestShouldEscalate:

    def test_scope_mismatch_triggers_escalation(self):
        """scope_mismatch → should_escalate True."""
        assessment = {"correct": False, "score": 0.3,
                      "issue": "scope_mismatch"}
        assert should_escalate(assessment) is True

    def test_other_issues_do_not_escalate(self):
        """Non-scope_mismatch issues do not escalate."""
        for issue in ("wrong_handler", "wrong_table", "missing_join",
                      "wrong_time_window", "should_be_dynamic",
                      "data_gap", "format_only", None):
            assessment = {"correct": False, "score": 0.3, "issue": issue}
            assert should_escalate(assessment) is False, \
                f"should_escalate should be False for issue={issue!r}"

    def test_skipped_assessment_does_not_escalate(self):
        """Budget-skipped assessments never trigger escalation."""
        assessment = {"correct": True, "score": 0.5,
                      "issue": "scope_mismatch", "skipped": True}
        assert should_escalate(assessment) is False

    def test_empty_assessment_does_not_escalate(self):
        assert should_escalate({}) is False

    def test_correct_true_does_not_escalate(self):
        """Even if issue is scope_mismatch, correct=True is not escalated."""
        assessment = {"correct": True, "score": 0.8,
                      "issue": "scope_mismatch"}
        assert should_escalate(assessment) is False


class TestScopeMismatchNotRetryable:

    def test_scope_mismatch_not_in_retry_path(self):
        """scope_mismatch must not go through the retry handler path."""
        assessment = {"correct": False, "score": 0.3,
                      "issue": "scope_mismatch"}
        # should_retry never fires for scope_mismatch — escalation handles it
        assert should_retry(assessment, iteration=0) is False
        assert should_retry(assessment, iteration=1) is False

    def test_retryable_issues_still_retry(self):
        """Existing retryable issues are not broken by the new type."""
        for issue in ("wrong_handler", "wrong_table", "missing_join",
                      "wrong_time_window", "should_be_dynamic"):
            assessment = {"correct": False, "score": 0.3, "issue": issue}
            assert should_retry(assessment, iteration=0) is True, \
                f"should_retry should be True for issue={issue!r}"

    def test_data_gap_still_not_retried(self):
        assessment = {"correct": False, "score": 0.3, "issue": "data_gap"}
        assert should_retry(assessment, iteration=0) is False
