# Tutorial 4: MongoDB Interaction

This tutorial explores how the Case Management Microservice interacts with MongoDB, which serves as its primary data store for both the Event Store and the queryable Read Models. We use the `pymongo` driver along with Pydantic for data modeling and validation at the database interaction layer.

## 1. MongoDB Connection Management (`infrastructure/database/connection.py`)

A centralized module handles the connection to MongoDB.

*   **Configuration:** The MongoDB connection URI (`MONGO_DETAILS`) and database name (`DB_NAME`) are sourced from `app/config.py:AppSettings`.
*   **Connection Function (`connect_to_mongo()`):**
    *   Initializes the `MongoClient` using `MONGO_DETAILS`.
    *   Pings the admin database to verify the connection.
    *   Sets a global `db` variable to the specific database instance (e.g., `client[settings.DB_NAME]`).
    *   Raises a `ConnectionError` if connection fails.
*   **Closing Connection (`close_mongo_connection()`):** Closes the MongoDB client.
*   **Accessing Database Instance (`async def get_database()`):**
    *   Provides an asynchronous way to get the current database instance.
    *   If the connection isn't established, it attempts to call `connect_to_mongo()`. This is useful for components that need a DB instance on demand, though explicit connection at application startup (as done in `app/main.py`) is preferred.
*   **Lifecycle Management:** `connect_to_mongo()` and `close_mongo_connection()` are typically called during the FastAPI application's startup and shutdown events, respectively.

```python
# Snippet from infrastructure/database/connection.py
from case_management_service.app.config import settings
from pymongo import MongoClient
from typing import Optional # Ensure Optional is imported

client: Optional[MongoClient] = None
db = None # Will hold the database instance (e.g., from client[settings.DB_NAME])

def connect_to_mongo():
    global client, db
    # ... (connection logic, ping, set db) ...

async def get_database():
    global db # client is also global and used by connect_to_mongo
    if db is None:
        connect_to_mongo()
    # ... (error if still None) ...
    return db
```

## 2. Pydantic Schemas for Database Documents (`infrastructure/database/schemas.py`)

Pydantic models define the structure of documents stored in MongoDB, providing data validation and serialization benefits even at the database layer.

*   **`StoredEventDB`**: Defines how domain events are structured when persisted in the `domain_events` collection (the Event Store).
    *   Key fields: `event_id`, `event_type`, `aggregate_id`, `timestamp`, `version`, `payload: Dict[str, Any]` (the domain event's specific payload is stored as a dictionary), `metadata`.
    ```python
    # Snippet from infrastructure/database/schemas.py
    from pydantic import BaseModel, Field
    from typing import Dict, Any, Optional # Ensure all are imported
    import uuid # For default_factory
    import datetime # For default_factory

    class StoredEventMetaData(BaseModel): # Assuming this is also defined
        correlation_id: Optional[str] = None
        causation_id: Optional[str] = None

    class StoredEventDB(BaseModel):
        event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
        # ... other common event fields ...
        payload: Dict[str, Any]
        metadata: StoredEventMetaData = Field(default_factory=StoredEventMetaData)
    ```
*   **Read Model Schemas**: These define the structure for query-optimized data. Each typically corresponds to a separate MongoDB collection.
    *   `CaseManagementDB`: For the `cases` collection.
    *   `PersonDB`: For the `persons` collection.
    *   `CompanyProfileDB`: For the `companies` collection.
    *   `BeneficialOwnerDB`: For the `beneficial_owners` collection.
    *   `RequiredDocumentDB`: For the `document_requirements` collection.
    *   These models include fields relevant for querying and display, often denormalized from multiple domain events. They also include `id`, `created_at`, and `updated_at` fields.
    ```python
    # Example: Snippet from infrastructure/database/schemas.py
    from case_management_service.infrastructure.kafka.schemas import AddressData # Example if AddressData is used

    class CompanyProfileDB(BaseModel):
        id: str # company_id
        registered_name: str
        # ... other company fields ...
        registered_address: AddressData # Embedded Pydantic model
        created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
        updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    ```
*   **`RawEventDB`**: Schema for storing raw, successfully decoded Kafka messages in the `raw_events` collection for auditing.

## 3. Event Store Operations (`infrastructure/database/event_store.py`)

This module implements the persistence and retrieval logic for domain events, forming the Event Sourcing mechanism.

*   **`EVENT_STORE_COLLECTION = "domain_events"`**: Defines the MongoDB collection name.
*   **`async def save_event(event_data: domain_event_models.BaseEvent)`**:
    1.  Takes a domain event object (from `core/events/models.py`) as input. These domain event objects have their `payload` attribute as a typed Pydantic model.
    2.  Performs a simplified optimistic concurrency check by querying the latest version of an event for the given `aggregate_id`.
    3.  **Serialization for Storage:** Transforms the input domain event into the `StoredEventDB` format. This crucially involves serializing the domain event's typed Pydantic `payload` into a dictionary using `event_data.payload.model_dump()`. The `event_data.metadata` is also dumped.
    4.  Inserts the resulting dictionary (after validating with `StoredEventDB(...).model_dump()`) into the `EVENT_STORE_COLLECTION`.
    ```python
    # Simplified snippet from infrastructure/database/event_store.py
    # Assuming domain_event_models and StoredEventDB are correctly imported
    async def save_event(event_data: domain_event_models.BaseEvent) -> domain_event_models.BaseEvent:
        db = await get_database()
        # ... (optimistic concurrency check) ...

        stored_event_payload = event_data.payload.model_dump()
        # Assuming StoredEventMetaData is compatible or also dumped from domain_event_models.EventMetaData
        stored_metadata_dict = event_data.metadata.model_dump()

        stored_event_for_db = StoredEventDB(
            event_id=event_data.event_id,
            event_type=event_data.event_type,
            aggregate_id=event_data.aggregate_id,
            timestamp=event_data.timestamp,
            version=event_data.version,
            payload=stored_event_payload,
            metadata=stored_metadata_dict # Use the dumped dict
        )
        await db[EVENT_STORE_COLLECTION].insert_one(stored_event_for_db.model_dump())
        return event_data
    ```
*   **`async def get_events_for_aggregate(aggregate_id: str)`**:
    1.  Retrieves all documents from `EVENT_STORE_COLLECTION` matching the `aggregate_id`, sorted by `version`.
    2.  **Deserialization from Storage:** For each retrieved document (which is a dictionary adhering to `StoredEventDB`):
        *   It first validates the document against the `StoredEventDB` Pydantic model.
        *   Then, it dynamically determines the specific domain event class (e.g., `CaseCreatedEvent`) using the `event_type` string stored in the document (e.g., "CaseCreated").
        *   It uses the `payload_model_name` attribute from the domain event class (e.g., "CaseCreatedEventPayload") to find the corresponding Pydantic model for the payload.
        *   The stored dictionary `payload` is then parsed into this specific payload Pydantic model.
        *   Finally, an instance of the specific domain event class is created with its correctly typed payload.
    3.  Returns a list of these fully deserialized domain event objects.

## 4. Read Model Operations

These operations are primarily handled by projectors calling functions in modules like `infrastructure/database/read_models.py` and `infrastructure/database/document_requirements_store.py`.

*   **Updating Read Models (Upserts):**
    *   Functions like `upsert_case_read_model(case_data: CaseManagementDB)`, `upsert_company_read_model(company_data: CompanyProfileDB)\`, etc., are used by event projectors.
    *   They typically take a Pydantic DB schema object (e.g., `CaseManagementDB`) as input.
    *   They serialize this object to a dictionary using `.model_dump()`.
    *   They use MongoDB's `replace_one({"id": ...}, replacement_doc, upsert=True)` method to either insert a new document or replace an existing one in the corresponding read model collection (e.g., `db.cases`, `db.companies`).
    *   The `updated_at` timestamp is usually refreshed during this operation.
    ```python
    # Snippet from infrastructure/database/read_models.py
    # Assuming db_schemas is an alias for infrastructure.database.schemas
    async def upsert_case_read_model(case_data: db_schemas.CaseManagementDB) -> db_schemas.CaseManagementDB:
        db = await get_database()
        case_dict = case_data.model_dump()
        case_dict["updated_at"] = datetime.datetime.utcnow() # Ensure datetime is imported
        await db.cases.replace_one({"id": case_data.id}, case_dict, upsert=True)
        return case_data
    ```
*   **Querying Read Models:**
    *   Functions like `get_case_by_id_from_read_model(case_id: str)`, `list_cases_from_read_model(...)`, `list_required_documents(...)` are used by the API layer (or query handlers) to fetch data.
    *   They construct a query filter dictionary.
    *   They use `pymongo` methods like `find_one()` or `find()` on the appropriate collection.
    *   Results from the database (dictionaries) are parsed back into their respective Pydantic DB schema objects (e.g., `CaseManagementDB(**doc)`) before being returned.
    ```python
    # Snippet from infrastructure/database/read_models.py
    async def get_case_by_id_from_read_model(case_id: str) -> Optional[db_schemas.CaseManagementDB]: # Optional from typing
        db = await get_database()
        case_doc = await db.cases.find_one({"id": case_id})
        return db_schemas.CaseManagementDB(**case_doc) if case_doc else None
    ```

## 5. Raw Event Storage (`infrastructure/database/raw_event_store.py`)

*   The `add_raw_event_to_store` function takes a raw message payload (as a dictionary) and an event type string.
*   It wraps this in a `RawEventDB` Pydantic model (which adds an ID and timestamp).
*   It then inserts this into the `raw_events` collection for auditing and debugging purposes.

This comprehensive use of MongoDB, managed through Pydantic schemas and specific store modules, allows for robust data persistence for both event sourcing and optimized querying of read models.

Proceed to: [**Tutorial 5: FastAPI and API Design**](./05_fastapi_and_api_design.md)
