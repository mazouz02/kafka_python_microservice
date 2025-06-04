# API Guide

This guide provides details on using the RESTful API for the Case Management Microservice.
The API is built using FastAPI.

## Accessing the API

*   **Base URL (Local Docker Compose):** `http://localhost:8000/api/v1` (for most resource endpoints)
*   **Health Check:** `http://localhost:8000/health`
*   **Swagger UI (Interactive Docs):** `http://localhost:8000/docs`
*   **ReDoc (Alternative Docs):** `http://localhost:8000/redoc`

All resource-specific endpoints (Cases, Persons, Documents, Raw Events) are typically prefixed with `/api/v1/`. The health check is usually at the root.

## Authentication

(Currently, no authentication is implemented. This section would detail auth mechanisms like OAuth2, API keys, etc., if added.)

## Common Headers

*   `Content-Type: application/json` for request bodies.
*   `Accept: application/json` for responses.

## API Endpoints

(This section provides an overview. Detailed request/response schemas and examples can be found in the Swagger UI.)

### Health & Monitoring
*   **GET /health**: Checks the operational status of the service and its connection to MongoDB.

### Raw Events (Ingested Messages)
*   **GET /api/v1/events/raw**: Lists raw events ingested by the Kafka consumer. Useful for debugging and tracing data lineage.
    *   Query Parameters: `limit` (int, default 10), `skip` (int, default 0).

### Cases
*   **GET /api/v1/cases/**: Lists cases from the read model.
    *   Query Parameters: `limit` (int, default 10), `skip` (int, default 0).
*   **GET /api/v1/cases/{case_id}**: Retrieves a specific case by its ID.

### Persons
*   **GET /api/v1/persons/case/{case_id}**: Lists persons associated with a specific case.
    *   Query Parameters: `limit` (int, default 10), `skip` (int, default 0).

### Document Requirements
*   **POST /api/v1/documents/determine-requirements**: Initiates the process of determining required documents for an entity within a case.
    *   *Request Body Example:*
        ```json
        {
          "case_id": "existing_case_uuid",
          "entity_id": "person_or_company_uuid",
          "entity_type": "PERSON",
          "traitement_type": "KYC",
          "case_type": "INDIVIDUAL_STANDARD",
          "context_data": { "jurisdiction": "US" }
        }
        ```
*   **PUT /api/v1/documents/{document_requirement_id}/status**: Updates the status of a specific document requirement.
    *   *Request Body Example:*
        ```json
        {
          "new_status": "UPLOADED",
          "updated_by_actor_id": "user_x",
          "metadata_changes": { "file_reference_id": "file_abc.pdf", "upload_timestamp": "2023-10-27T10:30:00Z" },
          "notes_to_add": ["Document uploaded by customer via portal."]
        }
        ```
*   **GET /api/v1/documents/{document_requirement_id}**: Retrieves details of a specific document requirement.
*   **GET /api/v1/documents/case/{case_id}**: Lists all document requirements for a specific case.
    *   Query Parameters: `entity_id` (str, optional), `entity_type` (str, optional), `status` (str, optional), `is_required` (bool, optional).

(Further details for each endpoint: example full response bodies, error codes, specific field explanations would be beneficial.)
