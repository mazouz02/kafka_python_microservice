# Event Store Logic (Saving and Retrieving Domain Events)
import logging
from typing import List, Optional

# Corrected imports
from .connection import get_database
from .schemas import StoredEventDB
from case_management_service.core.events import models as domain_event_models


logger = logging.getLogger(__name__)
EVENT_STORE_COLLECTION = "domain_events"

async def save_event(event_data: domain_event_models.BaseEvent) -> domain_event_models.BaseEvent:
    db = await get_database()

    latest_event_document = await db[EVENT_STORE_COLLECTION].find_one(
        {"aggregate_id": event_data.aggregate_id},
        sort=[("version", -1)]
    )
    latest_version = 0
    if latest_event_document:
        latest_version = latest_event_document.get("version", 0)

    if event_data.version <= latest_version and latest_version != 0 :
        logger.warning(
            f"Potential concurrency conflict for aggregate {event_data.aggregate_id}. "
            f"Event version {event_data.version}, latest version in DB {latest_version}."
        )

    stored_event_payload = event_data.payload.model_dump()

    # Ensure metadata is correctly dumped from the domain model's EventMetaData
    stored_metadata_dict = event_data.metadata.model_dump()

    stored_event_dict = StoredEventDB(
        event_id=event_data.event_id,
        event_type=event_data.event_type,
        aggregate_id=event_data.aggregate_id,
        timestamp=event_data.timestamp,
        version=event_data.version,
        payload=stored_event_payload,
        metadata=stored_metadata_dict # Use the dumped dict for StoredEventMetaData
    ).model_dump()

    await db[EVENT_STORE_COLLECTION].insert_one(stored_event_dict)
    logger.info(f"Event '{event_data.event_type}' (ID: {event_data.event_id}) saved for aggregate {event_data.aggregate_id} with version {event_data.version}.")

    return event_data

async def get_events_for_aggregate(aggregate_id: str) -> List[domain_event_models.BaseEvent]:
    db = await get_database()

    stored_events_cursor = db[EVENT_STORE_COLLECTION].find({"aggregate_id": aggregate_id}).sort("version", 1)

    deserialized_domain_events = []
    async for event_doc in stored_events_cursor:
        try:
            stored_event = StoredEventDB(**event_doc)
        except Exception as e:
            logger.error(f"Invalid event document structure in DB for aggregate {aggregate_id}, doc: {event_doc}. Error: {e}", exc_info=True)
            continue

        event_type_str = stored_event.event_type
        payload_dict = stored_event.payload

        DomainEventClass = getattr(domain_event_models, event_type_str + "Event", None)

        if DomainEventClass and hasattr(DomainEventClass, 'payload_model_name'):
            PayloadModelStr = getattr(DomainEventClass, 'payload_model_name')
            PayloadModelClass = getattr(domain_event_models, PayloadModelStr, None)

            if PayloadModelClass:
                try:
                    deserialized_payload = PayloadModelClass(**payload_dict)

                    # Reconstruct domain's EventMetaData from StoredEventMetaData dict
                    deserialized_metadata = domain_event_models.EventMetaData(**stored_event.metadata.model_dump())

                    domain_event_instance = DomainEventClass(
                        event_id=stored_event.event_id,
                        event_type=stored_event.event_type,
                        aggregate_id=stored_event.aggregate_id,
                        timestamp=stored_event.timestamp,
                        version=stored_event.version,
                        payload=deserialized_payload,
                        metadata=deserialized_metadata
                    )
                    if hasattr(domain_event_instance, 'payload_model_name'):
                         setattr(domain_event_instance, 'payload_model_name', PayloadModelStr)

                    deserialized_domain_events.append(domain_event_instance)
                except Exception as e:
                    logger.error(f"Error deserializing payload for event {stored_event.event_id} of type {event_type_str}: {e}", exc_info=True)
            else:
                logger.warning(f"Payload model '{PayloadModelStr}' not found for event type '{event_type_str}'. Aggregate: {aggregate_id}")
        else:
            logger.warning(f"Domain event class '{event_type_str}Event' or its 'payload_model_name' not found. Aggregate: {aggregate_id}")

    logger.info(f"Retrieved and deserialized {len(deserialized_domain_events)} events for aggregate {aggregate_id}.")
    return deserialized_domain_events
