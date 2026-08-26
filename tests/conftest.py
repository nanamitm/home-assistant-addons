import asyncio

import pytest

# A test that stops making progress should fail with a traceback naming itself,
# not hang the whole run until the CI job is killed.
TEST_TIMEOUT = 15


@pytest.fixture
def run_async():
    """Run a coroutine to completion under a hard timeout."""

    def run(coro, timeout: float = TEST_TIMEOUT):
        async def guarded():
            return await asyncio.wait_for(coro, timeout)

        return asyncio.run(guarded())

    return run
