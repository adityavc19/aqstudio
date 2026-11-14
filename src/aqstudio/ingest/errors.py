"""Ingest errors mapped to API error codes."""


class IngestError(ValueError):
    """Raised when an upload cannot be parsed or mapped."""

    def __init__(self, message: str, code: str = "invalid_table") -> None:
        """Keep an API error code alongside the human message."""
        super().__init__(message)
        self.code = code
