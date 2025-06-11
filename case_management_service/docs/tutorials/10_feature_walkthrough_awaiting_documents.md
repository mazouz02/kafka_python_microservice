# Tutorial 10: Feature Walkthrough - Awaiting Documents System

This tutorial details the "Awaiting Documents" feature, which allows the Case Management Microservice to determine, track, and manage the status of documents required for KYC and KYB processes.

## 1. Purpose of the Feature

For any KYC/KYB process, collecting and verifying specific documents is a critical step. This feature enables the service to:

*   Identify which documents are necessary for a given case, person, or company based on defined rules (though the initial rules engine is simplified).
*   Store a record for each required document.
*   Track the status of each document requirement (e.g., AWAITING_UPLOAD, UPLOADED, VERIFIED).
*   Provide API endpoints to trigger document determination, update document statuses, and query current document requirements.
*   Utilize the CQRS/Event Sourcing pattern for managing changes to document requirements and statuses.

The actual storage of document files is assumed to be handled by a separate Document Management Service. This microservice focuses on the *metadata* and *status* of these document requirements.

## 2. Key Data Models Involved

### a. Database Schema (`infrastructure/database/schemas.py`)

*   **`RequiredDocumentDB`**: The central read model for this feature, stored in the `document_requirements` MongoDB collection.
    *   Fields: `id` (unique ID for the requirement), `case_id`, `entity_id` (person or company ID), `entity_type`, `document_type` (e.g., "PASSPORT"), `status` (defaults to "AWAITING_UPLOAD"), `is_required`, `metadata`, `notes`, `created_at`, `updated_at`.

### b. Domain Event Models (`core/events/models.py`)

*   **`DocumentRequirementDeterminedEvent(Payload)`**: Signals that a specific document has been identified as required.
    *   `aggregate_id`: Typically the `case_id`.
    *   Payload: `case_id`, `entity_id`, `entity_type`, `document_type`, `is_required`.
*   **`DocumentStatusUpdatedEvent(Payload)`**: Signals a change in the status of a document requirement.
    *   `aggregate_id`: The `document_requirement_id` itself (treating each requirement's status lifecycle as its own stream, or alternatively, could be `case_id`). The current implementation uses `document_requirement_id`.
    *   Payload: `document_requirement_id`, `new_status`, `old_status`, `updated_by`, `metadata_update`, `notes_added`.

### c. Command Models (`core/commands/models.py`)

*   **`DetermineInitialDocumentRequirementsCommand`**: Used to trigger the logic for determining document needs.
    *   Fields: `case_id`, `entity_id`, `entity_type`, `traitement_type`, `case_type`, `context_data`.
*   **`UpdateDocumentStatusCommand`**: Used to request a status change for a document requirement.
    *   Fields: `document_requirement_id`, `new_status`, actor details, metadata, notes.

### d. API Request Models (`app/api/routers/documents.py`)

These Pydantic models define the expected request bodies for the API endpoints:
*   **`DetermineDocRequirementsRequest`**: Maps to the data needed for `DetermineInitialDocumentRequirementsCommand`.
*   **`UpdateDocStatusRequest`**: Maps to the data needed for `UpdateDocumentStatusCommand`.

## 3. Logic Flow and Implementation Details

### a. Determining Document Requirements

1.  **API Call (Optional Trigger):** An external system or user can call `POST /api/v1/documents/determine-requirements` with details about the case and entity.
2.  **Command Creation:** The API endpoint creates a `DetermineInitialDocumentRequirementsCommand`.
3.  **Command Handler (`core/commands/handlers.py:handle_determine_initial_document_requirements`):**
    *   Receives the command.
    *   Applies a **simplified rules engine** (currently hardcoded if/else statements based on `entity_type`, `traitement_type`, `case_type`) to determine a list of required document types and their `is_required` flag.
        *Example Rule (Conceptual):* If entity is PERSON and traitement_type is KYC, require PASSPORT and PROOF_OF_ADDRESS.
    *   For each document identified, it generates a `DocumentRequirementDeterminedEvent`. The `aggregate_id` for these events is the `case_id` to group them. Versioning is handled (simplified) for these events against the case aggregate within this handler's transaction (or each event is v1 if treated as a unique fact).
    *   Saves each event to the Event Store (`event_store.save_event`).
    *   Dispatches each event to local projectors (`dispatch_event_to_projectors`).
4.  **Event Projector (`core/events/projectors.py:project_document_requirement_determined`):**
    *   Consumes `DocumentRequirementDeterminedEvent`.
    *   Creates a new `RequiredDocumentDB` Pydantic object with an initial status (e.g., "AWAITING_UPLOAD") and other details from the event.
    *   Calls `document_requirements_store.add_required_document()` to insert this new record into the `document_requirements` MongoDB collection.

### b. Updating Document Status

1.  **API Call:** An external system or user calls `PUT /api/v1/documents/{document_requirement_id}/status` with the new status and other relevant details.
2.  **Command Creation:** The API endpoint creates an `UpdateDocumentStatusCommand`.
3.  **Command Handler (`core/commands/handlers.py:handle_update_document_status`):**
    *   Receives the command.
    *   **Fetches Current State (Design Note):** It first calls `document_requirements_store.get_required_document_by_id()` to get the current state (especially `old_status`).
    *   If the document requirement is not found, it returns an error/None.
    *   (Future Enhancement: Validate status transition logic).
    *   Generates a `DocumentStatusUpdatedEvent`. The `aggregate_id` for this event is the `document_requirement_id` itself. The event payload includes `new_status`, `old_status`, and any metadata/notes. Versioning is based on the document requirement's state (e.g., using a pseudo-version from `updated_at` or a dedicated version field if `RequiredDocumentDB` were treated as a versioned ES aggregate).
    *   Saves the event to the Event Store.
    *   Dispatches the event to local projectors.
4.  **Event Projector (`core/events/projectors.py:project_document_status_updated`):**
    *   Consumes `DocumentStatusUpdatedEvent`.
    *   Calls `document_requirements_store.update_required_document_status_and_meta()` to update the specific document requirement record in the `document_requirements` collection with the new status, metadata, and notes.

### c. Querying Document Requirements

*   The API endpoints in `app/api/routers/documents.py` (`GET /api/v1/documents/{document_requirement_id}` and `GET /api/v1/documents/case/{case_id}`) directly use functions from `document_requirements_store.py` to query the `document_requirements` read model collection and return the data.

## 4. How to Test This Feature

### a. Unit Tests

*   **Database Store (`tests/infrastructure/database/test_database.py`):**
    *   Tests for `document_requirements_store.py` functions: `test_add_required_document`, `test_update_required_document_status_and_meta_success`, `test_get_required_document_by_id`, `test_list_required_documents`.
*   **Command Handlers (`tests/core/commands/test_command_handlers.py`):**
    *   Tests for `handle_determine_initial_document_requirements`: Verify correct `DocumentRequirementDeterminedEvent` generation based on simplified rules, and calls to `save_event`/`dispatch_event_to_projectors`.
    *   Tests for `handle_update_document_status`: Verify correct `DocumentStatusUpdatedEvent` generation, calls to `get_required_document_by_id`, `save_event`, and `dispatch_event_to_projectors`. Test not-found scenarios.
*   **Event Projectors (`tests/core/events/test_event_projectors.py`):**
    *   Tests for `project_document_requirement_determined`: Mock `add_required_document` and verify it's called with correct `RequiredDocumentDB` data.
    *   Tests for `project_document_status_updated`: Mock `update_required_document_status_and_meta` and verify it's called with correct arguments.
*   **API Endpoints (`tests/app/test_api.py`):**
    *   Test all endpoints in `documents.py` router, mocking command handlers and store functions. Verify request/response schemas, status codes, and error handling.

### b. End-to-End Testing (Conceptual)

1.  **Create a Case:** Use the Kafka producer method (from previous tutorials) to create a KYC or KYB case. Note the `case_id` and any relevant `person_id` or `company_id` generated.
2.  **Determine Requirements:**
    *   Call `POST /api/v1/documents/determine-requirements` using the API (e.g., via Swagger UI at `/docs`).
    *   *Request Body Example:*
        ```json
        {
          "case_id": "<your_case_id>",
          "entity_id": "<your_person_or_company_id>",
          "entity_type": "PERSON",
          "traitement_type": "KYC",
          "case_type": "INDIVIDUAL_STANDARD"
        }
        ```
    *   **Verify:**
        *   API response should be 202 Accepted.
        *   Check consumer logs for processing (if determination is triggered by an event, though here it's API-driven). Check API logs.
        *   **Database (`document_requirements` collection):** Verify new records are created with status "AWAITING_UPLOAD".
        *   **API:** Call `GET /api/v1/documents/case/{case_id}` to list the determined requirements.
3.  **Update Document Status:**
    *   Pick a `document_requirement_id` from the previous step.
    *   Call `PUT /api/v1/documents/{document_requirement_id}/status`.
    *   *Request Body Example:*
        ```json
        {
          "new_status": "UPLOADED",
          "updated_by_actor_id": "test_user_api",
          "metadata_changes": { "file_link": "/path/to/doc.pdf" },
          "notes_to_add": ["Document uploaded via API test."]
        }
        ```
    *   **Verify:**
        *   API response should be 200 OK with the updated document requirement.
        *   **Database:** Check the record in `document_requirements` for the new status, metadata, and appended note.
        *   **API:** Call `GET /api/v1/documents/{document_requirement_id}` to confirm the changes.

This feature provides a flexible way to manage document lifecycles within the case management process.

Proceed to: [**Tutorial 11: Feature Walkthrough - Configurable Notifications**](./11_feature_walkthrough_notifications.md)
