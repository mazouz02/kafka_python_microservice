# Unit Tests for Kafka Pydantic Schemas (Refactored Structure)
import pytest
from pydantic import ValidationError

# Module to test
from case_management_service.infrastructure.kafka import schemas as kafka_schemas


def test_address_data_valid():
    data = {"street": "123 Main St", "city": "Anytown", "country": "US", "postal_code": "12345"}
    addr = kafka_schemas.AddressData(**data)
    assert addr.street == "123 Main St"

def test_person_data_valid_with_role():
    data = {"firstname": "John", "lastname": "Doe", "birthdate": "1990-01-01", "role_in_company": "Director"}
    person = kafka_schemas.PersonData(**data)
    assert person.firstname == "John"
    assert person.role_in_company == "Director"

def test_company_profile_data_valid():
    addr_data = {"street": "1 Corp Ave", "city": "Business City", "country": "GB", "postal_code": "BC1 1CB"}
    company_data = {
        "registered_name": "Big Corp Ltd",
        "registration_number": "C123456",
        "country_of_incorporation": "GB",
        "registered_address": addr_data,
        "business_type": "PLC"
    }
    profile = kafka_schemas.CompanyProfileData(**company_data)
    assert profile.registered_name == "Big Corp Ltd"
    assert profile.registered_address.city == "Business City"

def test_beneficial_owner_data_valid():
    person_data_bo = {"firstname": "Beneficial", "lastname": "Owner", "birthdate": "1980-01-01"}
    bo_data = {
        "person_details": person_data_bo,
        "ownership_percentage": 75.5,
        "types_of_control": ["Voting Rights", "Direct Ownership"],
        "is_ubo": True
    }
    bo = kafka_schemas.BeneficialOwnerData(**bo_data)
    assert bo.person_details.firstname == "Beneficial"
    assert bo.ownership_percentage == 75.5
    assert bo.is_ubo is True

# --- KafkaMessage Validation Tests ---
def test_kafka_message_kyc_valid():
    msg_data = {
        "client_id": "client1", "version": "1.0", "type": "INDIVIDUAL_ONBOARDING",
        "traitement_type": "KYC",
        "persons": [{"firstname": "Simple", "lastname": "Person", "birthdate": "2000-03-03"}]
    }
    msg = kafka_schemas.KafkaMessage(**msg_data)
    assert msg.client_id == "client1"
    assert msg.traitement_type == "KYC"
    assert msg.company_profile is None
    assert msg.beneficial_owners == []

def test_kafka_message_kyb_valid_with_company_and_bos():
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
    assert msg.traitement_type == "KYB"
    assert msg.company_profile is not None
    assert msg.company_profile.registered_name == "Acme Corp"
    assert len(msg.beneficial_owners) == 1
    assert msg.beneficial_owners[0].is_ubo is True

def test_kafka_message_invalid_traitement_type():
    msg_data = {"client_id": "c1", "version": "1.0", "type": "T1", "traitement_type": "INVALID_TYPE", "persons": []}
    with pytest.raises(ValidationError) as exc_info:
        kafka_schemas.KafkaMessage(**msg_data)
    errors = exc_info.value.errors()
    assert any(
        e['loc'] == ('traitement_type',) and
        'Value error, traitement_type must be either KYC or KYB' in e['msg']
        for e in errors
    ), f"Errors: {errors}"

def test_kafka_message_kyb_missing_company_profile():
    msg_data = {
        "client_id": "c2", "version": "1.0", "type": "T2",
        "traitement_type": "KYB",
        "persons": [],
        "company_profile": None
    }
    with pytest.raises(ValidationError) as exc_info:
        kafka_schemas.KafkaMessage(**msg_data)
    errors = exc_info.value.errors()
    assert any(
        e['loc'] == () and # Root model validation
        'company_profile is required when traitement_type is KYB' in e['msg']
        for e in errors
    ), f"Errors: {errors}"

def test_kafka_message_kyc_with_company_profile_allowed():
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
    except ValidationError as e:
        pytest.fail(f"KafkaMessage raised ValidationError unexpectedly for KYC with company_profile: {e}")

def test_kafka_message_kyc_with_beneficial_owners_fails():
    bo_person_data = {"firstname": "BO", "lastname": "Unwanted"}
    bo_data = {"person_details": bo_person_data, "is_ubo": True}
    msg_data = {
        "client_id": "c4", "version": "1.0", "type": "T4",
        "traitement_type": "KYC",
        "persons": [],
        "beneficial_owners": [bo_data]
    }
    with pytest.raises(ValidationError) as exc_info:
        kafka_schemas.KafkaMessage(**msg_data)
    errors = exc_info.value.errors()
    assert any(
        e['loc'] == () and # Root model validation
        'beneficial_owners should be empty or not provided when traitement_type is KYC' in e['msg']
        for e in errors
    ), f"Errors: {errors}"

def test_kafka_message_kyc_with_empty_beneficial_owners_allowed():
    msg_data = {
        "client_id": "c5", "version": "1.0", "type": "T5",
        "traitement_type": "KYC",
        "persons": [],
        "beneficial_owners": []
    }
    try:
        kafka_schemas.KafkaMessage(**msg_data)
    except ValidationError as e:
        pytest.fail(f"KafkaMessage raised ValidationError unexpectedly for KYC with empty beneficial_owners: {e}")

def test_beneficial_owner_invalid_percentage():
    person_data_bo = {"firstname": "Beneficial", "lastname": "Owner", "birthdate": "1980-01-01"}
    with pytest.raises(ValidationError):
        kafka_schemas.BeneficialOwnerData(
            person_details=person_data_bo, ownership_percentage=101.0
        )
    with pytest.raises(ValidationError):
        kafka_schemas.BeneficialOwnerData(
            person_details=person_data_bo, ownership_percentage=-10.0
        )
