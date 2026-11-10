class RecoverXError(Exception):
    """Base error."""


class ImageValidationError(RecoverXError):
    pass


class UnsafePathError(RecoverXError):
    """Output path would collide with, or sit inside, evidence."""


class ToolUnavailableError(RecoverXError):
    pass


class EngineError(RecoverXError):
    pass


class ModelError(RecoverXError):
    pass
