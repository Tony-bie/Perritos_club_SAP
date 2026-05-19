"""Kafka producer helper and local simulator for SAP messages."""
import asyncio
import json
import logging
import random
from typing import Optional

from ..core.config import KAFKA_BOOTSTRAP, INGEST_TOPIC
from ..core.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)


async def produce_simulated_messages(count: int = 10, delay: float = 0.5, topic: Optional[str] = None) -> None:
	"""Simulate producing messages. If running with Kafka, callers can replace this.

	This function intentionally avoids importing aiokafka so it can run in
	lightweight environments.
	"""
	topic = topic or INGEST_TOPIC
	for i in range(count):
		msg = {
			"event_id": f"evt_{i}",
			"user": random.choice(["user_a", "user_b", "user_c"]),
			"amount": random.choice([10, 100, 1000, 1000000]),
			"timestamp": asyncio.get_event_loop().time(),
		}
		# In production this would send to Kafka; for local tests we just log
		logger.info("Simulated produce to %s: %s", topic, msg["event_id"])
		await asyncio.sleep(delay)


if __name__ == "__main__":
	asyncio.run(produce_simulated_messages(20, 0.2))

