#!/usr/bin/env python3
"""
Eval: LLMClient unified adapter
Tests provider normalization, response shape, and multi-turn correctness.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from unittest.mock import MagicMock, patch, PropertyMock
from llm_client import LLMClient, LLMResponse


def make_anthropic_response(text="test response",
                             stop_reason="end_turn",
                             input_tokens=100,
                             output_tokens=50):
    """Build a mock Anthropic SDK response."""
    mock_resp = MagicMock()
    mock_block = MagicMock()
    mock_block.text = text
    mock_block.type = "text"
    mock_resp.content = [mock_block]
    mock_resp.stop_reason = stop_reason
    mock_resp.usage.input_tokens = input_tokens
    mock_resp.usage.output_tokens = output_tokens
    return mock_resp


def make_openai_response(text="test response",
                          finish_reason="stop",
                          prompt_tokens=100,
                          completion_tokens=50):
    """Build a mock OpenAI SDK response."""
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = text
    mock_resp.choices[0].finish_reason = finish_reason
    mock_resp.usage.prompt_tokens = prompt_tokens
    mock_resp.usage.completion_tokens = completion_tokens
    return mock_resp


def test_anthropic_complete_returns_llm_response():
    mock_sdk_resp = make_anthropic_response("hello from claude")
    with patch("anthropic.Anthropic") as MockAnthropicClass:
        mock_instance = MockAnthropicClass.return_value
        mock_instance.messages.create.return_value = mock_sdk_resp
        client = LLMClient(model="claude-haiku-4-5-20251001",
                           provider="anthropic")
        client._sdk = mock_instance
        response = client.complete(
            messages=[{"role": "user", "content": "hi"}],
            system="You are helpful.",
            max_tokens=100,
        )
    assert isinstance(response, LLMResponse), "Must return LLMResponse"
    assert response.text == "hello from claude"
    assert response.stop_reason == "end_turn"
    assert response.input_tokens == 100
    assert response.output_tokens == 50
    assert response._provider == "anthropic"
    print("  ✓ Anthropic complete() returns LLMResponse")


def test_openai_complete_returns_llm_response():
    mock_sdk_resp = make_openai_response("hello from gpt")
    with patch("openai.OpenAI") as MockOpenAIClass:
        mock_instance = MockOpenAIClass.return_value
        mock_instance.chat.completions.create.return_value = mock_sdk_resp
        client = LLMClient(model="gpt-4o", provider="openai")
        client._sdk = mock_instance
        response = client.complete(
            messages=[{"role": "user", "content": "hi"}],
            system="You are helpful.",
            max_tokens=100,
        )
    assert isinstance(response, LLMResponse)
    assert response.text == "hello from gpt"
    assert response.stop_reason == "end_turn"   # mapped from 'stop'
    assert response.input_tokens == 100         # from prompt_tokens
    assert response.output_tokens == 50         # from completion_tokens
    assert response._provider == "openai"
    print("  ✓ OpenAI complete() returns LLMResponse")


def test_stop_reason_normalization():
    cases = [
        # (provider, raw_stop, expected_normalized)
        ("openai",    "stop",       "end_turn"),
        ("openai",    "length",     "max_tokens"),
        ("openai",    "tool_calls", "tool_use"),
        ("anthropic", "end_turn",   "end_turn"),
        ("anthropic", "max_tokens", "max_tokens"),
        ("anthropic", "tool_use",   "tool_use"),
    ]
    for provider, raw, expected in cases:
        if provider == "anthropic":
            mock_resp = make_anthropic_response(stop_reason=raw)
            client = LLMClient(model="claude-haiku-4-5-20251001",
                               provider="anthropic")
            with patch.object(client._sdk.messages, "create",
                              return_value=mock_resp):
                resp = client.complete([{"role": "user", "content": "x"}])
        else:
            mock_resp = make_openai_response(finish_reason=raw)
            client = LLMClient(model="gpt-4o", provider="openai")
            with patch.object(client._sdk.chat.completions, "create",
                              return_value=mock_resp):
                resp = client.complete([{"role": "user", "content": "x"}])
        assert resp.stop_reason == expected, \
            f"{provider} '{raw}' → expected '{expected}', got '{resp.stop_reason}'"
    print("  ✓ stop_reason normalized correctly for all providers")


def test_system_prompt_anthropic():
    """System passed as top-level kwarg to Anthropic messages.create."""
    mock_resp = make_anthropic_response()
    client = LLMClient(model="claude-haiku-4-5-20251001", provider="anthropic")
    captured = {}
    def capture_create(**kwargs):
        captured.update(kwargs)
        return mock_resp
    client._sdk.messages.create = capture_create
    client.complete(
        messages=[{"role": "user", "content": "hi"}],
        system="System prompt here",
    )
    assert captured.get("system") == "System prompt here", \
        "System must be top-level kwarg for Anthropic"
    assert not any(
        m.get("role") == "system" for m in captured.get("messages", [])
    ), "System must NOT be prepended as a message for Anthropic"
    print("  ✓ Anthropic: system passed as top-level kwarg")


def test_system_prompt_openai():
    """System prepended as first message for OpenAI."""
    mock_resp = make_openai_response()
    client = LLMClient(model="gpt-4o", provider="openai")
    captured = {}
    def capture_create(**kwargs):
        captured.update(kwargs)
        return mock_resp
    client._sdk.chat.completions.create = capture_create
    client.complete(
        messages=[{"role": "user", "content": "hi"}],
        system="System prompt here",
    )
    msgs = captured.get("messages", [])
    assert msgs[0]["role"] == "system", \
        "System must be first message for OpenAI"
    assert msgs[0]["content"] == "System prompt here"
    assert "system" not in captured, \
        "System must NOT be a top-level kwarg for OpenAI"
    print("  ✓ OpenAI: system prepended as first message")


def test_as_assistant_message_anthropic():
    """Anthropic: as_assistant_message preserves content blocks."""
    mock_raw = make_anthropic_response("claude response")
    resp = LLMResponse(
        text="claude response", stop_reason="end_turn",
        model="claude-haiku-4-5-20251001",
        input_tokens=10, output_tokens=5,
        raw=mock_raw, _provider="anthropic",
    )
    msg = resp.as_assistant_message()
    assert msg["role"] == "assistant"
    assert msg["content"] is mock_raw.content, \
        "Anthropic must preserve raw.content (list of blocks)"
    print("  ✓ Anthropic: as_assistant_message preserves content blocks")


def test_as_assistant_message_openai():
    """OpenAI: as_assistant_message returns plain string."""
    mock_raw = make_openai_response("gpt response")
    resp = LLMResponse(
        text="gpt response", stop_reason="end_turn",
        model="gpt-4o",
        input_tokens=10, output_tokens=5,
        raw=mock_raw, _provider="openai",
    )
    msg = resp.as_assistant_message()
    assert msg["role"] == "assistant"
    assert msg["content"] == "gpt response", \
        "OpenAI must return plain string content"
    assert isinstance(msg["content"], str), \
        "OpenAI content must be str, not list"
    print("  ✓ OpenAI: as_assistant_message returns plain string")


def test_content_block_list_normalized_for_openai():
    """
    When an Anthropic content block list appears in messages for an
    OpenAI call, it must be flattened to a plain string.
    This is the meddicc_agent multi-turn scenario.
    """
    mock_raw = make_openai_response("response")
    client = LLMClient(model="gpt-4o", provider="openai")
    captured = {}
    def capture_create(**kwargs):
        captured.update(kwargs)
        return mock_raw
    client._sdk.chat.completions.create = capture_create

    # Simulate Anthropic content blocks in an assistant message
    mock_block = MagicMock()
    mock_block.text = "previous assistant response"
    anthropic_content = [mock_block]

    client.complete(messages=[
        {"role": "user",      "content": "first question"},
        {"role": "assistant", "content": anthropic_content},  # blocks!
        {"role": "user",      "content": "follow-up"},
    ])

    msgs = captured.get("messages", [])
    assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1
    assert isinstance(assistant_msgs[0]["content"], str), \
        "Content blocks must be flattened to str for OpenAI"
    assert assistant_msgs[0]["content"] == "previous assistant response"
    print("  ✓ OpenAI: Anthropic content blocks flattened to string")


def test_fireworks_uses_custom_base_url():
    """Fireworks adapter initializes OpenAI client with Fireworks URL."""
    with patch("openai.OpenAI") as MockOpenAI:
        LLMClient(
            model="accounts/fireworks/models/deepseek-v3",
            provider="fireworks",
            api_key="test-key",
        )
        call_kwargs = MockOpenAI.call_args[1]
        assert call_kwargs.get("base_url") == \
            "https://api.fireworks.ai/inference/v1", \
            "Fireworks must set the correct base_url"
    print("  ✓ Fireworks: initializes with correct base URL")


def test_from_config_reads_provider():
    """from_config() instantiates the right SDK based on provider field."""
    config_fireworks = {
        "models": {
            "generator": {
                "name":     "accounts/fireworks/models/deepseek-v3",
                "provider": "fireworks",
            }
        }
    }
    config_anthropic = {
        "models": {
            "generator": {
                "name":     "claude-sonnet-4-6",
                "provider": "anthropic",
            }
        }
    }

    with patch("openai.OpenAI") as MockOpenAI, \
         patch("anthropic.Anthropic") as MockAnthropic:

        client_fw = LLMClient.from_config("generator", config_fireworks)
        assert client_fw.provider == "fireworks"
        assert client_fw.model == "accounts/fireworks/models/deepseek-v3"
        MockOpenAI.assert_called_once()

        MockOpenAI.reset_mock()

        client_an = LLMClient.from_config("generator", config_anthropic)
        assert client_an.provider == "anthropic"
        assert client_an.model == "claude-sonnet-4-6"
        MockAnthropic.assert_called()

    print("  ✓ from_config() instantiates correct provider from config")


if __name__ == "__main__":
    print("=" * 60)
    print("LLMClient Eval")
    print("=" * 60)
    tests = [
        test_anthropic_complete_returns_llm_response,
        test_openai_complete_returns_llm_response,
        test_stop_reason_normalization,
        test_system_prompt_anthropic,
        test_system_prompt_openai,
        test_as_assistant_message_anthropic,
        test_as_assistant_message_openai,
        test_content_block_list_normalized_for_openai,
        test_fireworks_uses_custom_base_url,
        test_from_config_reads_provider,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed += 1
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    if failed:
        raise SystemExit(1)
