"""Controlled model failures shared by the runtime and provider adapters."""


class ModelFailure(Exception):
    MESSAGES = {
        "unknown": "The model request failed. Please try again.",
        "configuration": "The model provider is not configured. Check the server settings.",
        "authentication": "The model provider rejected access. Check the server credentials and permissions.",
        "credits": "The model provider has insufficient credits. Check the server account.",
        "routing": "The selected model/provider configuration is unavailable. Check the server settings.",
        "rate_limit": "The model provider is busy. Please try again later.",
        "timeout": "The model provider timed out. Please try again.",
        "unavailable": "The model provider is unavailable. Please try again later.",
        "rejected": "The model provider rejected the request. Check the server settings.",
        "transport": "The model provider could not be reached. Please try again.",
        "invalid_response": "The model returned an invalid or incomplete response. Please try again.",
    }

    def __init__(self, category: str, **diagnostics):
        self.category = category if category in self.MESSAGES else "unknown"
        self.diagnostics = diagnostics
        super().__init__(self.MESSAGES[self.category])

    @classmethod
    def from_status(cls, status: int):
        category = {
            401: "authentication", 403: "authentication", 402: "credits",
            404: "routing", 408: "timeout", 429: "rate_limit", 504: "timeout",
        }.get(status, "unavailable" if status >= 500 else "rejected")
        return cls(category, http_status=status)
