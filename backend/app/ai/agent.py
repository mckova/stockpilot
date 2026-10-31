"""Stockpilot Copilot: a Claude agent that operates the inventory through tools.

Design choices
--------------
* Manual agentic loop over the Messages API, because each turn must interleave
  with our DB session and the human-approval gate for anything that writes.
* Model ``claude-opus-5-5`` (override with STOCKPILOT_AI_MODEL). Thinking is
  adaptive by default on this model; effort is set explicitly.
* ``fallbacks: "default"``: if a safety classifier declines a turn, the API
  re-runs it on Anthropic's recommended fallback model instead of failing.
* The transcript is stored append-only exactly as the API returned it, so
  thinking blocks are replayed unchanged (required for preserved thinking).
* Tools are ``strict`` so arguments always match the schema.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.orm import Session

from ..models import AIConversation, User
from ..services.stock import StockError
from .tools import PROPOSAL_TOOLS, TOOLS, execute_tool

MODEL = os.getenv("STOCKPILOT_AI_MODEL", "claude-opus-5-5")
EFFORT = os.getenv("STOCKPILOT_AI_EFFORT", "medium")
MAX_STEPS = 12
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """You are Stockpilot Copilot, the operations analyst inside a multi-site inventory system \
(one central warehouse feeding retail stores, plus suppliers with lead times).

How to work:
- Ground every number in a tool result. Call tools before answering; never guess stock, costs or dates.
- Prefer one well-chosen tool call over many; call independent tools in parallel.
- You cannot change stock. To act, use a propose_* tool: it creates a proposal the user approves or rejects \
  in the UI. Say clearly that it awaits approval.
- Think like a planner: projected stock = available + incoming; reorder point = lead-time demand + safety stock; \
  FEFO means short-dated lots should be sold or moved first.
- Answer in the user's language (Hebrew or English). Lead with the conclusion, then a short table or bullets \
  with the key numbers, then any proposals. Use SKUs and site names, not internal ids."""


class MessagesClient(Protocol):  # the slice of anthropic.Anthropic().beta.messages we use
    def create(self, **kwargs: Any) -> Any: ...


class AIUnavailable(RuntimeError):
    pass


def default_client() -> MessagesClient:
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover
        raise AIUnavailable("the 'anthropic' package is not installed") from e
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        raise AIUnavailable("Set ANTHROPIC_API_KEY on the server to enable the AI copilot.")
    return anthropic.Anthropic().beta.messages


@dataclass
class TurnResult:
    text: str
    steps: list[dict] = field(default_factory=list)  # tool trace for the UI
    proposal_ids: list[int] = field(default_factory=list)
    stop_reason: str = ""
    model: str = MODEL


def _dump(block: Any) -> dict:
    return block if isinstance(block, dict) else block.model_dump(mode="json", exclude_none=True)


def run_turn(db: Session, conv: AIConversation, user: User, text: str, client: MessagesClient | None = None) -> TurnResult:
    client = client or default_client()
    messages: list[dict] = json.loads(conv.messages)
    messages.append({"role": "user", "content": f"[{user.name}, role {user.role.value}] {text}"})
    result = TurnResult(text="")

    for _ in range(MAX_STEPS):
        response = client.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
            output_config={"effort": EFFORT},
            cache_control={"type": "ephemeral"},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        conv.input_tokens += getattr(response.usage, "input_tokens", 0) or 0
        conv.output_tokens += getattr(response.usage, "output_tokens", 0) or 0
        result.model = getattr(response, "model", MODEL)
        content = [_dump(b) for b in response.content]
        messages.append({"role": "assistant", "content": content})
        result.stop_reason = response.stop_reason

        if response.stop_reason == "refusal":
            result.text = "I can't help with that request."
            break
        if response.stop_reason == "pause_turn":
            continue
        tool_uses = [b for b in content if b.get("type") == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            result.text = "\n\n".join(b["text"] for b in content if b.get("type") == "text").strip()
            break

        results = []
        for tu in tool_uses:  # all results go back in ONE user message
            step = {"tool": tu["name"], "input": tu["input"]}
            try:
                out = execute_tool(db, tu["name"], tu["input"], conv.id)
                if tu["name"] in PROPOSAL_TOOLS:
                    result.proposal_ids.append(out["proposal_id"])
                payload, is_error = json.dumps(out, default=str), False
            except StockError as e:
                payload, is_error = f"Error: {e}", True
            step["ok"] = not is_error
            result.steps.append(step)
            results.append({"type": "tool_result", "tool_use_id": tu["id"], "content": payload, **({"is_error": True} if is_error else {})})
        messages.append({"role": "user", "content": results})
    else:
        result.text = result.text or "I stopped after too many steps. Try a narrower question."

    if conv.title == "New conversation":
        conv.title = text[:80]
    conv.messages = json.dumps(messages)
    return result


def visible_history(conv: AIConversation) -> list[dict]:
    """User/assistant text only, for rendering a conversation again."""
    out = []
    for m in json.loads(conv.messages):
        if m["role"] == "user" and isinstance(m["content"], str):
            out.append({"role": "user", "text": m["content"].split("] ", 1)[-1]})
        elif m["role"] == "assistant":
            t = "\n\n".join(b["text"] for b in m["content"] if b.get("type") == "text").strip()
            if t and not any(b.get("type") == "tool_use" for b in m["content"]):
                out.append({"role": "assistant", "text": t})
    return out
