"""
Entry point of the system-level test suite.

Run with `python -m tests.system_level`.
"""

import asyncio

from tests.system_level.test_liveness import LivenessTest


async def main():
    """Entry point of the system-level test suite."""
    await LivenessTest().run()


if __name__ == "__main__":
    asyncio.run(main())
