# Tutorial 9: Feature Walkthrough - Company & Beneficial Owner Modeling (KYB)

This tutorial walks through the design and implementation of the feature that enables the Case Management Microservice to handle **Know Your Business (KYB)** data, specifically focusing on modeling company profiles and their beneficial owners.

## 1. Purpose of the Feature

While the initial service could handle basic KYC (Know Your Customer) for individuals, modern compliance often requires onboarding and managing data for legal entities (companies, organizations). This feature extends the service to:

*   Distinguish between KYC and KYB processing via a `traitement_type`.
*   Capture detailed company profile information.
*   Record beneficial owners (BOs) associated with a company, including their details and ownership structure.
*   Link individuals (like directors or contact persons) to companies with specific roles.
*   Maintain separate read models for companies and beneficial owners for efficient querying.
*   Utilize the existing CQRS/Event Sourcing architecture to manage state changes for these new entities.

## 2. Key Data Models Involved

This feature introduced several new Pydantic models and updated existing ones across different layers.

### a. Kafka Schemas (`infrastructure/kafka/schemas.py`)

The incoming Kafka message (`KafkaMessage`) was enhanced:

*   **`traitement_type: str`**: Added to `KafkaMessage` to specify "KYC" or "KYB".
*   **`company_profile: Optional[CompanyProfileData]`**: Added to `KafkaMessage`.
    *   **`CompanyProfileData`**: New model containing fields like `registered_name`, `registration_number`, `country_of_incorporation`, `registered_address` (using `AddressData`), etc.
*   **`beneficial_owners: Optional[List[BeneficialOwnerData]]`**: Added to `KafkaMessage`.
    *   **`BeneficialOwnerData`**: New model with `person_details: PersonData`, `ownership_percentage`, `types_of_control`, `is_ubo`.
*   **`PersonData`**: Updated to include an optional `role_in_company: str`.
*   **Validators** in `KafkaMessage` ensure `company_profile` is present for KYB and `beneficial_owners` are not present for KYC.

### b. Command Models (`core/commands/models.py`)

*   **`CreateCaseCommand`**: Modified to mirror the enriched `KafkaMessage`, including `traitement_type`, `company_profile`, and `beneficial_owners`.

### c. Domain Event Models (`core/events/models.py`)

New events were introduced to capture state changes related to companies and BOs:

*   **`CompanyProfileCreatedEvent(Payload)`**: Signals the creation of a new company profile. Its `aggregate_id` is the unique `company_id`.
    *   Payload includes all company details.
*   **`BeneficialOwnerAddedEvent(Payload)`**: Signals a beneficial owner has been added to a company. Its `aggregate_id` is the `company_id`.
    *   Payload includes `beneficial_owner_id` (unique ID for the BO record) and BO details.
*   **`PersonLinkedToCompanyEvent(Payload)`**: Signals an individual has been linked to a company with a specific role. Its `aggregate_id` is the `company_id`.
    *   Payload includes `person_id`, denormalized person details, and `role_in_company`.
*   **`CaseCreatedEventPayload`**: Modified to include `traitement_type` and an optional `company_id` to link the case to the company profile if it's a KYB case.

### d. Database Schemas (Read Models - `infrastructure/database/schemas.py`)

New read model schemas were created, and existing ones updated:

*   **`CompanyProfileDB`**: For the `companies` collection, storing company details. `id` field is the `company_id`.
*   **`BeneficialOwnerDB`**: For the `beneficial_owners` collection, storing BO details, linked to a `company_id`. `id` field is the `beneficial_owner_id`.
*   **`CaseManagementDB`**: Updated to include `traitement_type` and `company_id`.
*   **`PersonDB`**: Updated to include an optional `company_id` and `role_in_company`.

## 3. Logic Flow and Implementation Details

### a. Command Handler (`core/commands/handlers.py:handle_create_case_command`)

The `handle_create_case_command` was significantly updated:

1.  **Checks `command.traitement_type`**.
2.  **If \"KYB\"**:
    *   If `company_profile` data is present:
        *   A new unique `company_id` (UUID) is generated.
        *   A `CompanyProfileCreatedEvent` is created. Its `aggregate_id` is set to this new `company_id`, and its `version` is 1 (as it's the first event for this new Company aggregate). This event is saved.
        *   The main `CaseCreatedEvent` (which is always created, with its own `case_id` as `aggregate_id` and version 1) has its payload updated to include this `company_id`, linking the case to the company.
    *   For each person in `command.persons` with a `role_in_company`:
        *   A `PersonLinkedToCompanyEvent` is created. Its `aggregate_id` is the `company_id`. The `version` for these events increments sequentially for the Company aggregate (e.g., if CompanyProfileCreated was v1, the first PersonLinked is v2 for that company).
    *   For each beneficial owner in `command.beneficial_owners`:
        *   A `BeneficialOwnerAddedEvent` is created. Its `aggregate_id` is the `company_id`. The `version` also increments sequentially for the Company aggregate.
3.  **If \"KYC\"**:
    *   The logic proceeds as before, primarily creating `PersonAddedToCaseEvent`(s) linked to the `case_id` aggregate. No company or BO-specific events are generated.
4.  **Event Persistence & Dispatch:** All generated domain events are saved to the Event Store using `infrastructure.database.event_store.save_event`. After all events for the command are successfully saved, they are dispatched to local projectors via `core.events.projectors.dispatch_event_to_projectors`.

This design treats **Company** as a distinct aggregate with its own event stream and versioning when `traitement_type` is KYB. The Case then acts as a context or wrapper, potentially linking to this Company aggregate.

### b. Event Projectors (`core/events/projectors.py`)

New projectors were added to update the new read models:

*   **`project_company_profile_created(event: CompanyProfileCreatedEvent)`**:
    *   Consumes `CompanyProfileCreatedEvent`.
    *   Transforms the event payload into a `CompanyProfileDB` object.
    *   Calls `read_model_ops.upsert_company_read_model()` to save/update it in the `companies` MongoDB collection.
*   **`project_beneficial_owner_added(event: BeneficialOwnerAddedEvent)`**:
    *   Consumes `BeneficialOwnerAddedEvent`.
    *   Transforms data into a `BeneficialOwnerDB` object (denormalizing person details from the event payload).
    *   Calls `read_model_ops.upsert_beneficial_owner_read_model()` to save/update it in the `beneficial_owners` collection.
*   **`project_person_linked_to_company(event: PersonLinkedToCompanyEvent)`**:
    *   Consumes `PersonLinkedToCompanyEvent`.
    *   Transforms data into a `PersonDB` object, ensuring `company_id` and `role_in_company` are set.
    *   Calls `read_model_ops.upsert_person_read_model()` to save/update it in the `persons` collection.
*   **`project_case_created`**: Modified to also project `traitement_type` and `company_id` into the `CaseManagementDB` read model.
*   The `EVENT_PROJECTORS` map was updated to include these new event-to-projector mappings.

### c. Database Operations (`infrastructure/database/read_models.py`)

New functions were added to support the new read models:
*   `upsert_company_read_model(company_data: CompanyProfileDB)`
*   `upsert_beneficial_owner_read_model(bo_data: BeneficialOwnerDB)`
These use `replace_one(upsert=True)` for idempotency.

## 4. How to Test This Feature

(This section recaps and focuses the general testing information from the main README and Tutorial 7).

### a. Unit Tests

*   **Kafka Schemas:** `tests/infrastructure/kafka/test_kafka_schemas.py` contains tests for the updated `KafkaMessage` structure, including validation of `company_profile` and `beneficial_owners` fields based on `traitement_type`.
*   **Command Handler:** `tests/core/commands/test_command_handlers.py` has specific test cases like `test_handle_create_case_command_kyb_with_company_and_bos_and_persons`. These mock dependencies (`save_event`, `dispatch_event_to_projectors`) and verify:
    *   Correct generation of `CompanyProfileCreatedEvent`, `BeneficialOwnerAddedEvent`, and `PersonLinkedToCompanyEvent`.
    *   Correct `aggregate_id` (case vs. company) and `version` for each event.
    *   That the `CaseCreatedEvent` payload includes the `company_id` for KYB cases.
*   **Event Projectors:** `tests/core/events/test_event_projectors.py` includes tests for the new projectors (`test_project_company_profile_created`, etc.). These mock the `upsert_...\` functions from `read_models.py\` and verify they are called with correctly transformed DB schema objects.
*   **Database Operations:** `tests/infrastructure/database/test_database.py` tests the new `upsert_company_read_model` and `upsert_beneficial_owner_read_model` functions, as well as ensuring the event store can handle saving and deserializing the new event types.

### b. End-to-End Testing (Conceptual)

1.  **Start Services:** Ensure Docker Compose services are running (`docker-compose up --build -d`).
2.  **Produce Kafka Message:** Send a Kafka message to the topic defined in your Docker Compose environment (e.g., `kyc_events_docker`) with:
    *   `traitement_type: "KYB"`
    *   A populated `company_profile` object.
    *   A list of `persons` with `role_in_company` specified.
    *   A list of `beneficial_owners`.
    *   (Refer to Tutorial 7 or the main README for an example KYB Kafka message payload).
3.  **Verify Processing:**
    *   **Logs:** Check the logs of the `case-management-consumer` service for messages indicating processing of the KYB data and generation of related events.
    *   **Event Store (MongoDB - `domain_events` collection):**
        *   Verify that `CaseCreatedEvent`, `CompanyProfileCreatedEvent`, `PersonLinkedToCompanyEvent`(s), and `BeneficialOwnerAddedEvent`(s) were persisted with correct `aggregate_id`s (`case_id` for CaseCreated, `company_id` for others) and sequential versions for each aggregate.
    *   **Read Models (MongoDB):**
        *   `cases` collection: Check the created case document. It should have `traitement_type: "KYB"` and its `company_id` field should be populated.
        *   `companies` collection: Verify the new company profile document.
        *   `persons` collection: Verify records for linked persons, ensuring their `company_id` and `role_in_company` are set.
        *   `beneficial_owners` collection: Verify the new beneficial owner documents, linked to the `company_id`.
    *   **API (Optional, as specific query endpoints for company/BO might be future features):**
        *   Query the `GET /api/v1/cases/{case_id}` endpoint and check the returned case data for the `company_id` link and correct `traitement_type`.

This feature significantly enhances the microservice's ability to handle complex business client onboarding data.

Proceed to: [**Tutorial 10: Feature Walkthrough - Awaiting Documents System**](./10_feature_walkthrough_awaiting_documents.md)
