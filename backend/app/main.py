import logging
import time
from contextlib import asynccontextmanager
from typing import Annotated, Optional

from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints

from . import db
from .config import settings
from .llm import AllProvidersUnavailable, complete, parse_simulation

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("chatbot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()  # schema is created automatically on startup
    yield


app = FastAPI(title="LLM Chatbot with Key Failover and Caching", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]
    system_prompt: Optional[Annotated[str, StringConstraints(max_length=4000)]] = None


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/health")
async def health():
    try:
        db.ping()
    except Exception:
        return JSONResponse(status_code=503, content={"detail": "database unavailable"})
    if not settings.api_keys:
        return JSONResponse(status_code=503, content={"detail": "key pool not loaded"})
    return {"status": "ok", "keys_configured": len(settings.api_keys), "cache_enabled": True}


@app.post("/chat")
async def chat(req: ChatRequest, x_simulate_failure: Optional[str] = Header(default=None)):
    started = time.perf_counter()

    system_prompt = (
        req.system_prompt or db.get_system_prompt(req.session_id) or settings.default_system_prompt
    )
    messages = (
        [{"role": "system", "content": system_prompt}]
        + db.get_history(req.session_id)
        + [{"role": "user", "content": req.message}]
    )
    simulated = (
        parse_simulation(x_simulate_failure) if settings.enable_failure_simulation else {}
    )

    try:
        result = await complete(messages, simulated)
    except AllProvidersUnavailable:
        # Nothing is written to history for a failed request.
        return JSONResponse(status_code=503, content={"detail": "all providers unavailable"})

    metadata = {
        "resolution_source": result.resolution_source,
        "model": settings.model,
        "latency_ms": max(1, int(round((time.perf_counter() - started) * 1000))),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "key_id": result.key_id,
        "fallback_attempts": result.fallback_attempts,
    }
    db.add_exchange(req.session_id, req.message, result.reply, metadata, req.system_prompt)
    return {"session_id": req.session_id, "reply": result.reply, "metadata": metadata}


@app.get("/sessions/{session_id}/messages")
async def session_messages(session_id: str):
    messages = db.get_messages(session_id)
    if messages is None:
        return JSONResponse(status_code=404, content={"detail": "session not found"})
    return {"session_id": session_id, "messages": messages}
