# Unit tests for document determination strategies
import pytest
from typing import List, Dict, Any

from case_management_service.app.service.commands.models import DetermineInitialDocumentRequirementsCommand, PersonData # Assuming PersonData is part of the command model
from case_management_service.app.service.strategies.document_strategies import (
    KycPersonStrategy,
    KybCompanyStrategy,
    KybPersonStrategy, # Added this strategy based on previous subtask
    DefaultStrategy,
    get_document_strategy,
)

# Helper to create a mock command
def create_mock_doc_command(
    entity_type: str,
    traitement_type: str,
    case_type: str = "STANDARD_DUE_DILIGENCE",
    context_data: Dict[str, Any] = None
) -> DetermineInitialDocumentRequirementsCommand:
    return DetermineInitialDocumentRequirementsCommand(
        case_id="case123",
        entity_id="entity456",
        entity_type=entity_type,
        traitement_type=traitement_type,
        case_type=case_type,
        context_data=context_data or {}
    )

@pytest.mark.asyncio
async def test_kyc_person_strategy():
    strategy = KycPersonStrategy()
    command = create_mock_doc_command(entity_type="PERSON", traitement_type="KYC")

    requirements = await strategy.determine_requirements(command)

    assert len(requirements) == 2
    assert {"type": "PASSPORT", "is_required": True} in requirements
    assert {"type": "PROOF_OF_ADDRESS", "is_required": True} in requirements

@pytest.mark.asyncio
async def test_kyc_person_strategy_wrong_type():
    strategy = KycPersonStrategy()
    command = create_mock_doc_command(entity_type="COMPANY", traitement_type="KYC")
    requirements = await strategy.determine_requirements(command)
    assert len(requirements) == 0

    command = create_mock_doc_command(entity_type="PERSON", traitement_type="KYB")
    requirements = await strategy.determine_requirements(command)
    assert len(requirements) == 0

@pytest.mark.asyncio
async def test_kyb_company_strategy_standard():
    strategy = KybCompanyStrategy()
    command = create_mock_doc_command(entity_type="COMPANY", traitement_type="KYB", case_type="STANDARD_DUE_DILIGENCE")

    requirements = await strategy.determine_requirements(command)

    assert len(requirements) == 2
    assert {"type": "COMPANY_REGISTRATION_CERTIFICATE", "is_required": True} in requirements
    assert {"type": "ARTICLES_OF_ASSOCIATION", "is_required": True} in requirements

@pytest.mark.asyncio
async def test_kyb_company_strategy_enhanced():
    strategy = KybCompanyStrategy()
    command = create_mock_doc_command(entity_type="COMPANY", traitement_type="KYB", case_type="ENHANCED_DUE_DILIGENCE")

    requirements = await strategy.determine_requirements(command)

    assert len(requirements) == 3
    assert {"type": "COMPANY_REGISTRATION_CERTIFICATE", "is_required": True} in requirements
    assert {"type": "ARTICLES_OF_ASSOCIATION", "is_required": True} in requirements
    assert {"type": "FINANCIAL_STATEMENTS_AUDITED", "is_required": True} in requirements

@pytest.mark.asyncio
async def test_kyb_company_strategy_wrong_type():
    strategy = KybCompanyStrategy()
    command = create_mock_doc_command(entity_type="PERSON", traitement_type="KYB")
    requirements = await strategy.determine_requirements(command)
    assert len(requirements) == 0

    command = create_mock_doc_command(entity_type="COMPANY", traitement_type="KYC")
    requirements = await strategy.determine_requirements(command)
    assert len(requirements) == 0

@pytest.mark.asyncio
async def test_kyb_person_strategy(): # Test for the new KybPersonStrategy
    strategy = KybPersonStrategy()
    command = create_mock_doc_command(entity_type="PERSON", traitement_type="KYB") # Person in KYB context

    requirements = await strategy.determine_requirements(command)

    assert len(requirements) == 1
    assert {"type": "PASSPORT_DIRECTOR_BO", "is_required": True} in requirements

@pytest.mark.asyncio
async def test_kyb_person_strategy_wrong_type():
    strategy = KybPersonStrategy()
    command = create_mock_doc_command(entity_type="COMPANY", traitement_type="KYB")
    requirements = await strategy.determine_requirements(command)
    assert len(requirements) == 0

    command = create_mock_doc_command(entity_type="PERSON", traitement_type="KYC")
    requirements = await strategy.determine_requirements(command)
    assert len(requirements) == 0

@pytest.mark.asyncio
async def test_default_strategy():
    strategy = DefaultStrategy()
    command = create_mock_doc_command(entity_type="OTHER", traitement_type="ANY")

    requirements = await strategy.determine_requirements(command)

    assert len(requirements) == 0

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entity_type, traitement_type, case_type, expected_strategy_type",
    [
        ("PERSON", "KYC", "STANDARD_DUE_DILIGENCE", KycPersonStrategy),
        ("COMPANY", "KYB", "STANDARD_DUE_DILIGENCE", KybCompanyStrategy),
        ("COMPANY", "KYB", "ENHANCED_DUE_DILIGENCE", KybCompanyStrategy),
        ("PERSON", "KYB", "STANDARD_DUE_DILIGENCE", KybPersonStrategy), # Person in KYB context
        ("UNKNOWN_ENTITY", "KYC", "STANDARD_DUE_DILIGENCE", DefaultStrategy),
        ("PERSON", "UNKNOWN_TRAITEMENT", "STANDARD_DUE_DILIGENCE", DefaultStrategy),
    ],
)
async def test_get_document_strategy_factory(
    entity_type, traitement_type, case_type, expected_strategy_type
):
    command = create_mock_doc_command(
        entity_type=entity_type, traitement_type=traitement_type, case_type=case_type
    )
    strategy = get_document_strategy(command)
    assert isinstance(strategy, expected_strategy_type)
