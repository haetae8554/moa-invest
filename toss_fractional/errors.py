class TradingError(Exception):
    """An error that can safely be displayed to an application user."""


class ApiError(TradingError):
    def __init__(self, status: int, code: str = "api-error"):
        self.status = status
        self.code = code
        super().__init__(f"Toss API 오류: HTTP {status} ({code})")


class NetworkError(TradingError):
    pass


class UnknownOrderError(TradingError):
    """The provider may have received the order; never automatically resubmit."""
