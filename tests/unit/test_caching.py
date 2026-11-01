from __future__ import annotations

from flashrouter.services.caching import (
    CacheDecision,
    anchor_anthropic,
    anchor_openai,
    apply_cache_markers,
    cache_marker_count,
    resolve_cache_decision,
    strip_cache_markers,
)

CC = {"type": "ephemeral"}
CC1H = {"type": "ephemeral", "ttl": "1h"}


def _decision(*, active=True, strip=False, head="5m", tail="5m") -> CacheDecision:
    return CacheDecision("force" if active else "off", active, strip, head, tail)


def test_resolve_defaults_follow_protocol():
    anth = resolve_cache_decision(
        endpoint="messages",
        provider={"protocol": "anthropic-messages"},
        key={"cache_policy": "auto"},
    )
    assert anth.active and not anth.strip

    openai = resolve_cache_decision(
        endpoint="chat/completions",
        provider={"protocol": "openai-chat"},
        key={"cache_policy": "auto"},
    )
    assert not openai.active and openai.strip


def test_resolve_provider_opt_in_and_key_override():
    opted_in = resolve_cache_decision(
        endpoint="chat/completions",
        provider={"protocol": "openai-chat", "cache_markers": "anthropic"},
        key={"cache_policy": "auto"},
    )
    assert opted_in.active

    forced = resolve_cache_decision(
        endpoint="chat/completions",
        provider={"protocol": "openai-chat", "cache_markers": "none"},
        key={"cache_policy": "force"},
    )
    assert forced.active

    off = resolve_cache_decision(
        endpoint="messages",
        provider={"protocol": "anthropic-messages"},
        key={"cache_policy": "auto"},
        override="off",
    )
    assert not off.active and off.strip


def test_anchor_anthropic_marks_system_tools_and_assistant():
    body = {
        "model": "claude",
        "system": "You are an agent.",
        "tools": [
            {"name": "read", "input_schema": {"type": "object"}},
            {"name": "write", "input_schema": {"type": "object"}},
        ],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
            {"role": "user", "content": [{"type": "text", "text": "next"}]},
        ],
    }
    out = anchor_anthropic(body, _decision(head="1h"))
    assert out["system"][0]["cache_control"] == CC1H
    assert out["tools"][-1]["cache_control"] == CC1H
    assert out["messages"][1]["content"][-1]["cache_control"] == CC
    assert cache_marker_count(out) == 3
    assert "cache_control" not in body["tools"][-1]


def test_anchor_anthropic_marks_final_tool_results_as_fourth_slot():
    body = {
        "system": [{"type": "text", "text": "sys"}],
        "tools": [{"name": "read", "input_schema": {"type": "object"}}],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "do it"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "reading"},
                    {"type": "tool_use", "id": "t1", "name": "read", "input": {}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "data"}
                ],
            },
        ],
    }
    out = anchor_anthropic(body, _decision())
    assert out["messages"][1]["content"][-1]["cache_control"] == CC
    assert out["messages"][2]["content"][-1]["cache_control"] == CC
    assert cache_marker_count(out) == 4


def test_anchor_anthropic_skips_thinking_blocks():
    body = {
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "answer"},
                    {"type": "thinking", "thinking": "hmm"},
                ],
            },
        ]
    }
    out = anchor_anthropic(body, _decision())
    assert out["messages"][1]["content"][0]["cache_control"] == CC
    assert "cache_control" not in out["messages"][1]["content"][1]


def test_anchor_anthropic_respects_client_markers_and_caps_at_four():
    body = {
        "system": [
            {"type": "text", "text": "a", "cache_control": CC},
            {"type": "text", "text": "b", "cache_control": CC},
        ],
        "tools": [
            {"name": "a", "input_schema": {}, "cache_control": CC},
            {"name": "b", "input_schema": {}, "cache_control": CC},
        ],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "q", "cache_control": CC}]},
        ],
    }
    out = anchor_anthropic(body, _decision())
    assert cache_marker_count(out) == 4
    assert out["tools"][-1]["cache_control"] == CC
    assert "cache_control" not in out["system"][0]


def test_anchor_openai_marks_system_and_last_assistant():
    body = {
        "messages": [
            {"role": "system", "content": "You are an agent."},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
            {"role": "user", "content": "next"},
        ]
    }
    out = anchor_openai(body, _decision(head="1h"))
    assert out["messages"][0]["content"][0]["cache_control"] == CC1H
    assert out["messages"][2]["content"][0]["cache_control"] == CC
    assert "cache_control" not in out["messages"][3]


def test_apply_strips_when_off():
    body = {
        "system": [{"type": "text", "text": "s", "cache_control": CC}],
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "q", "cache_control": CC}],
            }
        ],
    }
    decision = _decision(active=False, strip=True)
    out = apply_cache_markers(body, endpoint="chat/completions", decision=decision)
    assert not cache_marker_count(out)
    assert cache_marker_count(body) == 2


def test_strip_cache_markers_leaves_passthrough_untouched():
    body = {"messages": [{"role": "user", "content": "hi"}]}
    assert strip_cache_markers(body) is body
