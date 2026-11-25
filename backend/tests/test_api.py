import uuid

import litellm


def uid(prefix="s"):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def chat(client, message, session_id=None, headers=None, **extra):
    body = {"session_id": session_id or uid(), "message": message, **extra}
    return client.post("/chat", json=body, headers=headers or {})


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_live_then_cache_hit_in_new_session(client, provider_calls):
    msg = f"What is the capital of France? {uid('q')}"
    first = chat(client, msg).json()
    second = chat(client, msg).json()  # new session, same first message
    assert first["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert first["metadata"]["key_id"] == "key_1"
    assert second["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second["metadata"]["key_id"] is None
    assert second["metadata"]["fallback_attempts"] == 0
    assert second["reply"] == first["reply"]
    assert second["metadata"]["input_tokens"] == first["metadata"]["input_tokens"]
    assert second["metadata"]["output_tokens"] == first["metadata"]["output_tokens"]


def test_different_message_is_not_cached(client):
    chat(client, f"hello {uid('a')}")
    other = chat(client, f"hello {uid('b')}").json()
    assert other["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_multi_turn_history_and_session_isolation(client):
    sid, other_sid = uid(), uid()
    chat(client, f"first {sid}", session_id=sid)
    second = chat(client, "second", session_id=sid).json()
    assert "[4 msgs]" in second["reply"]  # system + user + assistant + new user

    history = client.get(f"/sessions/{sid}/messages").json()
    assert [m["role"] for m in history["messages"]] == ["user", "assistant", "user", "assistant"]
    assert "metadata" in history["messages"][1]
    assert history["messages"][1]["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert "metadata" not in history["messages"][0]

    chat(client, f"other {other_sid}", session_id=other_sid)
    assert len(client.get(f"/sessions/{other_sid}/messages").json()["messages"]) == 2


def test_simulated_failover_to_key_2(client):
    r = chat(client, f"failover {uid('m')}", headers={"X-Simulate-Failure": "key_1=429"})
    assert r.status_code == 200
    meta = r.json()["metadata"]
    assert meta["key_id"] == "key_2"
    assert meta["fallback_attempts"] == 1
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert not r.json()["reply"].startswith("Error")


def test_simulation_bypasses_cache_so_failover_is_demonstrable(client):
    msg = f"same message {uid('m')}"
    chat(client, msg)
    r = chat(client, msg, headers={"X-Simulate-Failure": "key_1=500"}).json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert r["metadata"]["key_id"] == "key_2"


def test_all_keys_fail_returns_503_and_nothing_stored(client):
    sid = uid()
    r = chat(client, "will fail", session_id=sid, headers={"X-Simulate-Failure": "*=429"})
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}
    assert client.get(f"/sessions/{sid}/messages").status_code == 404


def test_two_listed_keys_fail_returns_503(client):
    r = chat(client, "x", headers={"X-Simulate-Failure": "key_1=429,key_2=500"})
    assert r.status_code == 503


def test_real_provider_429_falls_over(client, provider_calls):
    provider_calls.broken_keys["test-key-1"] = litellm.RateLimitError(
        message="quota exceeded", llm_provider="gemini", model="m"
    )
    r = chat(client, f"organic failover {uid('m')}")
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_2"
    assert r.json()["metadata"]["fallback_attempts"] == 1


def test_real_provider_all_keys_fail_503(client, provider_calls):
    for key in ("test-key-1", "test-key-2"):
        provider_calls.broken_keys[key] = litellm.InternalServerError(
            message="boom", llm_provider="gemini", model="m"
        )
    r = chat(client, f"everything down {uid('m')}")
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}


def test_validation_errors_return_422(client):
    assert client.post("/chat", json={"session_id": "s", "message": ""}).status_code == 422
    assert client.post("/chat", json={"session_id": "s", "message": "   "}).status_code == 422
    assert client.post("/chat", json={"message": "hi"}).status_code == 422
    assert client.post("/chat", json={"session_id": "", "message": "hi"}).status_code == 422
    assert client.post("/chat", json={"session_id": "s", "message": "x" * 4001}).status_code == 422
    bad = client.post("/chat", content="{not json", headers={"Content-Type": "application/json"})
    assert bad.status_code == 422
    assert "detail" in bad.json()


def test_unknown_session_404(client):
    r = client.get("/sessions/does-not-exist/messages")
    assert r.status_code == 404
    assert r.json() == {"detail": "session not found"}


def test_custom_system_prompt_is_applied(client, provider_calls):
    sid = uid()
    r = chat(client, f"hi {sid}", session_id=sid, system_prompt="Talk like a pirate.")
    assert r.status_code == 200
    # system prompt must not leak into the history endpoint
    msgs = client.get(f"/sessions/{sid}/messages").json()["messages"]
    assert all(m["role"] != "system" for m in msgs)


def test_cache_key_does_not_depend_on_which_api_key_answered(client):
    msg = f"key independent {uid('m')}"
    live = chat(client, msg, headers={"X-Simulate-Failure": "key_1=429"}).json()
    assert live["metadata"]["key_id"] == "key_2"
    cached = chat(client, msg).json()  # normally key_1 would answer
    assert cached["metadata"]["resolution_source"] == "LLM_CACHE"
    assert cached["reply"] == live["reply"]
