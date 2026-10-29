"""Exercise a running FlashRouter with the official OpenAI Python SDK."""

from __future__ import annotations

import argparse
import os

from openai import OpenAI


def _print_tool_call(completion) -> None:
    message = completion.choices[0].message
    tool_calls = message.tool_calls or []
    if not tool_calls:
        print("  no tool call returned (model may not support tools)")
        return
    for call in tool_calls:
        print(f"  tool={call.function.name} arguments={call.function.arguments}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("FLASHROUTER_BASE_URL", "http://127.0.0.1:20128/v1"),
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("FLASHROUTER_API_KEY") or os.getenv("FLASHROUTER_GATEWAY_API_KEY"),
    )
    parser.add_argument("--model", default=os.getenv("FLASHROUTER_MODEL", "coding-fast"))
    args = parser.parse_args()

    if not args.api_key:
        parser.error("--api-key or FLASHROUTER_API_KEY is required")

    client = OpenAI(api_key=args.api_key, base_url=args.base_url)
    model = args.model

    print(f"Base URL: {args.base_url}")
    print(f"Model: {model}")

    print("\n[1] List models")
    models = client.models.list()
    model_ids = [item.id for item in models.data]
    print(f"  {len(model_ids)} model(s): {', '.join(model_ids)}")
    if model not in model_ids:
        print(f"  warning: {model!r} is not in /v1/models")

    print("\n[2] Non-streaming chat")
    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Reply with the single word: pong"}],
        max_tokens=16,
    )
    print(f"  {completion.choices[0].message.content!r}")

    print("\n[3] Streaming chat")
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Count from one to five."}],
        max_tokens=32,
        stream=True,
    )
    parts: list[str] = []
    for event in stream:
        delta = event.choices[0].delta.content if event.choices else None
        if delta:
            parts.append(delta)
    print(f"  {''.join(parts)!r}")

    print("\n[4] Tool call")
    tool_completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "What is the weather in Paris? Use the tool."}],
        max_tokens=64,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the current weather for a city",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                },
            }
        ],
        tool_choice="auto",
    )
    _print_tool_call(tool_completion)

    print("\nSmoke test completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
