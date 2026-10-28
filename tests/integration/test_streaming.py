from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from tests.conftest import (
    ControlledStream,
    RecordingSink,
    StaticStream,
    direct_proxy,
    make_settings,
)


def payload() -> dict:
    return {
        "model": "coding-fast",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
    }


@pytest.mark.anyio
async def test_first_chunk_is_forwarded_before_upstream_finishes(tmp_path: Path) -> None:
    stream = ControlledStream()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream=stream,
        )

    async with direct_proxy(make_settings(tmp_path), handler) as proxy:
        response = await proxy.stream(payload(), "req_1")
        iterator = response.body_iterator

        first = await asyncio.wait_for(anext(iterator), timeout=0.5)
        assert first == b"data: first\n\n"

        stream.release_second.set()
        second = await asyncio.wait_for(anext(iterator), timeout=0.5)
        assert second == b"data: second\n\n"

        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(iterator), timeout=0.5)

    assert stream.closed is True


@pytest.mark.anyio
async def test_closing_client_iterator_closes_upstream(tmp_path: Path) -> None:
    stream = ControlledStream()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream=stream,
        )

    async with direct_proxy(make_settings(tmp_path), handler) as proxy:
        response = await proxy.stream(payload(), "req_disconnect")
        iterator = response.body_iterator
        first = await asyncio.wait_for(anext(iterator), timeout=0.5)
        assert first == b"data: first\n\n"

        await asyncio.wait_for(iterator.aclose(), timeout=0.5)

    assert stream.closed is True


@pytest.mark.anyio
async def test_tool_call_fragments_are_not_rewritten(tmp_path: Path) -> None:
    chunks = [
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",',
        b'"function":{"name":"get_weather","arguments":"{\\"city\\":"}}]}}]}\n\n',
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":',
        b'{"arguments":"\\"Paris\\"}"}}]}}]}\n\n',
        b"data: [DONE]\n\n",
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream=StaticStream(chunks),
        )

    sink = RecordingSink()
    async with direct_proxy(make_settings(tmp_path), handler, sink=sink) as proxy:
        response = await proxy.stream(payload(), "req_tools")
        body = b"".join([chunk async for chunk in response.body_iterator])

    assert body == b"".join(chunks)
    assert sink.events[-1]["completed"] is True
    assert sink.events[-1]["upstream_model"] == "real-model"
