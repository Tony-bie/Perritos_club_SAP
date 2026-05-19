"""Ingest package: lightweight public API for producers, consumers and DLQ helpers.

This module re-exports the most commonly used classes and functions from the
submodules so callers can import a stable surface like:

	from backend.ingest import InMemoryBroker, produce_simulated_messages

Keep the lower-level modules available for advanced usage.
"""

from .mock_run import InMemoryBroker, producer as run_producer, consumer as run_consumer, process_message as process_message_local, main as run_mock
from .producer import produce_simulated_messages
from .consumer import consumer_loop_kafka, consumer_loop_local_stub, process_message as process_message_kafka
from .dlq import append_to_mock_dlq, read_mock_dlq, DLQ_FILE
from .dlq_inspector import inspect_mock_dlq, consume_kafka_dlq, post_feedback_example
from .dlq_autoposter import monitor_and_post

__all__ = [
	"InMemoryBroker",
	"run_producer",
	"run_consumer",
	"run_mock",
	"process_message_local",
	"produce_simulated_messages",
	"consumer_loop_kafka",
	"consumer_loop_local_stub",
	"process_message_kafka",
	"append_to_mock_dlq",
	"read_mock_dlq",
	"DLQ_FILE",
	"inspect_mock_dlq",
	"consume_kafka_dlq",
	"post_feedback_example",
	"monitor_and_post",
]

