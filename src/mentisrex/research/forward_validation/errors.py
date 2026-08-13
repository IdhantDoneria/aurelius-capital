"""M24 forward validation errors."""


class ForwardValidationError(Exception):
    """Base for M24 validation errors."""


class InsufficientDataError(ForwardValidationError):
    """Not enough forward observations for meaningful analysis."""


class LineageError(ForwardValidationError):
    """Lineage mismatch — strategy_id, version, or fingerprint disagrees."""


class ImplementationDivergenceError(ForwardValidationError):
    """Deterministic reproduction failed — same inputs produced different output."""


class PITViolationError(ForwardValidationError):
    """Point-in-time boundary violated — forward data used before its knowledge date."""


class InvalidArtifactError(ForwardValidationError):
    """Artifact is structurally invalid or has a fingerprint mismatch."""
