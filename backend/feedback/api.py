"""Feedback API exposing endpoints to create/list manual labels for alerts."""
from contextlib import asynccontextmanager
import logging
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel

from .repo import init_db, insert_feedback, list_feedback
from ..core.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> Any:
    """Initialize feedback persistence before serving requests."""
    init_db()
    logger.info("Feedback DB initialized")
    yield


app = FastAPI(title="Feedback API", lifespan=lifespan)


class FeedbackItem(BaseModel):
    alert_id: str
    label: str
    comment: Optional[str] = None


@app.post("/feedback")
def post_feedback(item: FeedbackItem) -> dict[str, str]:
    """Persist a single feedback label entry."""
    insert_feedback(item.alert_id, item.label, item.comment)
    logger.info("Inserted feedback for %s label=%s", item.alert_id, item.label)
    return {"status": "ok", "alert_id": item.alert_id}


@app.get("/feedback")
def get_feedback(limit: int = 100) -> dict[str, list[dict[str, Any]]]:
    """List recent feedback entries ordered by newest first."""
    items = list_feedback(limit)
    return {"items": items}
