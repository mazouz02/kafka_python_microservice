"""
Custom exceptions for the Case Management service.
"""

class BaseCaseManagementError(Exception):
    """Base class for exceptions in this module."""
    pass

class DocumentNotFoundError(BaseCaseManagementError):
    """Raised when a document requirement is not found."""
    def __init__(self, document_id: str):
        self.document_id = document_id
        super().__init__(f"Document requirement with ID '{document_id}' not found.")

class InvalidCaseStateError(BaseCaseManagementError):
    """Raised when an operation is attempted on a case in an invalid state."""
    def __init__(self, case_id: str, current_state: str, attempted_action: str):
        self.case_id = case_id
        self.current_state = current_state
        self.attempted_action = attempted_action
        super().__init__(f"Cannot {attempted_action} for case '{case_id}' in state '{current_state}'.")

class ConcurrencyConflictError(BaseCaseManagementError):
    """Raised when a version conflict is detected during an update operation."""
    def __init__(self, aggregate_id: str, expected_version: int, actual_version: int):
        self.aggregate_id = aggregate_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            f"Concurrency conflict for aggregate '{aggregate_id}'. "
            f"Expected version {expected_version}, but found {actual_version}."
        )

class ConfigurationError(BaseCaseManagementError):
    """Raised when a configuration issue is detected."""
    pass

class KafkaProducerError(BaseCaseManagementError):
    """Raised when there's an issue with Kafka message production."""
    pass
