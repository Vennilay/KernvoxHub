import os
import logging

from services.redis_client import redis_client

logger = logging.getLogger(__name__)

VALID_API_KEY = None


def get_valid_api_key() -> str:
    global VALID_API_KEY
    if VALID_API_KEY is None:
        api_secret = os.environ.get('API_SECRET', 'dev_secret')
        VALID_API_KEY = f"kvx_{api_secret[:32]}"
    return VALID_API_KEY


def generate_api_token() -> str:
    return get_valid_api_key()


def validate_api_token(token: str) -> bool:
    if not token:
        return False

    try:
        if redis_client:
            cached = redis_client.get(f"token:{token}")
            if cached:
                return True

        valid_key = get_valid_api_key()
        if token == valid_key:
            if redis_client:
                cache_token(token)
            return True
    except Exception as e:
        logger.error(f"Token validation error: {e}")

    return False


def cache_token(token: str, ttl: int = 300):
    if not redis_client:
        return
    try:
        redis_client.setex(f"token:{token}", ttl, "1")
    except Exception as e:
        logger.error(f"Token caching error: {e}")
