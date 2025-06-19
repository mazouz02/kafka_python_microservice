# Functions for Storing Raw Kafka Events
import logging

# Corrected imports
from .connection import get_database
from case_management_service.app.models import RawEventDB

logger = logging.getLogger(__name__)

async def add_raw_event_to_store(event_payload: dict, event_type: str = "KafkaMessageReceived") -> RawEventDB:
    db = await get_database()
    raw_event = RawEventDB(event_type=event_type, payload=event_payload)
    event_dict = raw_event.model_dump()

    await db.raw_events.insert_one(event_dict)
    logger.info(f"Raw event added to store with ID: {raw_event.id} of type: {event_type}")
    return raw_event
