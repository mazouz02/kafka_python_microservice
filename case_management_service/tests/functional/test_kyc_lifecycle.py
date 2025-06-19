import pytest
import uuid
from datetime import datetime, timezone # Not strictly needed for API calls but good for DB checks if comparing dates
from unittest.mock import patch, AsyncMock, ANY # ANY might be useful for some DB checks

from fastapi.testclient import TestClient
from mongomock import MongoClient as MongoMockClient # For type hinting if needed

from app.main import app
from app.api.dependencies import get_db
from app.config import settings
from app.service.models import CaseType, Role, PersonProfile, DocumentStatus, EntityType # Enums
from app.service.events.events import ( # For DB checks if looking at event types
    CaseCreatedEvent, PersonAddedToCaseEvent,
    DocumentRequirementDeterminedEvent, DocumentStatusUpdatedEvent,
    NotificationRequiredEvent
)
# Import schemas for request/response validation if needed, though direct dicts are often used for payloads
# from app.api.v1.endpoints.cases import CreateCaseRequest # Example, actual model is CreateCaseCommand
# from app.api.v1.endpoints.documents import DetermineDocRequirementsRequest, UpdateDocStatusRequest


# --- Fixtures ---
# Re-using fixtures from integration tests by placing them in a common conftest.py
# or by redefining them here if they are specific or need adaptation.
# For this exercise, let's assume they could be imported from a common test support module
# or are simple enough to redefine/adapt.

# Collection names (ensure these match your application's definitions)
EVENT_STORE_COLLECTION = settings.EVENT_STORE_COLLECTION_NAME
CASES_READ_MODEL_COLLECTION = settings.CASES_READ_MODEL_COLLECTION_NAME
# Assuming persons linked to cases are stored embedded in the case or in a specific collection
PERSONS_READ_MODEL_COLLECTION = "persons" # Placeholder, adjust if needed, or check embedded
DOCUMENT_REQUIREMENTS_READ_MODEL_COLLECTION = "document_requirements"
COMPANIES_READ_MODEL_COLLECTION = "companies"
BENEFICIAL_OWNERS_READ_MODEL_COLLECTION = "beneficial_owners"
PERSON_COMPANY_LINKS_COLLECTION = "person_company_links"


@pytest.fixture(scope="function")
def test_db_session():
    client = MongoMockClient()
    db = client[settings.MONGODB_DATABASE_NAME]
    collections_to_clear = [
        EVENT_STORE_COLLECTION, CASES_READ_MODEL_COLLECTION, PERSONS_READ_MODEL_COLLECTION,
        DOCUMENT_REQUIREMENTS_READ_MODEL_COLLECTION, COMPANIES_READ_MODEL_COLLECTION,
        BENEFICIAL_OWNERS_READ_MODEL_COLLECTION, PERSON_COMPANY_LINKS_COLLECTION
    ]
    for coll_name in collections_to_clear:
        db[coll_name].delete_many({})
    yield db
    client.close()

@pytest.fixture(scope="function")
def test_client_with_mock_db(test_db_session: MongoMockClient):
    app.dependency_overrides[get_db] = lambda: test_db_session
    yield TestClient(app)
    app.dependency_overrides = {}

@pytest.fixture(autouse=True) # Apply to all tests in this module
def mock_functional_external_services():
    """
    Mocks external services like Kafka, NotificationConfig, and DocumentStrategy
    for functional tests.
    """
    with patch("app.service.commands.handlers.get_kafka_producer", new_callable=AsyncMock) as mock_get_kafka, \
         patch("app.service.commands.handlers.get_notification_config_client", new_callable=AsyncMock) as mock_get_notif_client, \
         patch("app.service.commands.handlers.get_document_strategy", new_callable=AsyncMock) as mock_get_doc_strategy:

        mock_kafka_producer = AsyncMock()
        mock_kafka_producer.produce_message = AsyncMock(return_value=None)
        mock_get_kafka.return_value = mock_kafka_producer

        mock_notif_client = AsyncMock()
        mock_notif_client.get_notification_strategy = AsyncMock(return_value="SEND_ALL")
        mock_get_notif_client.return_value = mock_notif_client

        mock_doc_strategy_instance = AsyncMock()
        # The get_document_requirements method will be configured per-test.
        mock_doc_strategy_instance.get_document_requirements = AsyncMock()
        mock_get_doc_strategy.return_value = mock_doc_strategy_instance

        yield {
            "kafka_producer": mock_kafka_producer,
            "notification_config_client": mock_notif_client,
            "document_strategy": mock_doc_strategy_instance
        }

# --- Full KYC Case Lifecycle Test ---

def test_full_kyc_case_lifecycle(
    test_client_with_mock_db: TestClient,
    test_db_session: MongoMockClient,
    mock_functional_external_services: dict # Ensures mocks are active
):
    user_id = "functional_test_user"
    person1_id = str(uuid.uuid4())
    person1_profile = PersonProfile(name="Functional Test User One", email="functional.user@example.com")

    # --- Step 1: Create a KYC Case ---
    create_case_payload = {
        "case_type": CaseType.KYC.value,
        "created_by": user_id,
        "persons": [{
            "person_id": person1_id,
            "profile": person1_profile.model_dump(),
            "role": Role.PRIMARY_CONTACT.value
        }]
    }
    response_create_case = test_client_with_mock_db.post("/api/v1/cases", json=create_case_payload)
    assert response_create_case.status_code == 202
    case_data = response_create_case.json()
    case_id = case_data["case_id"]
    assert uuid.UUID(case_id)

    # Optional DB Check for Step 1 (example for CaseCreatedEvent)
    event_store = test_db_session[EVENT_STORE_COLLECTION]
    case_created_event = event_store.find_one({"aggregate_id": case_id, "event_type": CaseCreatedEvent.__name__})
    assert case_created_event is not None
    assert case_created_event["payload"]["created_by"] == user_id

    # --- Step 2: Determine Document Requirements ---
    # Explicitly configure the document strategy mock for this KYC/Person scenario
    mock_doc_strategy = mock_functional_external_services["document_strategy"]
    from app.service.models import DocumentSpecification # For type hinting
    kyc_person_docs_specs = [
        DocumentSpecification(document_id=str(uuid.uuid4()), document_type="PASSPORT", description="Valid Passport for KYC", country_code="US", required=True),
        DocumentSpecification(document_id=str(uuid.uuid4()), document_type="UTILITY_BILL", description="Proof of Address for KYC", country_code="US", required=True)
    ]
    mock_doc_strategy.get_document_requirements.return_value = kyc_person_docs_specs

    determine_req_payload = {
        "case_id": case_id,
        "entity_id": person1_id,
        "entity_type": EntityType.INDIVIDUAL.value,
        "case_type": CaseType.KYC.value,
        "country_code": "US",
        "traitement_type": "STANDARD_RISK", # Example
        "created_by": user_id
    }
    response_determine_docs = test_client_with_mock_db.post("/api/v1/documents/determine-requirements", json=determine_req_payload)
    assert response_determine_docs.status_code == 202
    assert response_determine_docs.json()["message"] == "Document requirements determination process started."

    # DB Check for Step 2
    doc_req_events = list(event_store.find({"aggregate_id": case_id, "event_type": DocumentRequirementDeterminedEvent.__name__}))
    # Based on mocked strategy, we expect 2 documents (PASSPORT, UTILITY_BILL)
    assert len(doc_req_events) == 2

    doc_req_read_models = list(test_db_session[DOCUMENT_REQUIREMENTS_READ_MODEL_COLLECTION].find({"case_id": case_id}))
    assert len(doc_req_read_models) == 2
    passport_req = next((d for d in doc_req_read_models if d["document_type"] == "PASSPORT"), None)
    assert passport_req is not None
    assert passport_req["status"] == DocumentStatus.AWAITING_UPLOAD.value

    # --- Step 3: List Document Requirements for the Case ---
    response_list_docs = test_client_with_mock_db.get(f"/api/v1/documents/case/{case_id}")
    assert response_list_docs.status_code == 200
    listed_docs = response_list_docs.json()
    assert len(listed_docs) == 2
    passport_req_listed = next((d for d in listed_docs if d["document_type"] == "PASSPORT"), None)
    assert passport_req_listed is not None
    assert passport_req_listed["status"] == DocumentStatus.AWAITING_UPLOAD.value
    document_requirement_id_to_update = passport_req_listed["document_id"] # Use the business ID

    # --- Step 4: Update Document Status (to UPLOADED) ---
    s3_path_uploaded = "/uploads/passport_functional.pdf"
    file_name_uploaded = "passport_functional.pdf"
    update_status_payload_uploaded = {
        "status": DocumentStatus.UPLOADED.value,
        "updated_by": user_id,
        "s3_path": s3_path_uploaded,
        "file_name": file_name_uploaded
    }
    response_update_uploaded = test_client_with_mock_db.put(
        f"/api/v1/documents/{document_requirement_id_to_update}/status",
        json=update_status_payload_uploaded
    )
    assert response_update_uploaded.status_code == 200
    updated_doc_uploaded = response_update_uploaded.json()
    assert updated_doc_uploaded["status"] == DocumentStatus.UPLOADED.value
    assert updated_doc_uploaded["s3_path"] == s3_path_uploaded
    initial_version = passport_req_listed["version"] # Version from listing
    assert updated_doc_uploaded["version"] == initial_version + 1

    # DB Check for Step 4
    doc_status_event_uploaded = event_store.find_one({
        "aggregate_id": case_id,
        "event_type": DocumentStatusUpdatedEvent.__name__,
        "payload.document_id": document_requirement_id_to_update,
        "payload.new_status": DocumentStatus.UPLOADED.value
    })
    assert doc_status_event_uploaded is not None
    read_model_uploaded = test_db_session[DOCUMENT_REQUIREMENTS_READ_MODEL_COLLECTION].find_one({"document_id": document_requirement_id_to_update})
    assert read_model_uploaded["status"] == DocumentStatus.UPLOADED.value
    assert read_model_uploaded["version"] == initial_version + 1

    # --- Step 5: Update Document Status Again (to APPROVED) ---
    update_status_payload_approved = {
        "status": DocumentStatus.APPROVED.value,
        "updated_by": user_id,
        # s3_path and file_name might be retained or cleared by handler, test assumes they are retained or re-provided if needed
    }
    response_update_approved = test_client_with_mock_db.put(
        f"/api/v1/documents/{document_requirement_id_to_update}/status",
        json=update_status_payload_approved
    )
    assert response_update_approved.status_code == 200
    updated_doc_approved = response_update_approved.json()
    assert updated_doc_approved["status"] == DocumentStatus.APPROVED.value
    assert updated_doc_approved["version"] == initial_version + 2 # Incremented again

    # DB Check for Step 5
    read_model_approved = test_db_session[DOCUMENT_REQUIREMENTS_READ_MODEL_COLLECTION].find_one({"document_id": document_requirement_id_to_update})
    assert read_model_approved["status"] == DocumentStatus.APPROVED.value
    assert read_model_approved["version"] == initial_version + 2

    # --- Step 6: Get Specific Document Requirement ---
    response_get_specific_doc = test_client_with_mock_db.get(f"/api/v1/documents/{document_requirement_id_to_update}")
    assert response_get_specific_doc.status_code == 200
    specific_doc_data = response_get_specific_doc.json()
    assert specific_doc_data["status"] == DocumentStatus.APPROVED.value
    assert specific_doc_data["version"] == initial_version + 2

    # --- Step 7: Get Case Details (Optional check) ---
    response_get_case = test_client_with_mock_db.get(f"/api/v1/cases/{case_id}")
    assert response_get_case.status_code == 200
    final_case_details = response_get_case.json()
    # Check if case status changed or if document details are reflected in the case read model
    # For example, if the case read model aggregates document statuses:
    # found_doc_in_case = next((d for d in final_case_details.get("required_documents", []) if d["document_id"] == document_requirement_id_to_update), None)
    # assert found_doc_in_case is not None
    # assert found_doc_in_case["status"] == DocumentStatus.APPROVED.value
    assert final_case_details["case_id"] == case_id # Basic check


# --- Simplified KYB Case Lifecycle Test ---

def test_simplified_kyb_case_lifecycle(
    test_client_with_mock_db: TestClient,
    test_db_session: MongoMockClient,
    mock_functional_external_services: dict # Provides mocked services
):
    user_id = "functional_kyb_user"
    company_id = str(uuid.uuid4())
    # Use CompanyProfile model for company_profile data
    from app.service.models import CompanyProfile as CompanyProfileModel

    person_id_director = str(uuid.uuid4())

    company_profile_data = CompanyProfileModel(name="Func Test Corp", registration_number="FTC-002", country_of_incorporation="US", address="123 Test Lane")
    director_profile = PersonProfile(name="Ms. Kyb Director", email="director.kyb@ftc.com")

    # --- Step 1: Create a KYB Case ---
    create_kyb_payload = {
        "case_type": CaseType.KYB.value,
        "created_by": user_id,
        "company_profile": {"company_id": company_id, "profile": company_profile_data.model_dump()},
        "persons": [{
            "person_id": person_id_director,
            "profile": director_profile.model_dump(),
            "role_in_company": Role.DIRECTOR.value
        }]
    }
    response_create_kyb_case = test_client_with_mock_db.post("/api/v1/cases", json=create_kyb_payload)
    assert response_create_kyb_case.status_code == 202
    kyb_case_data = response_create_kyb_case.json()
    kyb_case_id = kyb_case_data["case_id"]
    assert uuid.UUID(kyb_case_id)

    event_store = test_db_session[EVENT_STORE_COLLECTION]
    company_created_event = event_store.find_one({"aggregate_id": company_id, "event_type": "CompanyProfileCreatedEvent"})
    assert company_created_event is not None
    assert company_created_event["payload"]["profile"]["name"] == company_profile_data.name

    # --- Step 2: Determine Document Requirements for the Company ---
    mock_doc_strategy = mock_functional_external_services["document_strategy"]
    from app.service.models import DocumentSpecification
    company_docs_specs = [
        DocumentSpecification(document_id=str(uuid.uuid4()), document_type="CERTIFICATE_OF_INCORPORATION", description="COI", country_code="US", required=True),
        DocumentSpecification(document_id=str(uuid.uuid4()), document_type="ARTICLES_OF_ASSOCIATION", description="AOA", country_code="US", required=True)
    ]
    mock_doc_strategy.get_document_requirements.return_value = company_docs_specs

    determine_company_docs_payload = {
        "case_id": kyb_case_id,
        "entity_id": company_id,
        "entity_type": EntityType.COMPANY.value,
        "case_type": CaseType.KYB.value,
        "country_code": "US",
        "traitement_type": "STANDARD_RISK",
        "created_by": user_id
    }
    response_determine_company_docs = test_client_with_mock_db.post("/api/v1/documents/determine-requirements", json=determine_company_docs_payload)
    assert response_determine_company_docs.status_code == 202

    company_doc_req_events = list(event_store.find({"aggregate_id": kyb_case_id, "event_type": DocumentRequirementDeterminedEvent.__name__, "payload.entity_id": company_id}))
    assert len(company_doc_req_events) == 2

    doc_req_read_models_company = list(test_db_session[DOCUMENT_REQUIREMENTS_READ_MODEL_COLLECTION].find({"case_id": kyb_case_id, "entity_id": company_id}))
    assert len(doc_req_read_models_company) == 2
    coi_req = next((d for d in doc_req_read_models_company if d["document_type"] == "CERTIFICATE_OF_INCORPORATION"), None)
    assert coi_req is not None
    assert coi_req["status"] == DocumentStatus.AWAITING_UPLOAD.value

    # --- Step 3: List Document Requirements for the Case (focus on company) ---
    response_list_company_docs = test_client_with_mock_db.get(f"/api/v1/documents/case/{kyb_case_id}?entity_id={company_id}&entity_type={EntityType.COMPANY.value}")
    assert response_list_company_docs.status_code == 200
    listed_company_docs = response_list_company_docs.json()
    assert len(listed_company_docs) == 2
    coi_req_listed = next((d for d in listed_company_docs if d["document_type"] == "CERTIFICATE_OF_INCORPORATION"), None)
    assert coi_req_listed is not None
    company_doc_req_id_to_update = coi_req_listed["document_id"]

    # --- Step 4: Update Company Document Status ---
    update_company_doc_payload = {
        "status": DocumentStatus.REVIEW_PENDING.value,
        "updated_by": user_id,
        "s3_path": "/uploads/coi_functional.pdf",
        "file_name": "coi_functional.pdf"
    }
    response_update_company_doc = test_client_with_mock_db.put(
        f"/api/v1/documents/{company_doc_req_id_to_update}/status",
        json=update_company_doc_payload
    )
    assert response_update_company_doc.status_code == 200
    updated_company_doc_response = response_update_company_doc.json()
    assert updated_company_doc_response["status"] == DocumentStatus.REVIEW_PENDING.value
    company_doc_initial_version = coi_req_listed["version"]
    assert updated_company_doc_response["version"] == company_doc_initial_version + 1

    company_doc_status_event = event_store.find_one({
        "aggregate_id": kyb_case_id,
        "event_type": DocumentStatusUpdatedEvent.__name__,
        "payload.document_id": company_doc_req_id_to_update,
        "payload.new_status": DocumentStatus.REVIEW_PENDING.value
    })
    assert company_doc_status_event is not None
    company_read_model_updated = test_db_session[DOCUMENT_REQUIREMENTS_READ_MODEL_COLLECTION].find_one({"document_id": company_doc_req_id_to_update})
    assert company_read_model_updated["status"] == DocumentStatus.REVIEW_PENDING.value

    # --- Step 5: Verify Company Data (Direct DB Check) ---
    company_read_model = test_db_session[COMPANIES_READ_MODEL_COLLECTION].find_one({"company_id": company_id})
    assert company_read_model is not None
    assert company_read_model["name"] == company_profile_data.name # Adjusted to use company_profile_data

    person_link_read_model = test_db_session[PERSON_COMPANY_LINKS_COLLECTION].find_one({"company_id": company_id, "person_id": person_id_director})
    if person_link_read_model:
        assert person_link_read_model["name"] == director_profile.name
        assert person_link_read_model["role_in_company"] == Role.DIRECTOR.value
    else:
        found_director_in_company = next((p for p in company_read_model.get("persons", []) if p.get("person_id") == person_id_director), None)
        assert found_director_in_company is not None, "Director not found linked in company read model"
        assert found_director_in_company["name"] == director_profile.name
        assert found_director_in_company["role_in_company"] == Role.DIRECTOR.value
