# Tutorial 5: FastAPI and API Design

This tutorial explores how we use FastAPI to build the RESTful API for the Case Management Microservice. FastAPI is a modern, high-performance web framework for building APIs with Python, based on standard Python type hints.

## 1. FastAPI Application Setup (`app/main.py`)

The main FastAPI application instance is created and configured in `case_management_service/app/main.py`.

*   **Instantiation:**
    ```python
    from fastapi import FastAPI
    from case_management_service.app.config import settings # For app metadata

    app = FastAPI(
        title=settings.SERVICE_NAME_API, # Or a more descriptive title from settings
        description="Manages cases, companies, persons, and document requirements.",
        version="0.3.0" # Example version, could also be from settings or dynamic
    )
    ```
    The `title`, `description`, and `version` are used in the OpenAPI specification (Swagger UI/ReDoc).

*   **Lifecycle Events (`@app.on_event("startup")`, `@app.on_event("shutdown")`)**:
    *   **Startup:** Used to initialize resources like database connections (`connect_to_mongo()`) and the Kafka producer (`startup_kafka_producer()`). It also calls `PymongoInstrumentor().instrument()\` for OpenTelemetry.
    *   **Shutdown:** Used to release resources, such as closing the database connection (`close_mongo_connection()`) and shutting down the Kafka producer (`shutdown_kafka_producer()`).
    ```python
    # Snippet from app/main.py
    # Assuming relevant imports like connect_to_mongo, get_database, PymongoInstrumentor, startup_kafka_producer, logger
    @app.on_event("startup")
    async def startup_event():
        logger.info("FastAPI application startup...")
        connect_to_mongo()
        await get_database() # Verify connection
        PymongoInstrumentor().instrument()
        await startup_kafka_producer()
        logger.info("MongoDB, PyMongo OTel, and Kafka Producer initialized.")
    ```

*   **OpenTelemetry Instrumentation:**
    *   `setup_opentelemetry(service_name=settings.SERVICE_NAME_API)` is called at the beginning of `main.py` to initialize tracing and metrics.
    *   `FastAPIInstrumentor.instrument_app(app)` is called to automatically trace FastAPI requests.

## 2. API Routers (`app/api/routers/`)

To keep the API design modular and organized, endpoints are grouped into `APIRouter` instances, typically by resource. These routers are defined in separate files within the `case_management_service/app/api/routers/` directory.

*   **Example Router File (`app/api/routers/cases.py`):**
    ```python
    from fastapi import APIRouter, Depends, HTTPException
    from typing import List, Optional # Ensure these are imported
    from case_management_service.infrastructure.database import schemas as db_schemas
    from case_management_service.infrastructure.database import read_models as read_model_ops
    # ... other imports ...

    router = APIRouter()

    @router.get("/{case_id}", response_model=Optional[db_schemas.CaseManagementDB])
    async def get_case_by_id(case_id: str): # Renamed for clarity from endpoint
        # ... implementation using read_model_ops ...
        case_doc = await read_model_ops.get_case_by_id_from_read_model(case_id=case_id)
        if not case_doc:
            return None
        return case_doc

    @router.get("", response_model=List[db_schemas.CaseManagementDB]) # Path for list is often empty string for router root
    async def list_cases(limit: int = 10, skip: int = 0): # Renamed for clarity
        # ... implementation using read_model_ops ...
        cases = await read_model_ops.list_cases_from_read_model(limit=limit, skip=skip)
        return cases
    ```

*   **Including Routers in `app/main.py`:**
    The main `app` object includes these routers, often with a common prefix and tags for OpenAPI grouping.
    ```python
    # Snippet from app/main.py
    from case_management_service.app.api.routers import health, cases, persons, documents, raw_events

    # ... (app = FastAPI() instance) ...

    app.include_router(health.router) # No prefix for /health
    app.include_router(raw_events.router, prefix="/api/v1/events", tags=["Events"]) # Updated prefix
    app.include_router(cases.router, prefix="/api/v1/cases", tags=["Cases"])
    app.include_router(persons.router, prefix="/api/v1/persons", tags=["Persons"])
    app.include_router(documents.router, prefix="/api/v1/documents", tags=["Document Requirements"])
    ```
    For example, endpoints defined in `cases.router` with path `/{case_id}` will be accessible under `/api/v1/cases/{case_id}`.

## 3. Defining Path Operations (Endpoints)

FastAPI uses decorators on your asynchronous functions to define path operations:

*   **Path:** The URL path for the endpoint (e.g., `"/{case_id}"`).
*   **Operation:** The HTTP method (`@router.get`, `@router.post`, `@router.put`, `@router.delete`).
*   **Path Parameters:** Defined using curly braces in the path string (e.g., `{case_id}`) and passed as arguments to your function with type hints (`case_id: str`).
*   **Query Parameters:** Defined as function arguments with default values (e.g., `limit: int = 10`). FastAPI automatically parses them from the URL query string.
*   **Request Body:** For `POST`, `PUT`, `PATCH`, you define a Pydantic model representing the expected request body and type-hint a function argument with it. FastAPI handles deserialization and validation.
    ```python
    # Example from app/api/routers/documents.py
    from pydantic import BaseModel # Ensure BaseModel is imported in the router file
    from fastapi import Body # Ensure Body is imported

    class UpdateDocStatusRequest(BaseModel): # Pydantic model for request body
        new_status: str
        # ... other fields ...

    @router.put("/{document_requirement_id}/status", response_model=Optional[db_schemas.RequiredDocumentDB])
    async def update_document_status_api(
        document_requirement_id: str, # Path parameter
        request_data: UpdateDocStatusRequest = Body(...) # Request body
    ):
        # ... implementation ...
    ```
    The `Body(...)` indicates that `request_data` comes from the request body.

## 4. Request Validation with Pydantic

FastAPI leverages Pydantic models for automatic request data validation.
*   If path parameters, query parameters, or request body data don't match the type hints or Pydantic model constraints, FastAPI automatically returns a 422 Unprocessable Entity error with details.
*   This significantly reduces boilerplate validation code in your endpoint functions.

## 5. Response Models and Data Serialization

*   **`response_model`:** The `@router.get(...)\` decorator (and others) takes a `response_model` argument. You provide a Pydantic model here (e.g., `db_schemas.CaseManagementDB`).
*   **Automatic Serialization:** FastAPI will automatically:
    *   Filter the return value of your path operation function to include only the fields defined in the `response_model`.
    *   Serialize the Pydantic model instance (or list of instances) to JSON.
    *   Convert types as needed (e.g., `datetime` objects to ISO 8601 strings).
*   This ensures your API responses are consistent and conform to a defined schema.

## 6. Dependency Injection

FastAPI has a powerful and easy-to-use Dependency Injection system.
*   **`Depends()`:** You can define dependencies (functions or classes) that FastAPI will resolve and inject into your path operation functions.
*   **Common Use Case (Database Session):**
    ```python
    # Snippet from app/api/routers/health.py
    from case_management_service.infrastructure.database.connection import get_database
    from fastapi import Depends # Ensure Depends is imported

    @router.get("/health", tags=["Monitoring"])
    async def health_check(db = Depends(get_database)): # db will be the result of calling get_database()
        # ... use db to ping MongoDB ...
    ```
    Here, `get_database()` (from `infrastructure.database.connection.py\`) is an async function that returns the MongoDB database instance. FastAPI calls it for each request to `/health` and provides the result as the `db` argument.
*   Dependencies can also be used for authentication, authorization, common parameter processing, etc.

## 7. Error Handling

*   **Automatic Validation Errors:** FastAPI returns 422 errors for Pydantic validation issues.
*   **`HTTPException`:** For business logic errors or other specific error conditions, you can raise an `HTTPException` from FastAPI.
    ```python
    # Snippet from app/api/routers/cases.py
    from fastapi import HTTPException # Ensure HTTPException is imported

    # ... inside an endpoint ...
    if not case_doc:
        # If response_model is Optional[...], returning None results in HTTP 200 with null body.
        # To explicitly return 404:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return case_doc
    ```
    The `HTTPException` will be automatically converted into an appropriate JSON error response.
*   **General Exception Handling:** You can also add custom exception handlers at the app level for unhandled exceptions to provide consistent error responses. (Not explicitly implemented in this project yet, but a common FastAPI feature).

## 8. Auto-Generated API Documentation

FastAPI automatically generates an OpenAPI specification for your API and provides two interactive documentation UIs out-of-the-box:

*   **Swagger UI:** Accessible at `/docs` (e.g., `http://localhost:8000/docs\` locally).
*   **ReDoc:** Accessible at `/redoc` (e.g., `http://localhost:8000/redoc\` locally).

These interfaces allow users (and developers) to explore your API endpoints, view schemas for request/response bodies, and even try out the API calls directly in the browser.

This combination of features makes FastAPI a very productive framework for building robust and well-documented APIs.

Proceed to: [**Tutorial 6: Observability with OpenTelemetry**](./06_observability_with_opentelemetry.md)
