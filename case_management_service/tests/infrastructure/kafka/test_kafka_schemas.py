# Unit Tests for Kafka Pydantic Schemas (Refactored Structure)
import unittest
import pytest # Using pytest for parametrize and raises
from pydantic import ValidationError

# Module to test
from case_management_service.infrastructure.kafka import schemas as kafka_schemas

class TestKafkaSchemas(unittest.TestCase):

    def test_address_data_valid(self):
        data = {"street": "123 Main St", "city": "Anytown", "country": "US", "postal_code": "12345"}
        addr = kafka_schemas.AddressData(**data)
        self.assertEqual(addr.street, "123 Main St")

    def test_person_data_valid_with_role(self):
        data = {"firstname": "John", "lastname": "Doe", "birthdate": "1990-01-01", "role_in_company": "Director"}
        person = kafka_schemas.PersonData(**data)
        self.assertEqual(person.firstname, "John")
        self.assertEqual(person.role_in_company, "Director")

    def test_company_profile_data_valid(self):
        addr_data = {"street": "1 Corp Ave", "city": "Business City", "country": "GB", "postal_code": "BC1 1CB"}
        company_data = {
            "registered_name": "Big Corp Ltd",
            "registration_number": "C123456",
            "country_of_incorporation": "GB",
            "registered_address": addr_data,
            "business_type": "PLC"
        }
        profile = kafka_schemas.CompanyProfileData(**company_data)
        self.assertEqual(profile.registered_name, "Big Corp Ltd")
        self.assertEqual(profile.registered_address.city, "Business City")

    def test_beneficial_owner_data_valid(self):
        person_data_bo = {"firstname": "Beneficial", "lastname": "Owner", "birthdate": "1980-01-01"}
        bo_data = {
            "person_details": person_data_bo,
            "ownership_percentage": 75.5,
            "types_of_control": ["Voting Rights", "Direct Ownership"],
            "is_ubo": True
        }
        bo = kafka_schemas.BeneficialOwnerData(**bo_data)
        self.assertEqual(bo.person_details.firstname, "Beneficial")
        self.assertEqual(bo.ownership_percentage, 75.5)
        self.assertTrue(bo.is_ubo)

    # --- KafkaMessage Validation Tests ---
    def test_kafka_message_kyc_valid(self):
        msg_data = {
            "client_id": "client1", "version": "1.0", "type": "INDIVIDUAL_ONBOARDING",
            "traitement_type": "KYC",
            "persons": [{"firstname": "Simple", "lastname": "Person", "birthdate": "2000-03-03"}]
            # company_profile and beneficial_owners are optional and should be None/empty for KYC
        }
        msg = kafka_schemas.KafkaMessage(**msg_data)
        self.assertEqual(msg.client_id, "client1")
        self.assertEqual(msg.traitement_type, "KYC")
        self.assertIsNone(msg.company_profile) # Default is None if not provided
        self.assertEqual(msg.beneficial_owners, []) # Default is empty list

    def test_kafka_message_kyb_valid_with_company_and_bos(self):
        addr_data = {"street": "1 Business Rd", "city": "Corpville", "country": "US", "postal_code": "CV1 2BC"}
        company_data = {
            "registered_name": "Acme Corp", "registration_number": "ACME001",
            "country_of_incorporation": "US", "registered_address": addr_data
        }
        person_data_kyb = {"firstname": "Director", "lastname": "Smith", "role_in_company": "Director"}
        bo_person_data = {"firstname": "BO", "lastname": "Ultimate"}
        bo_data = {"person_details": bo_person_data, "is_ubo": True}

        msg_data = {
            "client_id": "client2", "version": "1.0", "type": "COMPANY_ONBOARDING",
            "traitement_type": "KYB",
            "persons": [person_data_kyb],
            "company_profile": company_data,
            "beneficial_owners": [bo_data]
        }
        msg = kafka_schemas.KafkaMessage(**msg_data)
        self.assertEqual(msg.traitement_type, "KYB")
        self.assertIsNotNone(msg.company_profile)
        self.assertEqual(msg.company_profile.registered_name, "Acme Corp")
        self.assertEqual(len(msg.beneficial_owners), 1)
        self.assertTrue(msg.beneficial_owners[0].is_ubo)

    def test_kafka_message_invalid_traitement_type(self):
        msg_data = {"client_id": "c1", "version": "1.0", "type": "T1", "traitement_type": "INVALID_TYPE", "persons": []}
        with self.assertRaises(ValidationError) as exc_info: # Using unittest.assertRaises
            kafka_schemas.KafkaMessage(**msg_data)
        errors = exc_info.exception.errors()
        self.assertTrue(any(
            e['loc'] == ('traitement_type',) and
            e['msg'] == 'Value error, traitement_type must be either KYC or KYB'
            for e in errors
        ), f"Errors: {errors}")


    def test_kafka_message_kyb_missing_company_profile(self):
        msg_data = {
            "client_id": "c2", "version": "1.0", "type": "T2",
            "traitement_type": "KYB",
            "persons": [],
            "company_profile": None
        }
        with self.assertRaises(ValidationError) as exc_info:
            kafka_schemas.KafkaMessage(**msg_data)
        errors = exc_info.exception.errors()
        self.assertTrue(any(
            e['loc'] == () and
            'company_profile is required when traitement_type is KYB' in e['msg']
            for e in errors
        ), f"Errors: {errors}")

    def test_kafka_message_kyc_with_company_profile_allowed(self):
        addr_data = {"street": "1 Business Rd", "city": "Corpville", "country": "US", "postal_code": "CV1 2BC"}
        company_data = {
            "registered_name": "Acme Corp", "registration_number": "ACME001",
            "country_of_incorporation": "US", "registered_address": addr_data
        }
        msg_data = {
            "client_id": "c3", "version": "1.0", "type": "T3",
            "traitement_type": "KYC",
            "persons": [],
            "company_profile": company_data
        }
        try:
            kafka_schemas.KafkaMessage(**msg_data)
        except ValidationError:
            self.fail("KafkaMessage raised ValidationError unexpectedly for KYC with company_profile")


    def test_kafka_message_kyc_with_beneficial_owners_fails(self):
        bo_person_data = {"firstname": "BO", "lastname": "Unwanted"}
        bo_data = {"person_details": bo_person_data, "is_ubo": True}
        msg_data = {
            "client_id": "c4", "version": "1.0", "type": "T4",
            "traitement_type": "KYC",
            "persons": [],
            "beneficial_owners": [bo_data]
        }
        with self.assertRaises(ValidationError) as exc_info:
            kafka_schemas.KafkaMessage(**msg_data)
        errors = exc_info.exception.errors()
        self.assertTrue(any(
            e['loc'] == () and
            'beneficial_owners should be empty or not provided when traitement_type is KYC' in e['msg']
            for e in errors
        ), f"Errors: {errors}")

    def test_kafka_message_kyc_with_empty_beneficial_owners_allowed(self):
        msg_data = {
            "client_id": "c5", "version": "1.0", "type": "T5",
            "traitement_type": "KYC",
            "persons": [],
            "beneficial_owners": []
        }
        try:
            kafka_schemas.KafkaMessage(**msg_data)
        except ValidationError:
            self.fail("KafkaMessage raised ValidationError unexpectedly for KYC with empty beneficial_owners")


    def test_beneficial_owner_invalid_percentage(self):
        person_data_bo = {"firstname": "Beneficial", "lastname": "Owner", "birthdate": "1980-01-01"}
        with self.assertRaises(ValidationError):
            kafka_schemas.BeneficialOwnerData(
                person_details=person_data_bo, ownership_percentage=101.0
            )
        with self.assertRaises(ValidationError):
            kafka_schemas.BeneficialOwnerData(
                person_details=person_data_bo, ownership_percentage=-10.0
            )

    # Note: Pytest's 'raises' context manager is more idiomatic for testing exceptions with Pydantic.
    # Since this class uses unittest.TestCase, self.assertRaises is used.
    # The error message checking is adapted for Pydantic's error structure.
