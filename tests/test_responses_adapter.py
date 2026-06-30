from responses_adapter import (
    openai_to_responses_response,
    resolve_responses_effort,
    responses_to_openai_body,
)


def test_resolve_responses_effort_keychain_model():
    assert resolve_responses_effort({"model": "keychain-high"}) == "high"


def test_resolve_responses_effort_reasoning():
    assert (
        resolve_responses_effort({"model": "gpt-5", "reasoning": {"effort": "low"}})
        == "low"
    )


def test_responses_to_openai_string_input():
    body = {
        "model": "keychain-medium",
        "input": "Hello",
        "instructions": "Be brief.",
    }
    oai = responses_to_openai_body(body)
    assert oai["messages"][0] == {"role": "system", "content": "Be brief."}
    assert oai["messages"][-1] == {"role": "user", "content": "Hello"}
    assert oai["model"] == "keychain-medium"


def test_responses_to_openai_function_turns():
    body = {
        "model": "keychain-medium",
        "input": [
            {"type": "message", "role": "user", "content": "Run it"},
            {
                "type": "function_call",
                "call_id": "call_abc",
                "name": "shell",
                "arguments": '{"cmd": ["ls"]}',
            },
            {
                "type": "function_call_output",
                "call_id": "call_abc",
                "output": "ok",
            },
        ],
    }
    oai = responses_to_openai_body(body)
    assert oai["messages"][0]["role"] == "user"
    assert oai["messages"][1]["tool_calls"][0]["function"]["name"] == "shell"
    assert oai["messages"][2]["role"] == "tool"


def test_openai_to_responses_message():
    oai = {
        "id": "chatcmpl-test",
        "choices": [
            {
                "message": {"role": "assistant", "content": "Hi there"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }
    resp = openai_to_responses_response(oai, {"model": "keychain-medium"})
    assert resp["object"] == "response"
    assert resp["status"] == "completed"
    assert resp["output"][0]["type"] == "message"
    assert resp["output"][0]["content"][0]["text"] == "Hi there"
    assert resp["usage"]["total_tokens"] == 8


def test_openai_to_responses_function_call():
    oai = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "shell",
                                "arguments": '{"cmd":["pwd"]}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    resp = openai_to_responses_response(oai, {"model": "gpt-5"})
    assert resp["output"][0]["type"] == "function_call"
    assert resp["output"][0]["name"] == "shell"
