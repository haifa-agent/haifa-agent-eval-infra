"""Typed exception hierarchy for evalctl (Fail-Closed principle)."""

from __future__ import annotations


class EvalctlError(Exception):
    """Base class for all evalctl exceptions."""


class RequestValidationError(EvalctlError):
    """Raised when Run Request schema or constraints fail."""


class HostTrustError(EvalctlError):
    """Raised when SSH Host Key verification fails or is untrusted."""


class HostDoctorError(EvalctlError):
    """Raised when remote host preflight fails."""


class BootstrapError(EvalctlError):
    """Raised when remote host bootstrap fails or tools are missing."""


class SourcePrepareError(EvalctlError):
    """Raised when git checkout, pin, or clean check fails."""


class AdmissionError(EvalctlError):
    """Raised when agent profile, provider, model, or secret check fails."""


class PlanApprovalError(EvalctlError):
    """Raised when plan generation or budget approval check fails."""


class ExecutionError(EvalctlError):
    """Raised when harness execution or supervisor fails."""


class EvidenceError(EvalctlError):
    """Raised when evidence manifest verification or secret scan fails."""


class CleanupError(EvalctlError):
    """Raised when cleanup operation is blocked or dangerous."""
