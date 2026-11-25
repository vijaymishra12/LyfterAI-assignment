import os
import tempfile

# Configure the app BEFORE importing it.
_tmp = tempfile.mkdtemp()
os.environ["LLM_API_KEYS"] = "test-key-1,test-key-2"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["ENABLE_FAILURE_SIMULATION"] = "true"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:3000"

import litellm  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

_real_acompletion = litellm.acompletion


@pytest.fixture
def provider_calls():
    """Replace the real provider with LiteLLM's mock_response (no network, no keys)."""
    calls = []
    broken_keys: dict[str, Exception] = {}

    async def fake(*args, **kwargs):
        calls.append(kwargs["api_key"])
        if kwargs["api_key"] in broken_keys:
            raise broken_keys[kwargs["api_key"]]
        n = len(kwargs["messages"])
        last = kwargs["messages"][-1]["content"]
        kwargs["mock_response"] = f"mock[{n} msgs]: {last}"
        return await _real_acompletion(*args, **kwargs)

    litellm.acompletion = fake
    fake.broken_keys = broken_keys
    fake.calls = calls
    yield fake
    litellm.acompletion = _real_acompletion


@pytest.fixture
def client(provider_calls):
    with TestClient(app) as c:
        yield c
