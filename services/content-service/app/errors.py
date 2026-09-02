class GenerationPipelineError(RuntimeError):
    """Base error for a generation run that must not produce a successful result."""


class LLMGenerationError(GenerationPipelineError):
    """The LLM request or its structured response could not be recovered."""


class AnalysisValidationError(GenerationPipelineError):
    """The source analysis is incomplete or contains unsupported facts."""


class PlanValidationError(GenerationPipelineError):
    """The generated slide plan violates template or grounding constraints."""


class ContentValidationError(GenerationPipelineError):
    """Generated slide content remains invalid after all retries."""


class UserMappingValidationError(GenerationPipelineError):
    """User-provided slide or placeholder mapping violates the file contract."""
