"""Run an in-memory producer/consumer with DLQ for local testing without Kafka.

This module provides a small in-memory broker useful for local tests and
development when Kafka/Docker is not available.
"""
import asyncio
import json
import random
import time
import logging
from typing import Optional

from .dlq import append_to_mock_dlq
from ..core.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)


class InMemoryBroker:
	def __init__(self) -> None:
		self.topic: asyncio.Queue = asyncio.Queue()
		self.dlq: list = []

	async def produce(self, message: dict) -> None:
		await self.topic.put(message)

	async def consume(self) -> dict:
		return await self.topic.get()

	def send_to_dlq(self, message: dict, error: Optional[str] = None) -> None:
		item = {"failed": message, "error": error, "ts": time.time()}
		self.dlq.append(item)
		append_to_mock_dlq(item)
		logger.info("Appended message %s to DLQ", message.get("event_id"))


async def producer(broker: InMemoryBroker, count: int = 20, delay: float = 0.2, force_fail_at: Optional[int] = None) -> None:
	for i in range(count):
		amount = random.choice([10, 100, 1000, 1000000])
		if force_fail_at is not None and i == force_fail_at:
			amount = 1000000
		msg = {
			"event_id": f"evt_{i}",
			"user": random.choice(["user_a", "user_b", "user_c"]),
			"amount": amount,
			"timestamp": time.time(),
		}
		await broker.produce(msg)
		logger.info("Produced %s amount=%s", msg["event_id"], msg["amount"])
		await asyncio.sleep(delay)


async def process_message(payload: dict) -> None:
	"""Simulated processing: raise on large amounts to test retry/DLQ."""
	amount = payload.get("amount", 0)
	if amount > 100000:
		raise RuntimeError("simulated transient processing failure")
	await asyncio.sleep(0.05)
	logger.info("Processed %s amount=%s", payload.get("event_id"), amount)


async def consumer(broker: InMemoryBroker, max_retries: int = 3) -> None:
	while True:
		msg = await broker.consume()
		attempt = 0
		backoff = 0.5
		last_exc: Optional[Exception] = None
		while attempt < max_retries:
			try:
				await process_message(msg)
				break
			except Exception as e:
				last_exc = e
				attempt += 1
				logger.warning("Attempt %d failed for %s: %s", attempt, msg.get("event_id"), e)
				await asyncio.sleep(backoff)
				backoff *= 2
		else:
			logger.error("Sending to DLQ %s after %d attempts", msg.get("event_id"), max_retries)
			broker.send_to_dlq(msg, error=str(last_exc))


async def main(count: int = 20, delay: float = 0.2, force_fail_at: Optional[int] = None) -> None:
	broker = InMemoryBroker()
	prod = asyncio.create_task(producer(broker, count=count, delay=delay, force_fail_at=force_fail_at))
	cons = asyncio.create_task(consumer(broker))
	await prod
	await asyncio.sleep(2)
	if broker.dlq:
		logger.info("DLQ entries: %d", len(broker.dlq))
		for item in broker.dlq:
			logger.info("DLQ item: %s", json.dumps(item))
	cons.cancel()
	try:
		await cons
	except Exception:
		pass


if __name__ == "__main__":
	asyncio.run(main())
