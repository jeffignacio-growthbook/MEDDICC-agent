"""
Strict-signature test double for LLMClient.

Why this exists
---------------
A plain unittest.mock.MagicMock accepts ANY attribute and ANY kwargs. So a
caller that passes a kwarg the real LLMClient.complete() rejects — model=,
temperature= — "passes" against a MagicMock while raising TypeError in
production. That exact gap kept the assessor's quality gate inert for two
days (the TypeError was swallowed into a constant 0.50 score) and let a
NameError-adjacent signature drift ship undetected.

A mock that stands in for a typed interface must enforce that interface, or
the test is only proving the mock works. StrictFakeLLMClient mirrors
complete()'s real signature — complete(messages, system=None,
max_tokens=1000) — so a drifted call site fails the test instead of failing
silently in production.

Use this anywhere a mock substitutes for LLMClient.
"""

from __future__ import annotations

import types


class StrictFakeLLMClient:
    """
    Test double whose complete() has LLMClient.complete()'s exact signature.

    complete(messages, system=None, max_tokens=1000) -> response

    Passing any other keyword (model=, temperature=, ...) raises TypeError —
    exactly what the real client does — so signature drift surfaces in the
    test rather than in production.

    Parameters
    ----------
    text   : str
        The .text of the returned response (usually a JSON string the caller
        will parse).
    raises : BaseException | None
        If set, complete() raises this instead of returning — for exercising
        a caller's exception / fallback path deliberately (not by accident).

    Attributes
    ----------
    calls  : list of {"messages", "system", "max_tokens"} recorded per call.
    called : True once complete() has been invoked at least once.
    """

    def __init__(self, text: str = "", raises: BaseException | None = None):
        self._text = text
        self._raises = raises
        self.calls: list[dict] = []

    def complete(self, messages, system=None, max_tokens=1000):
        self.calls.append(
            {"messages": messages, "system": system, "max_tokens": max_tokens}
        )
        if self._raises is not None:
            raise self._raises
        return types.SimpleNamespace(
            text=self._text, input_tokens=10, output_tokens=5
        )

    @property
    def called(self) -> bool:
        return bool(self.calls)
