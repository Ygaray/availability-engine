from datetime import time, timedelta

import pytest_asyncio

from availability_engine.contracts import LocalInterval, Resource, Weekday
from availability_engine.storage.memory import InMemoryStore


@pytest_asyncio.fixture
async def store() -> InMemoryStore:
    return InMemoryStore()


@pytest_asyncio.fixture
async def sample_resource() -> Resource:
    return Resource(
        id="resource-1",
        capacity=1,
        operating_hours={
            Weekday.MONDAY: [LocalInterval(start=time(9, 0), end=time(17, 0))],
        },
        buffer=timedelta(minutes=0),
        timezone="America/Chicago",
        slot_duration=timedelta(minutes=30),
    )
