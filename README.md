# Resilient LLM Chatbot (key failover + response caching)

React + FastAPI + SQLite chatbot. LiteLLM provides the key-pool failover and the response cache.

## 1. Live URLs

- Frontend: `<FRONTEND_URL>`
- Backend: `<BACKEND_URL>` (try `<BACKEND_URL>/health`)
- Repo: `<GITHUB_URL>`
- Demo video: `<VIDEO_URL>`

## 2. Run locally

### With Docker

```bash
cp .env.example .env      # then put 2+ real API keys in LLM_API_KEYS
make up                   # same as: docker compose up --build -d
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8000 (`/health`, `/chat`, `/sessions/{id}/messages`)
- Stop with `make down`. SQLite lives in the named volume `app_data` mounted at `/data`, so history survives restarts.

### Without Docker

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export LLM_API_KEYS=key1,key2 DATABASE_URL=sqlite:///./app.db ENABLE_FAILURE_SIMULATION=true
uvicorn app.main:app --port 8000

# frontend (new terminal)
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev         # http://localhost:3000
```

Backend tests (no API keys or network needed, the provider is mocked with LiteLLM's `mock_response`):

```bash
cd backend && pip install -r requirements-dev.txt && python -m pytest -q
```

## 3. Design decisions

**Key fallback.** `LLM_API_KEYS` is parsed into `key_1..key_N`. For each request the gateway calls `litellm.acompletion` with `key_1`; on any failure (429, quota, 5xx, timeout, auth error, empty completion) it moves to the next key and counts it in `fallback_attempts`. If every key fails the API returns `503 {"detail": "all providers unavailable"}` and nothing is saved. LiteLLM's own retries are disabled (`num_retries=0`) so failover is immediate and predictable. Keys are never returned or logged, only `key_id`.

**Failure simulation.** When `ENABLE_FAILURE_SIMULATION=true`, `X-Simulate-Failure: key_1=429,key_2=500` (or `*=429`) marks those keys as failed for that single request only. The surviving key makes a real LLM call. Simulated requests skip cache *reads* so the failover can always be demonstrated, even for a message that is already cached.

**Caching.** LiteLLM's built-in in-memory cache (`litellm.cache = Cache(type="local")`, `caching=True` per call). The cache key is derived by LiteLLM from the model and the full message list (system prompt + history + new message), not from the API key, so the same first message in a new session is a hit and any different message is a miss. A hit is detected with `response._hidden_params["cache_hit"]` and reported as `LLM_CACHE` with `key_id: null`, `fallback_attempts: 0`, the identical reply and the usage stored with the cached response. Trade-off: the cache is per-process and is cleared on restart (history in SQLite is not).

**SQLite session storage.** `messages` table exactly as specified, plus a small `sessions` table that stores the optional per-session system prompt. The schema is created on startup. The client sends only the new message; the backend rebuilds `[system] + stored history + [new user message]` for each call. A turn (user + assistant row) is written in one transaction only after a successful reply, so 422/503 requests never touch history. `DATABASE_URL` points at a file on a Docker volume.

**Tokens and latency.** `input_tokens` / `output_tokens` come from the LiteLLM `usage` of that one request (never a running total). `latency_ms` is measured on the server for the whole request.

## 4. Verification

Replace `$API` with `http://localhost:8000` or the live backend URL.

```bash
curl $API/health

# Live call
curl -s $API/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"s-1","message":"What is the capital of France?"}'

# Cache hit: same first message, NEW session -> LLM_CACHE, key_id null, lower latency
curl -s $API/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"s-2","message":"What is the capital of France?"}'

# Failover: key_1 fails, key_2 answers (key_id=key_2, fallback_attempts=1)
curl -s $API/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: key_1=429' \
  -d '{"session_id":"s-3","message":"Tell me a fun fact"}'

# All keys fail -> 503 {"detail":"all providers unavailable"}, nothing stored
curl -s -i $API/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: *=429' \
  -d '{"session_id":"s-4","message":"hello"}'

# Stored history, and 404 for an unknown session
curl -s $API/sessions/s-1/messages
curl -s -i $API/sessions/nope/messages
```

In the UI every assistant reply shows source, model, latency and that request's input/output tokens. The "Simulate key failure" field sends the `X-Simulate-Failure` header, and "New chat" starts a fresh session so you can see a cache hit.

## 5. Setup Used

- Editor: VS Code
- AI tools: Claude (code generation and review)
- Stack: React 18 + Vite, FastAPI, LiteLLM, SQLite, Docker / Docker Compose

## 6. Bonus features

- Simulate-failure field in the UI (sends `X-Simulate-Failure`) so failover can be demoed without curl.
- Optional per-session system prompt field, persisted per session.
- Backend test suite (14 tests) covering caching, failover, 503, 422, 404, multi-turn and session isolation.
- Non-root runtime containers; `make test` and `make logs` targets.
