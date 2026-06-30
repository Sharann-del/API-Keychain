"""OpenAI Responses API ↔ Chat Completions translation.

Codex CLI v0.136+ calls POST /v1/responses. The gateway routes through the
same OpenAI-compatible provider cascade as /v1/chat/completions.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

ROLE_MAP = {
    "user": "user",
    "assistant": "assistant",
    "system": "system",
    "developer": "system",
}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def resolve_responses_effort(body: Dict[str, Any]) -> str:
    model = (body.get("model") or "").lower()
    if model.startswith("keychain-"):
        tier = model.split("-", 1)[1]
        if tier in ("low", "medium", "high"):
            return tier
    reasoning = body.get("reasoning") or {}
    if isinstance(reasoning, dict):
        effort = reasoning.get("effort")
        if effort in ("low", "medium", "high"):
            return effort
    return "medium"


def _blocks_to_text(blocks: Any) -> str:
    if isinstance(blocks, str):
        return blocks
    if not isinstance(blocks, list):
        return ""
    parts: List[str] = []
    for block in blocks:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype in ("input_text", "output_text", "text"):
            parts.append(block.get("text", ""))
        elif btype == "summary_text":
            parts.append(block.get("text", ""))
    return "\n".join(p for p in parts if p)


def _input_message(role: str, content: Any) -> Optional[Dict[str, Any]]:
    text = _blocks_to_text(content)
    if not text.strip():
        return None
    mapped = ROLE_MAP.get(role, role)
    if mapped not in ("user", "assistant", "system"):
        mapped = "user"
    return {"role": mapped, "content": text}


def _convert_input_item(item: Any, messages: List[Dict[str, Any]]) -> None:
    if isinstance(item, str):
        msg = _input_message("user", item)
        if msg:
            messages.append(msg)
        return
    if not isinstance(item, dict):
        return

    itype = item.get("type")

    if itype in (None, "message") or ("role" in item and "content" in item):
        role = item.get("role", "user")
        msg = _input_message(role, item.get("content"))
        if msg:
            messages.append(msg)
        return

    if itype == "function_call":
        call_id = item.get("call_id") or item.get("id") or _new_id("call")
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": item.get("name", ""),
                            "arguments": item.get("arguments") or "{}",
                        },
                    }
                ],
            }
        )
        return

    if itype == "function_call_output":
        messages.append(
            {
                "role": "tool",
                "tool_call_id": item.get("call_id", ""),
                "content": item.get("output", ""),
            }
        )
        return

    if itype == "reasoning":
        summary = item.get("summary") or []
        text = _blocks_to_text(summary)
        if text.strip():
            messages.append({"role": "assistant", "content": text})
        return

    if itype == "item_reference":
        return


def responses_to_openai_body(body: Dict[str, Any]) -> Dict[str, Any]:
    messages: List[Dict[str, Any]] = []

    instructions = body.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        messages.append({"role": "system", "content": instructions.strip()})

    raw_input = body.get("input")
    if isinstance(raw_input, str):
        msg = _input_message("user", raw_input)
        if msg:
            messages.append(msg)
    elif isinstance(raw_input, list):
        for item in raw_input:
            _convert_input_item(item, messages)

    if not messages:
        messages.append({"role": "user", "content": ""})

    out: Dict[str, Any] = {"messages": messages}

    if body.get("model"):
        out["model"] = body["model"]
    if body.get("max_output_tokens") is not None:
        out["max_tokens"] = body["max_output_tokens"]
    if body.get("temperature") is not None:
        out["temperature"] = body["temperature"]
    if body.get("top_p") is not None:
        out["top_p"] = body["top_p"]
    if body.get("stream"):
        out["stream"] = True

    text_cfg = body.get("text")
    if isinstance(text_cfg, dict):
        fmt = text_cfg.get("format")
        if isinstance(fmt, dict):
            if fmt.get("type") == "json_schema":
                out["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": fmt.get("name") or "response",
                        "schema": fmt.get("schema") or {"type": "object"},
                        "strict": fmt.get("strict", True),
                    },
                }
            elif fmt.get("type") == "json_object":
                out["response_format"] = {"type": "json_object"}

    tools = body.get("tools")
    if isinstance(tools, list) and tools:
        openai_tools: List[Dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") == "function":
                openai_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.get("name", ""),
                            "description": tool.get("description") or "",
                            "parameters": tool.get("parameters")
                            or {"type": "object", "properties": {}},
                        },
                    }
                )
        if openai_tools:
            out["tools"] = openai_tools

    tool_choice = body.get("tool_choice")
    if tool_choice is not None:
        out["tool_choice"] = tool_choice

    return out


def _responses_usage(openai_usage: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    usage = openai_usage or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or prompt + completion)
    return {
        "input_tokens": prompt,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": completion,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": total,
    }


def _response_shell(
    request: Dict[str, Any],
    *,
    response_id: str,
    created_at: int,
    status: str,
    output: Optional[List[Dict[str, Any]]] = None,
    usage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    text_cfg = request.get("text")
    if not isinstance(text_cfg, dict):
        text_cfg = {"format": {"type": "text"}}
    return {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "status": status,
        "error": None,
        "incomplete_details": None,
        "instructions": request.get("instructions"),
        "max_output_tokens": request.get("max_output_tokens"),
        "model": request.get("model"),
        "output": output or [],
        "parallel_tool_calls": request.get("parallel_tool_calls", True),
        "previous_response_id": request.get("previous_response_id"),
        "reasoning": request.get("reasoning"),
        "store": request.get("store", False),
        "temperature": request.get("temperature", 1),
        "text": text_cfg,
        "tool_choice": request.get("tool_choice", "auto"),
        "tools": request.get("tools") or [],
        "top_p": request.get("top_p", 1),
        "truncation": request.get("truncation", "disabled"),
        "usage": usage,
        "user": request.get("user"),
        "metadata": request.get("metadata") or {},
    }


def _openai_message_to_output_items(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    content = message.get("content")
    if isinstance(content, str) and content:
        items.append(
            {
                "id": _new_id("msg"),
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": content, "annotations": []}
                ],
            }
        )
    for tc in message.get("tool_calls") or []:
        func = tc.get("function") or {}
        call_id = tc.get("id") or _new_id("call")
        items.append(
            {
                "id": tc.get("id") or _new_id("fc"),
                "type": "function_call",
                "call_id": call_id,
                "name": func.get("name", ""),
                "arguments": func.get("arguments") or "{}",
                "status": "completed",
            }
        )
    return items


def openai_to_responses_response(
    openai_resp: Dict[str, Any], request: Dict[str, Any]
) -> Dict[str, Any]:
    response_id = _new_id("resp")
    created_at = int(time.time())
    choice = (openai_resp.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    output = _openai_message_to_output_items(message)
    usage = _responses_usage(openai_resp.get("usage"))
    return _response_shell(
        request,
        response_id=response_id,
        created_at=created_at,
        status="completed",
        output=output,
        usage=usage,
    )


def _responses_sse(event: Dict[str, Any]) -> bytes:
    event_type = event.get("type", "")
    payload = json.dumps(event, separators=(",", ":"))
    if event_type:
        return f"event: {event_type}\ndata: {payload}\n\n".encode()
    return f"data: {payload}\n\n".encode()


async def convert_openai_stream_to_responses(
    openai_stream: AsyncIterator[bytes],
    request: Dict[str, Any],
) -> AsyncIterator[bytes]:
    """Translate Chat Completions SSE (plus keychain routing events) to Responses SSE."""
    response_id = _new_id("resp")
    created_at = int(time.time())
    shell = _response_shell(
        request,
        response_id=response_id,
        created_at=created_at,
        status="in_progress",
        output=[],
        usage=None,
    )

    yield _responses_sse({"type": "response.created", "response": shell})
    yield _responses_sse({"type": "response.in_progress", "response": shell})

    msg_id = _new_id("msg")
    msg_output_index = 0
    text_started = False
    text_done = False
    accumulated_text = ""
    finish_reason: Optional[str] = None
    usage: Dict[str, Any] = {}

    tool_states: Dict[int, Dict[str, Any]] = {}
    output_items: List[Dict[str, Any]] = []

    buffer = ""

    def _emit_text_start() -> List[bytes]:
        nonlocal text_started
        if text_started:
            return []
        text_started = True
        return [
            _responses_sse(
                {
                    "type": "response.output_item.added",
                    "output_index": msg_output_index,
                    "item": {
                        "id": msg_id,
                        "type": "message",
                        "role": "assistant",
                        "status": "in_progress",
                        "content": [],
                    },
                }
            ),
            _responses_sse(
                {
                    "type": "response.content_part.added",
                    "item_id": msg_id,
                    "output_index": msg_output_index,
                    "content_index": 0,
                    "part": {
                        "type": "output_text",
                        "text": "",
                        "annotations": [],
                    },
                }
            ),
        ]

    async for chunk in openai_stream:
        buffer += chunk.decode("utf-8", errors="replace")
        while "\n\n" in buffer:
            frame, buffer = buffer.split("\n\n", 1)
            event_name = ""
            data = ""
            for line in frame.replace("\r", "").split("\n"):
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data += line[5:].lstrip()

            if not data or data == "[DONE]":
                continue
            if event_name in ("routing", "done"):
                continue

            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue

            if isinstance(payload.get("usage"), dict):
                usage.update(payload["usage"])

            choices = payload.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            if choice.get("finish_reason"):
                finish_reason = choice.get("finish_reason")

            piece = delta.get("content")
            if isinstance(piece, str) and piece:
                for ev in _emit_text_start():
                    yield ev
                accumulated_text += piece
                yield _responses_sse(
                    {
                        "type": "response.output_text.delta",
                        "item_id": msg_id,
                        "output_index": msg_output_index,
                        "content_index": 0,
                        "delta": piece,
                    }
                )

            for tc_delta in delta.get("tool_calls") or []:
                idx = int(tc_delta.get("index", 0))
                state = tool_states.get(idx)
                if state is None:
                    state = {
                        "item_id": _new_id("fc"),
                        "call_id": tc_delta.get("id") or _new_id("call"),
                        "name": "",
                        "arguments": "",
                        "started": False,
                        "output_index": msg_output_index + 1 + idx,
                    }
                    tool_states[idx] = state

                if tc_delta.get("id"):
                    state["call_id"] = tc_delta["id"]
                func = tc_delta.get("function") or {}
                if func.get("name"):
                    state["name"] = func["name"]
                if func.get("arguments"):
                    state["arguments"] += func["arguments"]

                if not state["started"] and state["name"]:
                    state["started"] = True
                    yield _responses_sse(
                        {
                            "type": "response.output_item.added",
                            "output_index": state["output_index"],
                            "item": {
                                "id": state["item_id"],
                                "type": "function_call",
                                "status": "in_progress",
                                "call_id": state["call_id"],
                                "name": state["name"],
                                "arguments": "",
                            },
                        }
                    )

                arg_piece = func.get("arguments")
                if state["started"] and arg_piece:
                    yield _responses_sse(
                        {
                            "type": "response.function_call_arguments.delta",
                            "item_id": state["item_id"],
                            "output_index": state["output_index"],
                            "delta": arg_piece,
                        }
                    )

    if text_started and not text_done:
        text_done = True
        part = {
            "type": "output_text",
            "text": accumulated_text,
            "annotations": [],
        }
        yield _responses_sse(
            {
                "type": "response.output_text.done",
                "item_id": msg_id,
                "output_index": msg_output_index,
                "content_index": 0,
                "text": accumulated_text,
            }
        )
        yield _responses_sse(
            {
                "type": "response.content_part.done",
                "item_id": msg_id,
                "output_index": msg_output_index,
                "content_index": 0,
                "part": part,
            }
        )
        msg_item = {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [part],
        }
        output_items.append(msg_item)
        yield _responses_sse(
            {
                "type": "response.output_item.done",
                "output_index": msg_output_index,
                "item": msg_item,
            }
        )

    for idx in sorted(tool_states):
        state = tool_states[idx]
        if not state["started"]:
            continue
        item = {
            "id": state["item_id"],
            "type": "function_call",
            "call_id": state["call_id"],
            "name": state["name"],
            "arguments": state["arguments"] or "{}",
            "status": "completed",
        }
        output_items.append(item)
        yield _responses_sse(
            {
                "type": "response.function_call_arguments.done",
                "item_id": state["item_id"],
                "output_index": state["output_index"],
                "arguments": state["arguments"] or "{}",
            }
        )
        yield _responses_sse(
            {
                "type": "response.output_item.done",
                "output_index": state["output_index"],
                "item": item,
            }
        )

    if finish_reason == "length":
        status = "incomplete"
        incomplete_details = {"reason": "max_output_tokens"}
    else:
        status = "completed"
        incomplete_details = None

    completed = _response_shell(
        request,
        response_id=response_id,
        created_at=created_at,
        status=status,
        output=output_items,
        usage=_responses_usage(usage) if usage else _responses_usage({}),
    )
    completed["incomplete_details"] = incomplete_details
    yield _responses_sse({"type": "response.completed", "response": completed})
