"""Consumer implementation supporting Kafka and local operation.

Uses centralized config and logs actions. When `aiokafka` is available the
consumer will connect to Kafka; otherwise this module can be used as a
reference for implementing a framework-specific consumer.
"""
import asyncio
import json
import logging
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..core.config import KAFKA_BOOTSTRAP, INGEST_TOPIC, DLQ_TOPIC
from ..core.logging_config import configure_logging
from .dlq import append_to_mock_dlq

configure_logging()
logger = logging.getLogger(__name__)


class ProcessingError(Exception):
	pass


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10),
	   retry=retry_if_exception_type(ProcessingError))
async def process_message(payload: dict) -> None:
	"""Placeholder processing logic (raise ProcessingError on simulated conditions)."""
	amount = payload.get("amount", 0)
	if amount > 100000:
		raise ProcessingError("Simulated transient failure for large amount")
	logger.info("Processed message %s amount=%s", payload.get("event_id"), amount)


async def consumer_loop_kafka() -> None:
	try:
		from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
	except Exception:
		logger.error("aiokafka not installed; kafka consumer unavailable")
		return

	consumer = AIOKafkaConsumer(INGEST_TOPIC, bootstrap_servers=KAFKA_BOOTSTRAP, group_id="sap_ingest_group")
	producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
	await consumer.start()
	await producer.start()
	try:
		async for msg in consumer:
			try:
				payload = json.loads(msg.value.decode("utf-8"))
				try:
					await process_message(payload)
				except Exception as e:
					logger.exception("Processing failed for %s; sending to DLQ", payload.get('event_id'))
					# fallback to writing to mock dlq file for persistence
					append_to_mock_dlq({"failed": payload, "error": str(e)})
					# also publish to DLQ topic if kafka is available
					try:
						await producer.send_and_wait(DLQ_TOPIC, json.dumps({"failed": payload, "error": str(e)}).encode("utf-8"))
					except Exception:
						logger.exception("Failed to publish to Kafka DLQ topic")
			except json.JSONDecodeError:
				logger.error("Invalid JSON message, appending to DLQ file")
				append_to_mock_dlq({"failed": {"raw": msg.value.decode('utf-8', errors='replace')}, "error": "invalid_json"})
	finally:
		await consumer.stop()
		await producer.stop()


def consumer_loop_local_stub():
	logger.info("Local consumer stub - use mock_run for local in-memory testing")


if __name__ == "__main__":
	# Prefer Kafka consumer if available
	try:
		asyncio.run(consumer_loop_kafka())
	except KeyboardInterrupt:
		logger.info("Consumer stopped")

