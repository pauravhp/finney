class ProviderError(RuntimeError):
    """Safe provider failure without response bodies, tokens, or personal data."""

    def __init__(self, provider: str, status: int | None = None, *, retryable: bool = False):
        self.provider = provider
        self.status = status
        self.retryable = retryable
        super().__init__(f"{provider} request failed (status={status}, retryable={retryable})")


class ConnectionRequired(RuntimeError):
    pass
