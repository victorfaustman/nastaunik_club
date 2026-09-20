"""Ephemeral local fixture for browser QA. Never connects to the production database."""
import asyncio
from tests.test_tracks import TrackTests


async def main():
    fixture = TrackTests()
    await fixture.asyncSetUp()
    try:
        await fixture.create()
        print(fixture.client.make_url('/'), flush=True)
        await asyncio.Event().wait()
    finally:
        await fixture.asyncTearDown()


if __name__ == '__main__':
    asyncio.run(main())
