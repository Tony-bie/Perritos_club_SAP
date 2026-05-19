"""Monitor mock DLQ file and auto-post feedback drafts to Feedback API."""
import os
import time
import json
import asyncio
from typing import Any
import aiohttp

from .dlq import DLQ_FILE
from ..core.logging_config import configure_logging

configure_logging()
import logging
logger = logging.getLogger(__name__)

FEEDBACK_API = os.getenv("FEEDBACK_API", "http://localhost:8001/feedback")
POLL_INTERVAL = float(os.getenv("DLQ_POLL_INTERVAL", "2"))


async def post_feedback(
	session: aiohttp.ClientSession,
	alert_id: str,
	label: str = "FP",
) -> None:
	"""Post one feedback draft to the feedback API."""
	payload = {"alert_id": alert_id, "label": label, "comment": "Auto-draft from DLQ autoposter"}
	async with session.post(FEEDBACK_API, json=payload) as resp:
		text = await resp.text()
		logger.info("Posted feedback for %s: %s %s", alert_id, resp.status, text)


async def monitor_and_post() -> None:
	"""Tail mock DLQ file and post feedback for detected failed alert IDs."""
	last_pos = 0
	if not os.path.exists(DLQ_FILE):
		open(DLQ_FILE, "a").close()
	async with aiohttp.ClientSession() as session:
		while True:
			try:
				with open(DLQ_FILE, "r", encoding="utf-8") as f:
					f.seek(last_pos)
					for line in f:
						try:
							item = json.loads(line)
							failed = item.get("failed", {})
							alert_id = failed.get("event_id") or failed.get("alert_id")
							if alert_id:
								await post_feedback(session, alert_id, label="FP")
						except Exception as e:
							logger.warning("Failed to parse DLQ line: %s", e)
					last_pos = f.tell()
			except Exception as e:
				logger.exception("Error reading DLQ file: %s", e)
			await asyncio.sleep(POLL_INTERVAL)


def main() -> None:
	"""CLI entrypoint for the DLQ auto-poster loop."""
	try:
		asyncio.run(monitor_and_post())
	except KeyboardInterrupt:
		print("Stopping DLQ autoposter")


if __name__ == "__main__":
	main()

