from abc import ABC, abstractmethod
from typing import List, Dict, Any

# Assuming DetermineInitialDocumentRequirementsCommand is in app.service.commands.models
# We need to ensure this path is correct and accessible.
# If it causes circular dependencies, we might need to pass plain data to strategies
# instead of the full command object, or define a simpler Command-like dataclass here.
from case_management_service.app.service.commands.models import DetermineInitialDocumentRequirementsCommand

class DocumentDeterminationStrategy(ABC):
    @abstractmethod
    async def determine_requirements(
        self, command: DetermineInitialDocumentRequirementsCommand
    ) -> List[Dict[str, Any]]:
        """
        Determines the list of required documents based on the command.

        Args:
            command: The command containing details about the case and entity.

        Returns:
            A list of document specifications, where each specification is a dictionary.
            Example: [{"type": "PASSPORT", "is_required": True}, ...]
        """
        pass

class KycPersonStrategy(DocumentDeterminationStrategy):
    async def determine_requirements(
        self, command: DetermineInitialDocumentRequirementsCommand
    ) -> List[Dict[str, Any]]:
        requirements: List[Dict[str, Any]] = []
        if command.entity_type == "PERSON" and command.traitement_type == "KYC":
            requirements.append({"type": "PASSPORT", "is_required": True})
            requirements.append({"type": "PROOF_OF_ADDRESS", "is_required": True})
        # Potentially add more complex logic based on command.context_data if needed
        return requirements

class KybCompanyStrategy(DocumentDeterminationStrategy):
    async def determine_requirements(
        self, command: DetermineInitialDocumentRequirementsCommand
    ) -> List[Dict[str, Any]]:
        requirements: List[Dict[str, Any]] = []
        if command.entity_type == "COMPANY" and command.traitement_type == "KYB":
            requirements.append({"type": "COMPANY_REGISTRATION_CERTIFICATE", "is_required": True})
            requirements.append({"type": "ARTICLES_OF_ASSOCIATION", "is_required": True})

            # Example of handling case_type variation within a strategy
            if command.case_type == "ENHANCED_DUE_DILIGENCE":
                requirements.append({"type": "FINANCIAL_STATEMENTS_AUDITED", "is_required": True})

            # If person details are provided in KYB for directors/UBOs,
            # this strategy could also suggest generic requirements for them,
            # or a separate strategy could be invoked by the handler.
            # For now, keeping it focused on company-level docs.
            # We might also need a KybPersonStrategy for individuals in a KYB context.
            # For example, for directors of a company:
            # requirements.append({"type": "PASSPORT_DIRECTOR_BO", "is_required": True})

        return requirements

class KybPersonStrategy(DocumentDeterminationStrategy):
    """
    Strategy for individuals involved in a KYB case (e.g., directors, UBOs).
    This is distinct from a KYC check on a standalone person.
    """
    async def determine_requirements(
        self, command: DetermineInitialDocumentRequirementsCommand
    ) -> List[Dict[str, Any]]:
        requirements: List[Dict[str, Any]] = []
        # This strategy assumes the command's entity_type is "PERSON"
        # but the overall case context (traitement_type) is "KYB".
        # The handler would need to select this strategy appropriately.
        if command.entity_type == "PERSON" and command.traitement_type == "KYB":
            requirements.append({"type": "PASSPORT_DIRECTOR_BO", "is_required": True})
            # Add other requirements specific to persons in a KYB context if necessary
        return requirements


# Example of a default or fallback strategy
class DefaultStrategy(DocumentDeterminationStrategy):
    async def determine_requirements(
        self, command: DetermineInitialDocumentRequirementsCommand
    ) -> List[Dict[str, Any]]:
        # Returns an empty list or could have some very basic default requirement.
        return []

# A simple factory function to select the strategy (can be placed in handlers or here)
# For now, let's keep it here to group strategy-related logic.
def get_document_strategy(command: DetermineInitialDocumentRequirementsCommand) -> DocumentDeterminationStrategy:
    if command.entity_type == "PERSON":
        if command.traitement_type == "KYC":
            return KycPersonStrategy()
        elif command.traitement_type == "KYB": # Person in context of KYB
            return KybPersonStrategy()
    elif command.entity_type == "COMPANY":
        if command.traitement_type == "KYB":
            return KybCompanyStrategy()

    # Fallback or raise error
    # logger.warning(f"No specific document determination strategy found for entity_type='{command.entity_type}', traitement_type='{command.traitement_type}'. Using default.")
    return DefaultStrategy()
