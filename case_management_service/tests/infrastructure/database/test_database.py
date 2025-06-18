# Unit Tests for Database Functions (Refactored Structure)
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock, call
import datetime
import uuid

# Modules to test - new locations
from case_management_service.infrastructure.database import connection as db_connection
from case_management_service.infrastructure.database import event_store as db_event_store
from case_management_service.infrastructure.database import read_models as db_read_models
from case_management_service.infrastructure.database import raw_event_store as db_raw_event_store
# Import the new store module
from case_management_service.infrastructure.database import document_requirements_store as db_doc_req_store
# Updated schema import to include all necessary schemas
from case_management_service.infrastructure.database import schemas as db_schemas
from case_management_service.app.service.events import models as domain_event_models
from case_management_service.app import config
from case_management_service.infrastructure.kafka.schemas import AddressData


# Helper to reset global db client in database.connection module
def reset_db_connection_module_state():
    db_connection.client = None
    db_connection.db = None

# Helper for async iterable mock
async def async_iterable(items):
    for item in items:
        yield item

class TestDatabaseInfrastructure(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        reset_db_connection_module_state()
        self.test_db_name = config.settings.DB_NAME

    def tearDown(self):
        reset_db_connection_module_state()

    # --- Tests for infrastructure.database.connection ---
    @patch('case_management_service.infrastructure.database.connection.MongoClient')
    async def test_connect_to_mongo_success(self, mock_mongo_client_cls):
        mock_client_instance = MagicMock()
        mock_client_instance.admin.command.return_value = {"ok": 1}
        mock_mongo_client_cls.return_value = mock_client_instance

        db_connection.connect_to_mongo()

        mock_mongo_client_cls.assert_called_once_with(config.settings.MONGO_DETAILS)
        mock_client_instance.admin.command.assert_called_once_with('ping')
        self.assertEqual(db_connection.db, mock_client_instance[self.test_db_name])

        db_instance = await db_connection.get_database()
        self.assertEqual(db_instance, mock_client_instance[self.test_db_name])
        self.assertEqual(mock_mongo_client_cls.call_count, 1)

    @patch('case_management_service.infrastructure.database.connection.MongoClient', side_effect=ConnectionError("Mock Connection Error"))
    async def test_connect_to_mongo_failure(self, mock_mongo_client_cls):
        with self.assertRaisesRegex(ConnectionError, "Failed to connect to MongoDB: Mock Connection Error"):
            db_connection.connect_to_mongo()
        with self.assertRaisesRegex(ConnectionError, "Failed to connect to MongoDB: Mock Connection Error"):
            await db_connection.get_database()

    # --- Tests for infrastructure.database.event_store ---
    @patch('case_management_service.infrastructure.database.event_store.get_database')
    async def test_save_event_new_aggregate(self, mock_get_db_for_event_store):
        mock_db_instance = AsyncMock()
        mock_db_instance[db_event_store.EVENT_STORE_COLLECTION].find_one = AsyncMock(return_value=None)
        mock_db_instance[db_event_store.EVENT_STORE_COLLECTION].insert_one = AsyncMock()
        mock_get_db_for_event_store.return_value = mock_db_instance

        agg_id = str(uuid.uuid4())
        event_payload_model = domain_event_models.CaseCreatedEventPayload(
            client_id="c1", case_type="t1", case_version="v1", traitement_type="KYC"
        )
        event_to_save = domain_event_models.CaseCreatedEvent(
            aggregate_id=agg_id, payload=event_payload_model, version=1, event_type="CaseCreated"
        )

        returned_event = await db_event_store.save_event(event_to_save)

        mock_db_instance[db_event_store.EVENT_STORE_COLLECTION].insert_one.assert_called_once()
        inserted_doc = mock_db_instance[db_event_store.EVENT_STORE_COLLECTION].insert_one.call_args.args[0]
        self.assertIsInstance(inserted_doc, dict)
        self.assertEqual(inserted_doc["aggregate_id"], agg_id)
        self.assertEqual(inserted_doc["event_type"], "CaseCreated")
        self.assertEqual(inserted_doc["payload"]["client_id"], "c1")
        self.assertEqual(returned_event, event_to_save)

    # Test for new DB Schemas (Instantiation)
    def test_company_profile_db_schema_instantiation(self):
        addr = AddressData(street="1 Corp Ave", city="Corpville", country="CY", postal_code="123")
        now = datetime.datetime.now(datetime.UTC)
        company_db = db_schemas.CompanyProfileDB(
            id="comp_123",
            registered_name="Corp Inc",
            registration_number="C123",
            country_of_incorporation="CY",
            registered_address=addr
            # created_at and updated_at will use default_factory
        )
        self.assertEqual(company_db.id, "comp_123")
        self.assertEqual(company_db.registered_address.city, "Corpville")
        self.assertIsNotNone(company_db.created_at)
        self.assertIsNotNone(company_db.updated_at)


    def test_beneficial_owner_db_schema_instantiation(self):
        bo_db = db_schemas.BeneficialOwnerDB(
            id="bo_123",
            company_id="comp_123",
            firstname="Beneficial",
            lastname="Owner",
            is_ubo=True
            # created_at and updated_at will use default_factory
        )
        self.assertEqual(bo_db.id, "bo_123")
        self.assertEqual(bo_db.firstname, "Beneficial")
        self.assertIsNotNone(bo_db.created_at)
        self.assertIsNotNone(bo_db.updated_at)

    def test_required_document_db_schema_instantiation(self): # New test for RequiredDocumentDB
        doc_req = db_schemas.RequiredDocumentDB(
            case_id="case_doc_test",
            entity_id="entity_doc_test",
            entity_type="PERSON",
            document_type="PASSPORT"
            # id, status, is_required, created_at, updated_at will use default_factory
        )
        self.assertIsNotNone(doc_req.id)
        self.assertEqual(doc_req.case_id, "case_doc_test")
        self.assertEqual(doc_req.status, "AWAITING_UPLOAD")
        self.assertTrue(doc_req.is_required)


    # Tests for New Read Model Operations
    @patch('case_management_service.infrastructure.database.read_models.get_database')
    async def test_upsert_company_read_model(self, mock_get_db_for_read_models):
        mock_db_instance = AsyncMock()
        mock_db_instance.companies.replace_one = AsyncMock()
        mock_get_db_for_read_models.return_value = mock_db_instance

        addr = AddressData(street="Test St", city="Test City", country="TC", postal_code="TS1")
        company_data = db_schemas.CompanyProfileDB(
            id="comp001", registered_name="Comp Name", registration_number="R001",
            country_of_incorporation="TC", registered_address=addr
        )
        await db_read_models.upsert_company_read_model(company_data)

        mock_db_instance.companies.replace_one.assert_called_once()
        filter_arg = mock_db_instance.companies.replace_one.call_args.args[0]
        doc_arg = mock_db_instance.companies.replace_one.call_args.args[1]
        self.assertEqual(filter_arg, {"id": "comp001"})
        self.assertEqual(doc_arg["registered_name"], "Comp Name")

    @patch('case_management_service.infrastructure.database.read_models.get_database')
    async def test_upsert_beneficial_owner_read_model(self, mock_get_db_for_read_models):
        mock_db_instance = AsyncMock()
        mock_db_instance.beneficial_owners.replace_one = AsyncMock()
        mock_get_db_for_read_models.return_value = mock_db_instance

        bo_data = db_schemas.BeneficialOwnerDB(
            id="bo001", company_id="comp001", firstname="BoName", lastname="BoLast"
        )
        await db_read_models.upsert_beneficial_owner_read_model(bo_data)

        mock_db_instance.beneficial_owners.replace_one.assert_called_once()
        filter_arg = mock_db_instance.beneficial_owners.replace_one.call_args.args[0]
        doc_arg = mock_db_instance.beneficial_owners.replace_one.call_args.args[1]
        self.assertEqual(filter_arg, {"id": "bo001"})
        self.assertEqual(doc_arg["firstname"], "BoName")

    @patch('case_management_service.infrastructure.database.event_store.get_database')
    async def test_get_events_for_aggregate_with_new_event_types(self, mock_get_db_for_event_store):
        mock_db_instance = AsyncMock()
        agg_id_case = str(uuid.uuid4())
        agg_id_company = str(uuid.uuid4())
        person_id_linked = str(uuid.uuid4())
        bo_id_unique = str(uuid.uuid4())

        addr_data = AddressData(street="s", city="c", country="US", postal_code="123")
        addr_data_dict = addr_data.model_dump()

        bo_person_details = domain_event_models.PersonData(firstname="BO", lastname="User", birthdate="1977-07-07")
        bo_person_details_dict = bo_person_details.model_dump()

        meta_dict = db_schemas.StoredEventMetaData().model_dump()

        case_event_doc = db_schemas.StoredEventDB(event_id=str(uuid.uuid4()), event_type="CaseCreated", aggregate_id=agg_id_case, timestamp=datetime.datetime.now(datetime.UTC), version=1, payload={"client_id": "c1", "case_type": "KYB", "case_version": "v1", "traitement_type": "KYB", "company_id": agg_id_company}, metadata=meta_dict).model_dump()
        company_event_docs = [
            db_schemas.StoredEventDB(event_id=str(uuid.uuid4()), event_type="CompanyProfileCreated", aggregate_id=agg_id_company, timestamp=datetime.datetime.now(datetime.UTC), version=1, payload={"registered_name": "Comp Ltd", "registration_number": "R1", "country_of_incorporation": "US", "registered_address": addr_data_dict}, metadata=meta_dict).model_dump(),
            db_schemas.StoredEventDB(event_id=str(uuid.uuid4()), event_type="BeneficialOwnerAdded", aggregate_id=agg_id_company, timestamp=datetime.datetime.now(datetime.UTC), version=2, payload={"beneficial_owner_id": bo_id_unique, "person_details": bo_person_details_dict, "is_ubo": True, "ownership_percentage": 50.0, "types_of_control": ["Voting Rights"]}, metadata=meta_dict).model_dump(),
            db_schemas.StoredEventDB(event_id=str(uuid.uuid4()), event_type="PersonLinkedToCompany", aggregate_id=agg_id_company, timestamp=datetime.datetime.now(datetime.UTC), version=3, payload={"person_id": person_id_linked, "firstname": "Dir", "lastname": "Ector", "role_in_company": "Director", "birthdate": "1980-08-08"}, metadata=meta_dict).model_dump()
        ]

        # Configure mock for find().sort()
        mock_find_result = MagicMock()
        mock_sort_result_case = MagicMock()
        mock_sort_result_case.__aiter__.return_value = iter([case_event_doc])
        mock_sort_result_company = MagicMock()
        mock_sort_result_company.__aiter__.return_value = iter(company_event_docs)
        mock_sort_result_empty = MagicMock()
        mock_sort_result_empty.__aiter__.return_value = iter([])

        def mock_find_side_effect(query_filter):
            agg_filter_id = query_filter.get("aggregate_id")
            # We need to return a mock that has a sort method
            current_find_mock = MagicMock()
            if agg_filter_id == agg_id_case:
                current_find_mock.sort.return_value = mock_sort_result_case
            elif agg_filter_id == agg_id_company:
                current_find_mock.sort.return_value = mock_sort_result_company
            else:
                current_find_mock.sort.return_value = mock_sort_result_empty
            return current_find_mock

        mock_db_instance[db_event_store.EVENT_STORE_COLLECTION].find.side_effect = mock_find_side_effect
        mock_get_db_for_event_store.return_value = mock_db_instance

        retrieved_events_case = await db_event_store.get_events_for_aggregate(agg_id_case)
        retrieved_events_company = await db_event_store.get_events_for_aggregate(agg_id_company)

        self.assertEqual(len(retrieved_events_case), 1)
        self.assertIsInstance(retrieved_events_case[0], domain_event_models.CaseCreatedEvent)
        self.assertEqual(retrieved_events_case[0].payload.traitement_type, "KYB")
        self.assertEqual(retrieved_events_case[0].payload.company_id, agg_id_company)

        self.assertEqual(len(retrieved_events_company), 3)
        self.assertIsInstance(retrieved_events_company[0], domain_event_models.CompanyProfileCreatedEvent)
        self.assertEqual(retrieved_events_company[0].payload.registered_name, "Comp Ltd")
        self.assertIsInstance(retrieved_events_company[1], domain_event_models.BeneficialOwnerAddedEvent)
        self.assertEqual(retrieved_events_company[1].payload.person_details.firstname, "BO")
        self.assertIsInstance(retrieved_events_company[2], domain_event_models.PersonLinkedToCompanyEvent)
        self.assertEqual(retrieved_events_company[2].payload.role_in_company, "Director")

    @patch('case_management_service.infrastructure.database.read_models.get_database')
    async def test_get_case_by_id_from_read_model(self, mock_get_db_for_read_models):
        mock_db_instance = AsyncMock()
        now = datetime.datetime.now(datetime.UTC)
        case_doc_from_db = {"id": "foundcase", "client_id": "c1", "version": "v1", "type": "t1",
                            "traitement_type": "KYC", "status": "OPEN",
                            "created_at": now, "updated_at": now}
        mock_db_instance.cases.find_one = AsyncMock(return_value=case_doc_from_db)
        mock_get_db_for_read_models.return_value = mock_db_instance

        result = await db_read_models.get_case_by_id_from_read_model("foundcase")
        self.assertIsInstance(result, db_schemas.CaseManagementDB)
        self.assertEqual(result.id, "foundcase")

        mock_db_instance.cases.find_one = AsyncMock(return_value=None)
        result_none = await db_read_models.get_case_by_id_from_read_model("notfoundcase")
        self.assertIsNone(result_none)

    @patch('case_management_service.infrastructure.database.raw_event_store.get_database')
    async def test_add_raw_event_to_store(self, mock_get_db_for_raw_store):
        mock_db_instance = AsyncMock()
        mock_db_instance.raw_events.insert_one = AsyncMock()
        mock_get_db_for_raw_store.return_value = mock_db_instance

        raw_payload = {"key": "value"}
        event_type = "RAW_TEST_EVENT"

        returned_event = await db_raw_event_store.add_raw_event_to_store(raw_payload, event_type)

        self.assertIsInstance(returned_event, db_schemas.RawEventDB)
        self.assertEqual(returned_event.payload, raw_payload)
        self.assertEqual(returned_event.event_type, event_type)
        mock_db_instance.raw_events.insert_one.assert_called_once()
        inserted_doc = mock_db_instance.raw_events.insert_one.call_args.args[0]
        self.assertEqual(inserted_doc["payload"], raw_payload)

    # --- Tests for infrastructure.database.document_requirements_store ---
    @patch('case_management_service.infrastructure.database.document_requirements_store.get_database')
    async def test_add_required_document(self, mock_get_db):
        mock_db_instance = AsyncMock()
        mock_db_instance[db_doc_req_store.DOCUMENT_REQUIREMENTS_COLLECTION].insert_one = AsyncMock()
        mock_get_db.return_value = mock_db_instance

        doc_req_data = db_schemas.RequiredDocumentDB(
            case_id="case1", entity_id="person1", entity_type="PERSON",
            document_type="PASSPORT", is_required=True
        )

        result = await db_doc_req_store.add_required_document(doc_req_data)

        self.assertEqual(result, doc_req_data)
        mock_db_instance[db_doc_req_store.DOCUMENT_REQUIREMENTS_COLLECTION].insert_one.assert_called_once()
        inserted_doc_arg = mock_db_instance[db_doc_req_store.DOCUMENT_REQUIREMENTS_COLLECTION].insert_one.call_args.args[0]
        self.assertEqual(inserted_doc_arg["id"], doc_req_data.id)
        self.assertEqual(inserted_doc_arg["document_type"], "PASSPORT")

    @patch('case_management_service.infrastructure.database.document_requirements_store.get_database')
    async def test_update_required_document_status_and_meta_success(self, mock_get_db):
        mock_db_instance = AsyncMock()
        doc_req_id = "doc_req_abc"
        now = datetime.datetime.now(datetime.UTC)
        updated_doc_from_db = {
            "id": doc_req_id, "case_id": "c1", "entity_id": "e1", "entity_type": "PERSON",
            "document_type": "ID_CARD", "status": "UPLOADED", "is_required": True,
            "metadata": {"upload_ref": "ref123"},
            "notes": ["Uploaded by user."],
            "created_at": now, "updated_at": now
        }
        mock_db_instance[db_doc_req_store.DOCUMENT_REQUIREMENTS_COLLECTION].update_one = AsyncMock(return_value=MagicMock(matched_count=1, modified_count=1))
        mock_db_instance[db_doc_req_store.DOCUMENT_REQUIREMENTS_COLLECTION].find_one = AsyncMock(return_value=updated_doc_from_db)
        mock_get_db.return_value = mock_db_instance

        new_status = "UPLOADED"
        metadata_changes = {"upload_ref": "ref123"}
        notes_to_add = ["Uploaded by user."]

        result = await db_doc_req_store.update_required_document_status_and_meta(
            doc_req_id, new_status, metadata_update=metadata_changes, notes_to_add=notes_to_add
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.id, doc_req_id)
        self.assertEqual(result.status, new_status)
        self.assertEqual(result.metadata, metadata_changes)
        self.assertIn("Uploaded by user.", result.notes)

        mock_db_instance[db_doc_req_store.DOCUMENT_REQUIREMENTS_COLLECTION].update_one.assert_called_once()
        update_call_args = mock_db_instance[db_doc_req_store.DOCUMENT_REQUIREMENTS_COLLECTION].update_one.call_args.args[1]
        self.assertIn("$set", update_call_args)
        self.assertEqual(update_call_args["$set"]["status"], new_status)
        self.assertEqual(update_call_args["$set"]["metadata"], metadata_changes)
        self.assertIn("$push", update_call_args)
        self.assertEqual(update_call_args["$push"]["notes"]["$each"][0], "Uploaded by user.")

    @patch('case_management_service.infrastructure.database.document_requirements_store.get_database')
    async def test_update_required_document_status_not_found(self, mock_get_db):
        mock_db_instance = AsyncMock()
        mock_db_instance[db_doc_req_store.DOCUMENT_REQUIREMENTS_COLLECTION].update_one = AsyncMock(return_value=MagicMock(matched_count=0))
        mock_get_db.return_value = mock_db_instance

        result = await db_doc_req_store.update_required_document_status_and_meta("non_existent_id", "UPLOADED")
        self.assertIsNone(result)

    @patch('case_management_service.infrastructure.database.document_requirements_store.get_database')
    async def test_get_required_document_by_id(self, mock_get_db):
        mock_db_instance = AsyncMock()
        doc_req_id = "doc_get_id"
        now = datetime.datetime.now(datetime.UTC)
        doc_from_db = { "id": doc_req_id, "case_id": "c1", "entity_id": "e1", "entity_type": "PERSON", "document_type": "PASSPORT", "status": "AWAITING_UPLOAD", "is_required": True, "created_at": now, "updated_at": now}

        mock_db_instance[db_doc_req_store.DOCUMENT_REQUIREMENTS_COLLECTION].find_one = AsyncMock(return_value=doc_from_db)
        mock_get_db.return_value = mock_db_instance
        result_found = await db_doc_req_store.get_required_document_by_id(doc_req_id)
        self.assertIsNotNone(result_found)
        self.assertEqual(result_found.id, doc_req_id)

        mock_db_instance[db_doc_req_store.DOCUMENT_REQUIREMENTS_COLLECTION].find_one = AsyncMock(return_value=None)
        result_not_found = await db_doc_req_store.get_required_document_by_id("other_id")
        self.assertIsNone(result_not_found)

    @patch('case_management_service.infrastructure.database.document_requirements_store.get_database')
    async def test_list_required_documents(self, mock_get_db):
        mock_db_instance = AsyncMock()
        now = datetime.datetime.now(datetime.UTC)
        docs_from_db = [
            { "id": "doc1", "case_id": "c1", "entity_id": "p1", "entity_type": "PERSON", "document_type": "PASSPORT", "status": "AWAITING_UPLOAD", "is_required": True, "created_at": now, "updated_at": now},
            { "id": "doc2", "case_id": "c1", "entity_id": "p1", "entity_type": "PERSON", "document_type": "VISA", "status": "UPLOADED", "is_required": False, "created_at": now, "updated_at": now}
        ]

        mock_cursor_final = AsyncMock()
        mock_cursor_final.to_list = AsyncMock(return_value=docs_from_db)
        mock_fluent_cursor = MagicMock()
        mock_fluent_cursor.sort.return_value = mock_cursor_final
        mock_db_instance[db_doc_req_store.DOCUMENT_REQUIREMENTS_COLLECTION].find.return_value = mock_fluent_cursor
        mock_get_db.return_value = mock_db_instance

        results = await db_doc_req_store.list_required_documents(case_id="c1", entity_id="p1", status="AWAITING_UPLOAD", is_required=True)

        # The mock setup for find().sort().to_list() needs to be precise.
        # Here, find() is called with the filter, then sort() on its result, then to_list() on sort's result.
        # The current mock setup will return all docs_from_db because the filter isn't applied by the mock find itself.
        # A more accurate mock would make find() return a list based on the filter.
        # For this test, we're primarily testing that find() is called with the correct filter.

        self.assertEqual(len(results), 2) # Mock currently returns all passed docs
        mock_db_instance[db_doc_req_store.DOCUMENT_REQUIREMENTS_COLLECTION].find.assert_called_once_with(
            {"case_id": "c1", "entity_id": "p1", "status": "AWAITING_UPLOAD", "is_required": True}
        )
        mock_fluent_cursor.sort.assert_called_once_with("created_at", 1)
        mock_cursor_final.to_list.assert_called_once_with(length=None)
