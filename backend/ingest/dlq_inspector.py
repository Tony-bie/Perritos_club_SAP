import os
import asyncio
import json
import aiohttp
from typing import Any

from .dlq import DLQ_FILE, read_mock_dlq
from ..core.logging_config import configure_logging

configure_logging()
import logging
logger = logging.getLogger(__name__)
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
DLQ_TOPIC = os.getenv("DLQ_TOPIC", "sap_logs_dlq")
FEEDBACK_API = os.getenv("FEEDBACK_API", "http://localhost:8001/feedback")


def inspect_mock_dlq(limit: int = 100):
	items = read_mock_dlq(limit=limit)
	if not items:
		logger.info("No mock DLQ file found or it's empty.")
		return
	for item in items:
		logger.info(json.dumps(item, indent=2, default=str))


async def consume_kafka_dlq() -> None:
	try:
		from aiokafka import AIOKafkaConsumer
	except Exception:
		logger.error("aiokafka not installed; install with: pip install aiokafka")
		return
	consumer = AIOKafkaConsumer(DLQ_TOPIC, bootstrap_servers=KAFKA_BOOTSTRAP, group_id="dlq_inspector")
	await consumer.start()
	try:
		async for msg in consumer:
			try:
				item = json.loads(msg.value.decode("utf-8"))
			except Exception:
				item = {"raw": msg.value.decode("utf-8", errors="replace")}
			logger.info(json.dumps(item, indent=2, default=str))
	finally:
		await consumer.stop()


async def post_feedback_example(alert_id: str, label: str = "FP") -> None:
	payload = {"alert_id": alert_id, "label": label, "comment": "Auto-posted from DLQ inspector"}
	async with aiohttp.ClientSession() as s:
		async with s.post(FEEDBACK_API, json=payload) as resp:
			logger.info("posted feedback %s %s", resp.status, await resp.text())


def main() -> None:
	mode = os.getenv("DLQ_MODE", "mock")
	if mode == "mock":
		inspect_mock_dlq()
	else:
		asyncio.run(consume_kafka_dlq())


if __name__ == "__main__":
	main()

