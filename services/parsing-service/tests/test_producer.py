from __future__ import annotations

import pytest
from app.kafka.producer import KafkaProducer
from app.kafka.schemas import MessageEnvelope


class FakeAIOKafkaProducer:
    def __init__(self, bootstrap_servers: str) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.started = False
        self.sent: list[tuple[str, bytes]] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    async def send_and_wait(self, topic: str, payload: bytes) -> None:
        self.sent.append((topic, payload))


@pytest.fixture
def patched_producer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.kafka.producer.AIOKafkaProducer", FakeAIOKafkaProducer
    )


@pytest.mark.asyncio
async def test_producer_start(patched_producer: None) -> None:
    p = KafkaProducer("kafka:9092")
    await p.start()
    assert p._producer is not None
    assert p._producer.started is True


@pytest.mark.asyncio
async def test_producer_stop_after_start(patched_producer: None) -> None:
    p = KafkaProducer("kafka:9092")
    await p.start()
    await p.stop()
    assert p._producer is None


@pytest.mark.asyncio
async def test_producer_stop_without_start() -> None:
    p = KafkaProducer("kafka:9092")
    await p.stop()  # не должно падать


@pytest.mark.asyncio
async def test_producer_publish_without_start_raises() -> None:
    p = KafkaProducer("kafka:9092")
    env = MessageEnvelope(task_id="t1")
    with pytest.raises(RuntimeError):
        await p.publish("topic", env)


@pytest.mark.asyncio
async def test_producer_publish_sends_envelope(patched_producer: None) -> None:
    p = KafkaProducer("kafka:9092")
    await p.start()
    env = MessageEnvelope(task_id="t1", payload={"x": 1})
    await p.publish("topic-a", env)

    assert len(p._producer.sent) == 1
    topic, raw = p._producer.sent[0]
    assert topic == "topic-a"
    assert b"t1" in raw
    assert b"x" in raw


@pytest.mark.asyncio
async def test_producer_publish_multiple(patched_producer: None) -> None:
    p = KafkaProducer("kafka:9092")
    await p.start()
    for i in range(3):
        await p.publish("t", MessageEnvelope(task_id=f"id-{i}"))
    assert len(p._producer.sent) == 3