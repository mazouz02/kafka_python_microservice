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
# Updated schema import to include all necessary schemas
from case_management_service.infrastructure.database import schemas as db_schemas
from case_management_service.core.events import models as domain_event_models
from case_management_service.app import config
# Import AddressData for constructing test objects that use it
from case_management_service.infrastructure.kafka.schemas import AddressData


# Helper to reset global db client in database.connection module
def reset_db_connection_module_state():
    db_connection.client = None
    db_connection.db = None

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
        # Ensure CaseCreatedEventPayload now includes traitement_type as it's required
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
        now = datetime.datetime.utcnow()
        company_db = db_schemas.CompanyProfileDB(
            id="comp_123",
            registered_name="Corp Inc",
            registration_number="C123",
            country_of_incorporation="CY",
            registered_address=addr,
            created_at=now, # Pydantic v2: default_factory used if not provided
            updated_at=now  # Pydantic v2: default_factory used if not provided
        )
        self.assertEqual(company_db.id, "comp_123")
        self.assertEqual(company_db.registered_address.city, "Corpville")

    def test_beneficial_owner_db_schema_instantiation(self):
        now = datetime.datetime.utcnow()
        bo_db = db_schemas.BeneficialOwnerDB(
            id="bo_123",
            company_id="comp_123",
            firstname="Beneficial",
            lastname="Owner",
            is_ubo=True,
            created_at=now, # Pydantic v2: default_factory used if not provided
            updated_at=now  # Pydantic v2: default_factory used if not provided
        )
        self.assertEqual(bo_db.id, "bo_123")
        self.assertEqual(bo_db.firstname, "Beneficial")

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

    # Updated test_get_events_for_aggregate_deserialization
    @patch('case_management_service.infrastructure.database.event_store.get_database')
    async def test_get_events_for_aggregate_with_new_event_types(self, mock_get_db_for_event_store):
        mock_db_instance = AsyncMock()
        agg_id_case = str(uuid.uuid4())
        agg_id_company = str(uuid.uuid4())
        person_id_bo_detail = str(uuid.uuid4()) # ID for person details within BO event
        person_id_linked = str(uuid.uuid4())
        bo_id_unique = str(uuid.uuid4()) # ID for the BO link/record itself

        addr_data = AddressData(street="s", city="c", country="US", postal_code="123")
        addr_data_dict = addr_data.model_dump()

        # PersonData for BO, then dumped to dict for StoredEventDB payload
        bo_person_details = domain_event_models.PersonData(firstname="BO", lastname="User", birthdate="1977-07-07")
        bo_person_details_dict = bo_person_details.model_dump()

        meta_dict = db_schemas.StoredEventMetaData().model_dump()

        event_docs_from_db = [
            db_schemas.StoredEventDB(event_id=str(uuid.uuid4()), event_type="CaseCreated", aggregate_id=agg_id_case, timestamp=datetime.datetime.utcnow(), version=1, payload={"client_id": "c1", "case_type": "KYB", "case_version": "v1", "traitement_type": "KYB", "company_id": agg_id_company}, metadata=meta_dict).model_dump(),
            db_schemas.StoredEventDB(event_id=str(uuid.uuid4()), event_type="CompanyProfileCreated", aggregate_id=agg_id_company, timestamp=datetime.datetime.utcnow(), version=1, payload={"registered_name": "Comp Ltd", "registration_number": "R1", "country_of_incorporation": "US", "registered_address": addr_data_dict}, metadata=meta_dict).model_dump(),
            db_schemas.StoredEventDB(event_id=str(uuid.uuid4()), event_type="BeneficialOwnerAdded", aggregate_id=agg_id_company, timestamp=datetime.datetime.utcnow(), version=2, payload={"beneficial_owner_id": bo_id_unique, "person_details": bo_person_details_dict, "is_ubo": True, "ownership_percentage": 50.0, "types_of_control": ["Voting Rights"]}, metadata=meta_dict).model_dump(),
            db_schemas.StoredEventDB(event_id=str(uuid.uuid4()), event_type="PersonLinkedToCompany", aggregate_id=agg_id_company, timestamp=datetime.datetime.utcnow(), version=3, payload={"person_id": person_id_linked, "firstname": "Dir", "lastname": "Ector", "role_in_company": "Director", "birthdate": "1980-08-08"}, metadata=meta_dict).model_dump()
        ]

        mock_cursor = MagicMock()
        mock_cursor.__aiter__.return_value = iter(event_docs_from_db)

        mock_db_instance[db_event_store.EVENT_STORE_COLLECTION].find.return_value.sort.return_value = mock_cursor
        mock_get_db_for_event_store.return_value = mock_db_instance

        retrieved_events_company = await db_event_store.get_events_for_aggregate(agg_id_company)
        retrieved_events_case = await db_event_store.get_events_for_aggregate(agg_id_case) # This will re-mock find().sort() if not careful

        # Re-mock for the second call if the mock is consumed or specific to one aggregate_id
        mock_db_instance[db_event_store.EVENT_STORE_COLLECTION].find.return_value.sort.return_value = async_iterable([event_docs_from_db[0]]) # Only CaseCreatedEvent for agg_id_case
        retrieved_events_case = await db_event_store.get_events_for_aggregate(agg_id_case)

        mock_db_instance[db_event_store.EVENT_STORE_COLLECTION].find.return_value.sort.return_value = async_iterable(event_docs_from_db[1:]) # Company events for agg_id_company
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

    # Keep existing tests for read_models (get_case_by_id, list_cases, etc.) and raw_event_store
    # They should still pass. For brevity, not repeating them here, but they are part of the file.
    # (Original test_get_case_by_id_from_read_model and others are assumed to be below)
    @patch('case_management_service.infrastructure.database.read_models.get_database')
    async def test_get_case_by_id_from_read_model(self, mock_get_db_for_read_models): # Copied from original
        mock_db_instance = AsyncMock()
        now = datetime.datetime.utcnow()
        # CaseManagementDB now requires traitement_type. Add it.
        case_doc_from_db = {"id": "foundcase", "client_id": "c1", "version": "v1", "type": "t1",
                            "traitement_type": "KYC", "status": "OPEN", # Added required fields
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
    async def test_add_raw_event_to_store(self, mock_get_db_for_raw_store): # Copied from original
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

# Helper for async iterable mock
async def async_iterable(items):
    for item in items:
        yield item
