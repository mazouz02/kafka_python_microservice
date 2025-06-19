import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, ANY

from fastapi.testclient import TestClient
from mongomock import MongoClient as MongoMockClient

from app.main import app
from app.api.dependencies import get_db
from app.config import settings
from app.service.models import CaseType, Role, PersonProfile
from app.service.events.events import CaseCreatedEvent, PersonAddedToCaseEvent, NotificationRequiredEvent
from app.db.db_schemas import CaseManagementDB, PersonCaseLinkDB # Assuming PersonDB is PersonCaseLinkDB for this context

# Collection names (ensure these match your application's definitions)
EVENT_STORE_COLLECTION = settings.EVENT_STORE_COLLECTION_NAME
CASES_READ_MODEL_COLLECTION = settings.CASES_READ_MODEL_COLLECTION_NAME
# Assuming persons linked to cases are stored in a collection named 'persons_case_links' or similar
# For this test, let's assume 'persons' is the read model collection for persons linked to cases.
# If it's part of the CaseManagementDB.persons list, adjust assertions accordingly.
PERSONS_READ_MODEL_COLLECTION = "persons" # Placeholder - adjust if needed

@pytest.fixture(scope="function")
def test_db_session():
    """
    Provides a mongomock database session for testing.
    Clears relevant collections before each test.
    """
    client = MongoMockClient()
    db = client[settings.MONGODB_DATABASE_NAME] # Use the database name from settings

    # Clear collections before each test
    db[EVENT_STORE_COLLECTION].delete_many({})
    db[CASES_READ_MODEL_COLLECTION].delete_many({})
    db[PERSONS_READ_MODEL_COLLECTION].delete_many({})
    db[COMPANIES_READ_MODEL_COLLECTION].delete_many({})
    db[BENEFICIAL_OWNERS_READ_MODEL_COLLECTION].delete_many({})
    db[PERSON_COMPANY_LINKS_COLLECTION].delete_many({})
    db[DOCUMENT_REQUIREMENTS_READ_MODEL_COLLECTION].delete_many({}) # Added this line
    # Add other collections to clear if necessary

    yield db
    client.close()


@pytest.fixture(scope="function")
def test_client_with_mock_db(test_db_session: MongoMockClient):
    """
    Provides a TestClient with the get_db dependency overridden to use mongomock.
    """
    app.dependency_overrides[get_db] = lambda: test_db_session
    yield TestClient(app)
    app.dependency_overrides = {} # Clear overrides after the test


# Mock external dependencies for command handlers
@pytest.fixture(autouse=True) # Apply to all tests in this module
def mock_external_services():
    with patch("app.service.commands.handlers.get_kafka_producer", new_callable=AsyncMock) as mock_get_kafka, \
         patch("app.service.commands.handlers.get_notification_config_client", new_callable=AsyncMock) as mock_get_notif_client, \
         patch("app.service.commands.handlers.get_document_strategy", new_callable=AsyncMock) as mock_get_doc_strategy: # Added document strategy mock

        mock_kafka_producer = AsyncMock()
        mock_kafka_producer.produce_message = AsyncMock(return_value=None) # Simulate successful send
        mock_get_kafka.return_value = mock_kafka_producer

        mock_notif_client = AsyncMock()
        mock_notif_client.get_notification_strategy = AsyncMock(return_value="SEND_ALL")
        mock_get_notif_client.return_value = mock_notif_client

        # Mock for document strategy used in determine_document_requirements
        mock_doc_strategy_instance = AsyncMock()
        # Define what get_document_requirements returns. This is crucial for the doc req test.
        # Example: Return one passport requirement for KYC/INDIVIDUAL/US
        from app.service.models import DocumentSpecification # Import for typing
        mock_doc_strategy_instance.get_document_requirements = AsyncMock(return_value=[
            DocumentSpecification(document_id=str(uuid.uuid4()), document_type="PASSPORT", description="Valid Passport", country_code="US", required=True)
        ])
        mock_get_doc_strategy.return_value = mock_doc_strategy_instance

        yield {
            "kafka_producer": mock_kafka_producer,
            "notification_config_client": mock_notif_client,
            "document_strategy": mock_doc_strategy_instance # So it can be asserted if needed
        }


def test_create_kyc_case_integration(
    test_client_with_mock_db: TestClient,
    test_db_session: MongoMockClient,
    mock_external_services: dict # Fixture to ensure mocks are active
):
    # 1. Prepare Command Payload
    user_id = "integration_test_user"
    person1_id = str(uuid.uuid4())
    person1_profile = PersonProfile(name="John Integration Doe", email="john.integration@example.com")

    create_case_payload = {
        "case_type": CaseType.KYC.value,
        "created_by": user_id,
        "persons": [
            {
                "person_id": person1_id,
                "profile": person1_profile.model_dump(),
                "role": Role.PRIMARY_CONTACT.value
            }
        ],
        "company_profile": None,
        "beneficial_owners": None
    }

    # 2. Action: Make POST request
    response = test_client_with_mock_db.post("/api/v1/cases", json=create_case_payload)

    # 3. Assertions
    # API Response
    assert response.status_code == 202 # Accepted
    response_data = response.json()
    assert "case_id" in response_data
    case_id = response_data["case_id"]
    assert uuid.UUID(case_id) # Check if it's a valid UUID

    # Event Store Verification
    event_store = test_db_session[EVENT_STORE_COLLECTION]

    # CaseCreatedEvent
    case_created_event_doc = event_store.find_one({"aggregate_id": case_id, "event_type": CaseCreatedEvent.__name__})
    assert case_created_event_doc is not None
    assert case_created_event_doc["version"] == 1
    assert case_created_event_doc["payload"]["case_type"] == CaseType.KYC.value
    assert case_created_event_doc["payload"]["created_by"] == user_id
    assert datetime.fromisoformat(case_created_event_doc["created_at"]).tzinfo is not None

    # PersonAddedToCaseEvent
    person_added_event_doc = event_store.find_one({
        "aggregate_id": case_id,
        "event_type": PersonAddedToCaseEvent.__name__,
        "payload.person_id": person1_id
    })
    assert person_added_event_doc is not None
    assert person_added_event_doc["version"] == 2 # Assuming it's the next event
    assert person_added_event_doc["payload"]["profile"]["name"] == person1_profile.name
    assert person_added_event_doc["payload"]["role"] == Role.PRIMARY_CONTACT.value

    # NotificationRequiredEvent (check if Kafka mock was called, via the fixture)
    # The mock_external_services fixture already patches get_kafka_producer
    # The handler calls save_event for NotificationRequiredEvent, then tries to send.
    notification_event_doc = event_store.find_one({
        "aggregate_id": case_id,
        "event_type": NotificationRequiredEvent.__name__
    })
    assert notification_event_doc is not None
    assert notification_event_doc["payload"]["case_id"] == case_id
    assert notification_event_doc["payload"]["notification_type"] == "CASE_CREATED"

    # Verify Kafka producer was called (via the mock injected by mock_external_services)
    mock_kafka_producer = mock_external_services["kafka_producer"]
    mock_kafka_producer.produce_message.assert_called_once_with(
        topic=settings.KAFKA_NOTIFICATIONS_TOPIC,
        key={"case_id": case_id},
        value=ANY # Or reconstruct the exact expected message if necessary
    )


    # Read Model Verification
    # Case Read Model
    cases_collection = test_db_session[CASES_READ_MODEL_COLLECTION]
    case_read_model_doc = cases_collection.find_one({"case_id": case_id})
    assert case_read_model_doc is not None
    assert case_read_model_doc["case_type"] == CaseType.KYC.value
    assert case_read_model_doc["status"] == "PENDING" # Default status set by projector
    assert case_read_model_doc["created_by"] == user_id
    assert case_read_model_doc["version"] == 1 # Version of the CaseCreatedEvent that built this
    assert isinstance(case_read_model_doc["created_at"], datetime) # Mongomock stores actual datetime
    assert isinstance(case_read_model_doc["updated_at"], datetime)

    # Person Read Model (assuming persons are stored in a separate 'persons' collection for read model)
    # This depends on how your projectors store person data.
    # If PersonCaseLinkDB is the schema for the 'persons' collection:
    persons_collection = test_db_session[PERSONS_READ_MODEL_COLLECTION] # Adjust collection name if needed
    person_read_model_doc = persons_collection.find_one({"person_id": person1_id, "case_id": case_id})

    # This part needs adjustment based on where/how person read models are stored.
    # If persons are embedded in the case_read_model_doc:
    # found_person_in_case = next((p for p in case_read_model_doc.get("persons", []) if p["person_id"] == person1_id), None)
    # assert found_person_in_case is not None
    # assert found_person_in_case["name"] == person1_profile.name
    # assert found_person_in_case["role"] == Role.PRIMARY_CONTACT.value

    # If PersonCaseLinkDB is stored in a separate collection:
    if person_read_model_doc: # Check if a separate person link record is expected
        assert person_read_model_doc["name"] == person1_profile.name
        assert person_read_model_doc["role"] == Role.PRIMARY_CONTACT.value
        assert person_read_model_doc["version"] == 2 # Version of PersonAddedToCaseEvent
    else:
        # Fallback: Check if the person info is embedded within the CaseManagementDB's 'persons' list
        case_doc_for_person_check = cases_collection.find_one({"case_id": case_id})
        assert case_doc_for_person_check is not None
        found_person_in_case = next((p for p in case_doc_for_person_check.get("persons", []) if p.get("person_id") == person1_id), None)
        assert found_person_in_case is not None, f"Person {person1_id} not found in case's persons list."
        assert found_person_in_case["name"] == person1_profile.name
        assert found_person_in_case["role"] == Role.PRIMARY_CONTACT.value
        # Add version check if applicable to embedded persons list items
        # assert found_person_in_case["version"] == 2

    # Further assertions for read models can be added here.


# Placeholder for company and BO collection names - adjust as per your actual settings/schema
COMPANIES_READ_MODEL_COLLECTION = "companies"
BENEFICIAL_OWNERS_READ_MODEL_COLLECTION = "beneficial_owners"
PERSON_COMPANY_LINKS_COLLECTION = "person_company_links" # If you have a specific collection for these links

def test_create_kyb_case_full_integration(
    test_client_with_mock_db: TestClient,
    test_db_session: MongoMockClient,
    mock_external_services: dict
):
    # 1. Prepare Command Payload for KYB Case
    user_id = "integration_test_user_kyb"
    company_id = str(uuid.uuid4())
    company_profile_data = CompanyProfile(name="Integration Test Corp", registration_number="ITC-001", country_of_incorporation="US", address="123 Test Lane")

    person1_id = str(uuid.uuid4())
    person1_profile = PersonProfile(name="Director Alpha", email="dir.alpha@itc.com")

    bo1_id = str(uuid.uuid4())
    bo1_profile = PersonProfile(name="Owner Bravo", email="owner.bravo@itc.com")

    create_kyb_payload = {
        "case_type": CaseType.KYB.value,
        "created_by": user_id,
        "company_profile": {
            "company_id": company_id, # Client can suggest an ID or it can be generated by handler
            "profile": company_profile_data.model_dump()
        },
        "persons": [ # Persons linked to the company, not directly to the case in KYB
            {
                "person_id": person1_id,
                "profile": person1_profile.model_dump(),
                "role_in_company": Role.DIRECTOR.value # Role within the company
            }
        ],
        "beneficial_owners": [
            {
                "bo_id": bo1_id,
                "profile": bo1_profile.model_dump(),
                "ownership_percentage": 75.0
            }
        ]
    }

    # 2. Action: Make POST request
    response = test_client_with_mock_db.post("/api/v1/cases", json=create_kyb_payload)

    # 3. Assertions
    # API Response
    assert response.status_code == 202
    response_data = response.json()
    assert "case_id" in response_data
    kyb_case_id = response_data["case_id"]
    assert uuid.UUID(kyb_case_id)

    # Event Store Verification
    event_store = test_db_session[EVENT_STORE_COLLECTION]

    # CompanyProfileCreatedEvent (aggregate_id is company_id)
    company_created_event_doc = event_store.find_one({"aggregate_id": company_id, "event_type": "CompanyProfileCreatedEvent"})
    assert company_created_event_doc is not None
    assert company_created_event_doc["version"] == 1
    assert company_created_event_doc["payload"]["profile"]["name"] == company_profile_data.name
    assert company_created_event_doc["payload"]["created_by"] == user_id

    # PersonLinkedToCompanyEvent (aggregate_id is company_id)
    person_linked_event_doc = event_store.find_one({
        "aggregate_id": company_id,
        "event_type": "PersonLinkedToCompanyEvent",
        "payload.person_id": person1_id
    })
    assert person_linked_event_doc is not None
    assert person_linked_event_doc["version"] == 2 # Assuming this order
    assert person_linked_event_doc["payload"]["profile"]["name"] == person1_profile.name
    assert person_linked_event_doc["payload"]["role_in_company"] == Role.DIRECTOR.value

    # BeneficialOwnerAddedEvent (aggregate_id is company_id)
    bo_added_event_doc = event_store.find_one({
        "aggregate_id": company_id,
        "event_type": "BeneficialOwnerAddedEvent",
        "payload.bo_id": bo1_id
    })
    assert bo_added_event_doc is not None
    assert bo_added_event_doc["version"] == 3 # Assuming this order
    assert bo_added_event_doc["payload"]["profile"]["name"] == bo1_profile.name
    assert bo_added_event_doc["payload"]["ownership_percentage"] == 75.0

    # CaseCreatedEvent (aggregate_id is kyb_case_id)
    case_created_event_doc = event_store.find_one({"aggregate_id": kyb_case_id, "event_type": "CaseCreatedEvent"})
    assert case_created_event_doc is not None
    assert case_created_event_doc["version"] == 1
    assert case_created_event_doc["payload"]["case_type"] == CaseType.KYB.value
    assert case_created_event_doc["payload"]["created_by"] == user_id
    assert case_created_event_doc["payload"]["company_id"] == company_id

    # NotificationRequiredEvent (aggregate_id is kyb_case_id)
    notification_event_doc = event_store.find_one({"aggregate_id": kyb_case_id, "event_type": "NotificationRequiredEvent"})
    assert notification_event_doc is not None
    assert notification_event_doc["payload"]["case_id"] == kyb_case_id
    assert notification_event_doc["payload"]["notification_type"] == "CASE_CREATED"

    mock_kafka_producer = mock_external_services["kafka_producer"]
    # Check if called for the KYB case (could be multiple calls if previous test ran in same scope without reset, but fixtures handle reset)
    mock_kafka_producer.produce_message.assert_any_call( # Use any_call if other calls are made
        topic=settings.KAFKA_NOTIFICATIONS_TOPIC,
        key={"case_id": kyb_case_id},
        value=ANY
    )


    # Read Model Verification
    # Case Read Model
    cases_collection = test_db_session[CASES_READ_MODEL_COLLECTION]
    case_read_model_doc = cases_collection.find_one({"case_id": kyb_case_id})
    assert case_read_model_doc is not None
    assert case_read_model_doc["case_type"] == CaseType.KYB.value
    assert case_read_model_doc["status"] == "PENDING"
    assert case_read_model_doc["company_id"] == company_id
    assert case_read_model_doc["version"] == 1
    assert isinstance(case_read_model_doc["created_at"], datetime)

    # Company Read Model
    companies_collection = test_db_session[COMPANIES_READ_MODEL_COLLECTION]
    company_read_model_doc = companies_collection.find_one({"company_id": company_id})
    assert company_read_model_doc is not None
    assert company_read_model_doc["name"] == company_profile_data.name
    assert company_read_model_doc["registration_number"] == company_profile_data.registration_number
    assert company_read_model_doc["version"] == 1 # Version of CompanyProfileCreatedEvent

    # Person-Company Link Read Model (adjust based on your schema for PersonCompanyLinkDB)
    # This could be a separate collection or part of the company/person read models.
    # Assuming a separate collection 'person_company_links' for PersonCompanyLinkDB type entries
    person_links_collection = test_db_session[PERSON_COMPANY_LINKS_COLLECTION]
    person_link_doc = person_links_collection.find_one({"person_id": person1_id, "company_id": company_id})
    if person_link_doc: # If stored separately
        assert person_link_doc["name"] == person1_profile.name
        assert person_link_doc["email"] == person1_profile.email
        assert person_link_doc["role_in_company"] == Role.DIRECTOR.value
        assert person_link_doc["version"] == 2 # Version of PersonLinkedToCompanyEvent
    else: # Fallback: Check if embedded in Company read model
        company_doc_for_person_check = companies_collection.find_one({"company_id": company_id})
        assert company_doc_for_person_check is not None
        found_person_in_company = next((p for p in company_doc_for_person_check.get("persons", []) if p.get("person_id") == person1_id), None)
        assert found_person_in_company is not None, f"Person {person1_id} not found in company's persons list."
        assert found_person_in_company["name"] == person1_profile.name
        assert found_person_in_company["role_in_company"] == Role.DIRECTOR.value


    # Beneficial Owner Read Model (adjust based on your schema for BeneficialOwnerDB)
    # Assuming a separate collection 'beneficial_owners' for BeneficialOwnerDB type entries
    bo_collection = test_db_session[BENEFICIAL_OWNERS_READ_MODEL_COLLECTION]
    bo_read_model_doc = bo_collection.find_one({"bo_id": bo1_id, "company_id": company_id})
    if bo_read_model_doc: # If stored separately
        assert bo_read_model_doc["name"] == bo1_profile.name
        assert bo_read_model_doc["ownership_percentage"] == 75.0
        assert bo_read_model_doc["version"] == 3 # Version of BeneficialOwnerAddedEvent
    else: # Fallback: Check if embedded in Company read model
        company_doc_for_bo_check = companies_collection.find_one({"company_id": company_id})
        assert company_doc_for_bo_check is not None
        found_bo_in_company = next((bo for bo in company_doc_for_bo_check.get("beneficial_owners", []) if bo.get("bo_id") == bo1_id), None)
        assert found_bo_in_company is not None, f"BO {bo1_id} not found in company's BO list."
        assert found_bo_in_company["name"] == bo1_profile.name
        assert found_bo_in_company["ownership_percentage"] == 75.0


# Collection name for document requirements read model
DOCUMENT_REQUIREMENTS_READ_MODEL_COLLECTION = "document_requirements"

def test_determine_document_requirements_integration(
    test_client_with_mock_db: TestClient,
    test_db_session: MongoMockClient,
    mock_external_services: dict # Ensures Kafka/Notification mocks are in place
):
    # 1. Setup: Create a Case (Simplified KYC for this test)
    user_id = "doc_req_test_user"
    person1_id = str(uuid.uuid4()) # This will be our entity_id for document requirements
    person1_profile = PersonProfile(name="Doc Test Person", email="doc.person@example.com")

    initial_case_payload = {
        "case_type": CaseType.KYC.value,
        "created_by": user_id,
        "persons": [{
            "person_id": person1_id,
            "profile": person1_profile.model_dump(),
            "role": Role.PRIMARY_CONTACT.value
        }]
    }
    response_case_create = test_client_with_mock_db.post("/api/v1/cases", json=initial_case_payload)
    assert response_case_create.status_code == 202
    created_case_id = response_case_create.json()["case_id"]
    assert uuid.UUID(created_case_id)

    # Clear events from the case creation to focus on document events (optional, but good for clarity)
    # For this test, we'll check all events related to the case_id to see the full flow.
    # If we wanted to isolate: test_db_session[EVENT_STORE_COLLECTION].delete_many({"aggregate_id": created_case_id})
    # However, versioning relies on previous events, so clearing might be an issue if not handled carefully.
    # Better to assert based on event types and higher versions.

    # 2. Action: Determine Document Requirements
    # Assuming the standard KYC strategy for an individual in US requires e.g., PASSPORT and UTILITY_BILL
    # These expected documents depend on your concrete DocumentStrategy implementation.
    # For the purpose of this test, we'll check that *some* DocumentRequirementDeterminedEvent(s) are created.

    determine_req_payload = {
        "case_id": created_case_id,
        "entity_id": person1_id, # Document requirements for the person created
        "entity_type": "INDIVIDUAL", # From service.models.EntityType
        "case_type": CaseType.KYC.value, # Could also be KYB
        "country_code": "US", # Example country
        "traitement_type": "STANDARD_RISK", # Example, from service.models.TraitementType
        "created_by": user_id
    }

    response_determine_req = test_client_with_mock_db.post(
        "/api/v1/documents/determine-requirements",
        json=determine_req_payload
    )

    # 3. Assertions
    # API Response
    assert response_determine_req.status_code == 202
    assert response_determine_req.json() == {"message": "Document requirements determination process started."}

    # Event Store Verification
    event_store = test_db_session[EVENT_STORE_COLLECTION]

    # Find DocumentRequirementDeterminedEvent(s)
    # Events from case creation will have lower versions. Doc events will have higher versions.
    # We need to find the version of the last event from case creation to predict doc event versions.
    last_case_creation_event = event_store.find_one(
        {"aggregate_id": created_case_id},
        sort=[("version", -1)] # Get the last event for this aggregate
    )
    assert last_case_creation_event is not None
    current_version = last_case_creation_event["version"]


    doc_req_events = list(event_store.find({
        "aggregate_id": created_case_id,
        "event_type": "DocumentRequirementDeterminedEvent",
        "version": {"$gt": current_version} # Ensure we are looking at new events
    }).sort("version", 1)) # Sort by version to check them in order

    assert len(doc_req_events) > 0, "No DocumentRequirementDeterminedEvent found"

    # Example: Assuming at least one document (e.g., PASSPORT) is determined
    # This part is highly dependent on the actual strategy logic.
    # For a robust test, you might need to know what your default strategy returns for KYC/US/Individual.

    first_doc_req_event = doc_req_events[0]
    assert first_doc_req_event["payload"]["case_id"] == created_case_id
    assert first_doc_req_event["payload"]["entity_id"] == person1_id
    assert first_doc_req_event["payload"]["entity_type"] == "INDIVIDUAL"
    assert first_doc_req_event["payload"]["determined_by"] == user_id
    assert "document_id" in first_doc_req_event["payload"]
    assert "document_type" in first_doc_req_event["payload"] # e.g., "PASSPORT"
    assert "description" in first_doc_req_event["payload"]
    assert first_doc_req_event["payload"]["status"] == "AWAITING_UPLOAD" # from service.models.DocumentStatus
    assert first_doc_req_event["payload"]["is_required"] is True # Example, could be False

    # Read Models Verification
    doc_req_collection = test_db_session[DOCUMENT_REQUIREMENTS_READ_MODEL_COLLECTION]

    # Verify based on one of the determined documents (e.g., the first one from events)
    determined_doc_id = first_doc_req_event["payload"]["document_id"]
    doc_read_model = doc_req_collection.find_one({"document_id": determined_doc_id, "case_id": created_case_id})

    assert doc_read_model is not None
    assert doc_read_model["entity_id"] == person1_id
    assert doc_read_model["entity_type"] == "INDIVIDUAL"
    assert doc_read_model["document_type"] == first_doc_req_event["payload"]["document_type"]
    assert doc_read_model["status"] == "AWAITING_UPLOAD"
    assert doc_read_model["is_required"] == first_doc_req_event["payload"]["is_required"]
    assert doc_read_model["created_by"] == user_id # Projector maps determined_by to created_by
    assert isinstance(doc_read_model["created_at"], datetime)
    assert isinstance(doc_read_model["updated_at"], datetime)
    assert doc_read_model["version"] == first_doc_req_event["version"]

    # If multiple documents are expected, loop through doc_req_events and verify each in read model
    for i, event_doc in enumerate(doc_req_events):
        doc_id = event_doc["payload"]["document_id"]
        rm_doc = doc_req_collection.find_one({"document_id": doc_id, "case_id": created_case_id})
        assert rm_doc is not None
        assert rm_doc["version"] == event_doc["version"]
        assert rm_doc["status"] == "AWAITING_UPLOAD"

    # Ensure the collection for document requirements is cleared for subsequent tests
    # This is handled by the test_db_session fixture if DOCUMENT_REQUIREMENTS_READ_MODEL_COLLECTION is added there.
    # Add DOCUMENT_REQUIREMENTS_READ_MODEL_COLLECTION to the test_db_session fixture's clear list.
    if DOCUMENT_REQUIREMENTS_READ_MODEL_COLLECTION not in [EVENT_STORE_COLLECTION, CASES_READ_MODEL_COLLECTION, PERSONS_READ_MODEL_COLLECTION, COMPANIES_READ_MODEL_COLLECTION, BENEFICIAL_OWNERS_READ_MODEL_COLLECTION, PERSON_COMPANY_LINKS_COLLECTION]:
         test_db_session[DOCUMENT_REQUIREMENTS_READ_MODEL_COLLECTION].delete_many({}) # Manual clear if not in fixture


def test_update_document_status_integration(
    test_client_with_mock_db: TestClient,
    test_db_session: MongoMockClient,
    mock_external_services: dict
):
    # 1. Setup: Create Case and Determine Document Requirements
    user_id = "doc_status_updater"
    person_id_for_docs = str(uuid.uuid4())
    initial_case_payload = {
        "case_type": CaseType.KYC.value,
        "created_by": user_id,
        "persons": [{"person_id": person_id_for_docs, "profile": {"name": "Update Test Person", "email": "update.test@example.com"}, "role": Role.PRIMARY_CONTACT.value}]
    }
    response_case_create = test_client_with_mock_db.post("/api/v1/cases", json=initial_case_payload)
    assert response_case_create.status_code == 202
    created_case_id = response_case_create.json()["case_id"]

    determine_req_payload = {
        "case_id": created_case_id, "entity_id": person_id_for_docs, "entity_type": "INDIVIDUAL",
        "case_type": CaseType.KYC.value, "country_code": "US", "traitement_type": "STANDARD_RISK", "created_by": user_id
    }
    response_determine_req = test_client_with_mock_db.post("/api/v1/documents/determine-requirements", json=determine_req_payload)
    assert response_determine_req.status_code == 202

    # Fetch the created document requirement from read model to get its ID and current version
    doc_req_collection = test_db_session[DOCUMENT_REQUIREMENTS_READ_MODEL_COLLECTION]
    # The mocked strategy in mock_external_services returns one "PASSPORT" doc.
    created_doc_req = doc_req_collection.find_one({"case_id": created_case_id, "entity_id": person_id_for_docs, "document_type": "PASSPORT"})
    assert created_doc_req is not None, "Setup failed: Document requirement not found in read model"
    doc_req_id_to_update = created_doc_req["document_id"] # This is the business ID
    initial_doc_version = created_doc_req["version"]
    old_status = created_doc_req["status"] # Should be AWAITING_UPLOAD

    # 2. Action: Update Document Status
    new_status = DocumentStatus.UPLOADED.value
    s3_path = "/uploads/passport_test.pdf"
    file_name = "passport_test.pdf"

    update_status_payload = {
        "status": new_status,
        "updated_by": user_id,
        "s3_path": s3_path,
        "file_name": file_name
    }

    response_update_status = test_client_with_mock_db.put(
        f"/api/v1/documents/{doc_req_id_to_update}/status",
        json=update_status_payload
    )

    # 3. Assertions
    # API Response
    assert response_update_status.status_code == 200
    updated_doc_response = response_update_status.json()
    assert updated_doc_response["document_id"] == doc_req_id_to_update
    assert updated_doc_response["status"] == new_status
    assert updated_doc_response["version"] == initial_doc_version + 1
    assert updated_doc_response["s3_path"] == s3_path
    assert updated_doc_response["file_name"] == file_name
    assert updated_doc_response["updated_by"] == user_id

    # Event Store Verification
    event_store = test_db_session[EVENT_STORE_COLLECTION]

    # DocumentStatusUpdatedEvent - aggregate_id is case_id
    status_updated_event_doc = event_store.find_one({
        "aggregate_id": created_case_id, # Events are aggregated by case_id for documents
        "event_type": "DocumentStatusUpdatedEvent",
        "payload.document_id": doc_req_id_to_update
    })
    assert status_updated_event_doc is not None
    assert status_updated_event_doc["version"] == initial_doc_version + 1
    assert status_updated_event_doc["payload"]["old_status"] == old_status
    assert status_updated_event_doc["payload"]["new_status"] == new_status
    assert status_updated_event_doc["payload"]["updated_by"] == user_id
    assert status_updated_event_doc["payload"]["s3_path"] == s3_path
    assert status_updated_event_doc["payload"]["file_name"] == file_name

    # Read Model Verification
    updated_doc_read_model = doc_req_collection.find_one({"document_id": doc_req_id_to_update, "case_id": created_case_id})
    assert updated_doc_read_model is not None
    assert updated_doc_read_model["status"] == new_status
    assert updated_doc_read_model["version"] == initial_doc_version + 1
    assert updated_doc_read_model["s3_path"] == s3_path
    assert updated_doc_read_model["file_name"] == file_name
    assert updated_doc_read_model["updated_by"] == user_id
    assert updated_doc_read_model["updated_at"] > updated_doc_read_model["created_at"]
