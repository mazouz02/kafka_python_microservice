import datetime
from pydantic import BaseModel, Field
from typing import List, Optional
from pymongo import MongoClient
import logging
import os

# (Import BaseEvent and other specific events if needed for type hinting, from .domain_events)
from .domain_events import BaseEvent
from .event_projectors import dispatch_event_to_projectors # Add this import

# Configure logging
logger = logging.getLogger(__name__)

# --- Pydantic Models for Database Entities ---
class PersonDB(BaseModel):
    id: str = Field(default_factory=lambda: str(os.urandom(16).hex())) # Auto-generated ID
    case_id: str
    firstname: str
    lastname: str
    birthdate: Optional[str] = None
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)

class CaseManagementDB(BaseModel):
    id: str = Field(default_factory=lambda: str(os.urandom(16).hex())) # Auto-generated ID
    client_id: str
    version: str
    type: str
    # persons: List[PersonDB] # We'll store persons in a separate collection
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)

class RawEventDB(BaseModel):
    id: str = Field(default_factory=lambda: str(os.urandom(16).hex()))
    event_type: str # e.g., "KYC_RECEIVED"
    payload: dict # The actual Kafka message content
    received_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    processed_at: Optional[datetime.datetime] = None # To mark when it's processed into domain entities

# --- MongoDB Connection and Utility Functions ---
MONGO_DETAILS = os.environ.get("MONGO_DETAILS", "mongodb://localhost:27017")
client: Optional[MongoClient] = None
db = None

def connect_to_mongo():
    global client, db
    try:
        logger.info(f"Attempting to connect to MongoDB at {MONGO_DETAILS}...")
        client = MongoClient(MONGO_DETAILS)
        db = client.case_management_db # Database name
        client.admin.command('ping') # Verify connection
        logger.info("Successfully connected to MongoDB.")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        client = None
        db = None
        # Depending on the application's needs, you might want to raise the exception
        # or handle it by retrying, or exiting if the DB is critical.
        raise

def close_mongo_connection():
    global client
    if client:
        client.close()
        logger.info("MongoDB connection closed.")

async def get_database():
    if db is None:
        connect_to_mongo() # Ensure connection is established
    return db

# Example function to insert a case (will be expanded later)
async def add_case(case_data: CaseManagementDB) -> CaseManagementDB:
    if db is None:
        await get_database() # Ensure db is initialized
    if db is None: # Check again if db could not be initialized
        logger.error("Database not available for adding case.")
        raise ConnectionError("Database not available")

    case_dict = case_data.model_dump()
    case_dict["created_at"] = datetime.datetime.utcnow()
    case_dict["updated_at"] = datetime.datetime.utcnow()

    result = await db.cases.insert_one(case_dict) # "cases" is the collection name
    # Retrieve the inserted document to include DB-generated fields if any (though we use Pydantic defaults)
    # For this example, we assume our model's ID generation is sufficient.
    # created_case = await db.cases.find_one({"_id": result.inserted_id})
    # return CaseManagementDB(**created_case) if created_case else None
    logger.info(f"Case added with ID: {case_data.id}")
    return case_data # Return the original model with its generated ID

# Example function to insert a person (will be expanded later)
async def add_person(person_data: PersonDB) -> PersonDB:
    if db is None:
        await get_database()
    if db is None:
        logger.error("Database not available for adding person.")
        raise ConnectionError("Database not available")

    person_dict = person_data.model_dump()
    person_dict["created_at"] = datetime.datetime.utcnow()
    person_dict["updated_at"] = datetime.datetime.utcnow()

    result = await db.persons.insert_one(person_dict) # "persons" is the collection name
    logger.info(f"Person added with ID: {person_data.id} for case ID: {person_data.case_id}")
    return person_data

async def add_raw_event(event_payload: dict, event_type: str = "KafkaMessageReceived") -> RawEventDB:
    if db is None:
        await get_database()
    if db is None:
        logger.error("Database not available for adding raw event.")
        raise ConnectionError("Database not available")

    raw_event = RawEventDB(event_type=event_type, payload=event_payload)
    event_dict = raw_event.model_dump()

    result = await db.raw_events.insert_one(event_dict) # "raw_events" collection
    logger.info(f"Raw event added with ID: {raw_event.id} of type: {event_type}")
    return raw_event

# --- Event Store Functions ---
EVENT_STORE_COLLECTION = "domain_events"

async def save_event(event_data: BaseEvent) -> BaseEvent:
    if db is None:
        await get_database()
    if db is None:
        logger.error("Database not available for saving event.")
        raise ConnectionError("Database not available")

    # Check for optimistic concurrency:
    # Find the latest event for this aggregate to determine the next version.
    # This is a simplified check. A more robust check might be needed.
    latest_event_cursor = db[EVENT_STORE_COLLECTION].find_one(
        {"aggregate_id": event_data.aggregate_id},
        sort=[("version", -1)]
    )
    latest_version = 0
    if latest_event_cursor:
        # In MongoDB, find_one returns a dict or None
        latest_version = latest_event_cursor.get("version", 0)

    if event_data.version <= latest_version and latest_version != 0:
        # If we are not forcing a version (e.g. version = 1 for a new aggregate)
        # and the provided version is not greater than the latest, it's a conflict.
        # For new aggregates, event_data.version will be 1, latest_version will be 0.
        # This simple check assumes new events for existing aggregates increment correctly.
        # A more robust system would pass expected_version to save_event.
        logger.warning(
            f"Potential concurrency conflict for aggregate {event_data.aggregate_id}. "
            f"Event version {event_data.version}, latest version in DB {latest_version}."
        )
        # For now, we'll allow it but log. Production systems might raise an error.
        # Or, if the event_data.version is not explicitly set by handler, set it here:
        # event_data.version = latest_version + 1

    event_dict = event_data.model_dump()
    # Ensure timestamp is current if not already set (Pydantic default_factory handles this)
    event_dict["timestamp"] = event_data.timestamp

    await db[EVENT_STORE_COLLECTION].insert_one(event_dict)
    logger.info(f"Event '{event_data.event_type}' (ID: {event_data.event_id}) saved for aggregate {event_data.aggregate_id} with version {event_data.version}.")

    # Now, dispatch the event to projectors
    # The event_data here is already the specific type (e.g. CaseCreatedEvent instance)
    await dispatch_event_to_projectors(event_data)
    logger.debug(f"Event {event_data.event_id} dispatched to projectors.")

    return event_data # Return the original event_data

async def get_events_for_aggregate(aggregate_id: str) -> List[BaseEvent]:
    if db is None:
        await get_database()
    if db is None:
        logger.error("Database not available for retrieving events.")
        raise ConnectionError("Database not available")

    events_cursor = db[EVENT_STORE_COLLECTION].find({"aggregate_id": aggregate_id}).sort("version", 1)
    # events_data = await events_cursor.to_list(length=None) # Get all events

    # Deserialize into specific event types (this is tricky without knowing the type beforehand)
    # For now, return as BaseEvent or raw dicts. A proper event deserializer would be needed.
    # This is a simplified version:
    deserialized_events = []
    # Easiest to access specific event types:
    from . import domain_events # to access event classes like CaseCreatedEvent

    async for event_doc in events_cursor:
        event_type_str = event_doc.get("event_type")
        payload_data = event_doc.get("payload", {})
        # Attempt to find the correct Pydantic model for the event type
        # This part is tricky. The original instructions had a slight mismatch in how to use event_class.payload_model.
        # Assuming payload_model_name was added to event definitions as I did:
        event_class_name = event_type_str + "Event" # e.g., CaseCreatedEvent
        event_class = getattr(domain_events, event_class_name, None)

        current_event = None
        if event_class:
            try:
                # If specific event class found, try to parse its specific payload
                payload_model_name = getattr(event_class, "payload_model_name", None) # Get the payload model name string
                if payload_model_name:
                    payload_model_class = getattr(domain_events, payload_model_name, None)
                    if payload_model_class:
                        parsed_payload = payload_model_class(**payload_data)
                        event_doc["payload"] = parsed_payload # Replace dict payload with parsed model
                        current_event = event_class(**event_doc)
                    else: # Fallback if payload model class string is wrong
                        current_event = BaseEvent(**event_doc)
                else: # Fallback if specific event doesn't define payload_model_name
                     current_event = event_class(**event_doc) # Try to init with dict payload
            except Exception as e:
                logger.error(f"Error deserializing specific event {event_type_str}: {e}. Falling back to BaseEvent.")
                current_event = BaseEvent(**event_doc) # Fallback to BaseEvent
        else:
            # Fallback for unknown event types
            logger.warning(f"Unknown event type '{event_type_str}' found in event store for aggregate {aggregate_id}. Deserializing as BaseEvent.")
            current_event = BaseEvent(**event_doc)

        if current_event:
            deserialized_events.append(current_event)

    logger.info(f"Retrieved {len(deserialized_events)} events for aggregate {aggregate_id}.")
    return deserialized_events

# --- Lifecycle for FastAPI (optional, but good practice if using FastAPI) ---
# from fastapi import FastAPI
# def connect_app_db(app: FastAPI):
#     @app.on_event("startup")
#     async def startup_db_client():
#         connect_to_mongo()
#
#     @app.on_event("shutdown")
#     async def shutdown_db_client():
#         close_mongo_connection()
#
# if __name__ == '__main__':
#     # Example usage (requires an async context to run properly)
#     import asyncio
#     async def main():
#         connect_to_mongo()
#         if db:
#             test_case = CaseManagementDB(client_id="test_client", version="1.0", type="KYC_test")
#             created_case = await add_case(test_case)
#             if created_case:
#                 logger.info(f"Test case created: {created_case.model_dump_json(indent=2)}")
#                 test_person = PersonDB(case_id=created_case.id, firstname="Test", lastname="User")
#                 created_person = await add_person(test_person)
#                 if created_person:
#                     logger.info(f"Test person created: {created_person.model_dump_json(indent=2)}")
#         close_mongo_connection()
#
#     asyncio.run(main())
