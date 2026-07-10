class ContextProviderError(RuntimeError):
    def __init__(self, code: str, safe_detail: str = "") -> None:
        self.code = code
        self.safe_detail = safe_detail
        super().__init__(f"{code}: {safe_detail}" if safe_detail else code)


RESOURCE_NOT_REGISTERED = "RESOURCE_NOT_REGISTERED"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
STALE_SOURCE = "STALE_SOURCE"
