from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from backend.config import get_settings

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncIOMotorClient(settings.mongo_uri)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    settings = get_settings()
    return get_client()[settings.mongo_db_name]


# Convenience collection accessors
def users_col(db: AsyncIOMotorDatabase):
    return db["users"]


def zones_col(db: AsyncIOMotorDatabase):
    return db["zones"]


def rate_cards_col(db: AsyncIOMotorDatabase):
    return db["rate_cards"]


def cod_surcharge_col(db: AsyncIOMotorDatabase):
    return db["cod_surcharge_config"]


def orders_col(db: AsyncIOMotorDatabase):
    return db["orders"]


def tracking_col(db: AsyncIOMotorDatabase):
    return db["tracking_history"]


async def close_client():
    global _client
    if _client is not None:
        _client.close()
        _client = None
