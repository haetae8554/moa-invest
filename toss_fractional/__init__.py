"""UI-independent public API. Importing this package never contacts the broker."""
from .auth import TossAuthClient
from .client import TossClient
from .config import Settings
from .errors import ApiError, TradingError, UnknownOrderError
from .service import Broker, FractionalBuyService
from .batch import FractionalTradeService
from .store import OrderStore


def create_service(settings: Settings) -> FractionalTradeService:
    client = None
    if settings.configured:
        auth = TossAuthClient(settings.client_id, settings.client_secret,
                              cache_path=settings.token_cache)
        client = TossClient(auth)
    return FractionalTradeService(client, settings)


__all__ = ["Settings", "FractionalTradeService", "FractionalBuyService", "Broker", "OrderStore", "TossClient", "TossAuthClient",
           "create_service", "TradingError", "ApiError", "UnknownOrderError"]
