from __future__ import annotations

import pydantic_ai.models
import pytest

# Prevent accidental real model requests during tests.
pydantic_ai.models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on the asyncio backend, matching pydantic-ai."""
    return 'asyncio'
