"""Application-level errors suitable for presentation by thin interfaces."""


class PersonalOSError(Exception):
    """Base class for expected Personal OS operational errors."""


class DomainValidationError(PersonalOSError):
    """Raised when application-facing domain input is invalid."""


class EntityNotFoundError(PersonalOSError):
    """Raised when a requested or referenced entity does not exist."""


class PersistenceError(PersonalOSError):
    """Raised when structured state cannot be read or persisted safely."""
