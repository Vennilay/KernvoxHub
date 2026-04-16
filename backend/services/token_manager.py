import logging
import hashlib
import hmac
import secrets

from services.redis_client import redis_client

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "kvx_"
TOKEN_HASH_SET_KEY = "api_tokens"
TOKEN_CACHE_PREFIX = "token_cache:"
BOOTSTRAP_API_KEY = None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_bootstrap_api_key() -> str:
    global BOOTSTRAP_API_KEY
    if BOOTSTRAP_API_KEY is None:
        from config import settings
        if not settings.API_TOKEN:
            raise RuntimeError(
                "API_TOKEN is not set. Run setup.sh to generate a bootstrap API token."
            )
        BOOTSTRAP_API_KEY = settings.API_TOKEN
    return BOOTSTRAP_API_KEY


def generate_api_token() -> str:
    token = f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    store_api_token(token)
    return token


def store_api_token(token: str) -> None:
    if not redis_client:
        raise RuntimeError("Redis is required to store generated API tokens.")

    token_hash = _hash_token(token)
    redis_client.sadd(TOKEN_HASH_SET_KEY, token_hash)
    cache_token(token)


def validate_api_token(token: str) -> bool:
    if not token:
        return False

    try:
        try:
            bootstrap_key = get_bootstrap_api_key()
        except RuntimeError:
            bootstrap_key = ""

        if bootstrap_key and hmac.compare_digest(token, bootstrap_key):
            cache_token(token)
            return True

        if redis_client:
            token_hash = _hash_token(token)
            cached = redis_client.get(f"{TOKEN_CACHE_PREFIX}{token_hash}")
            if cached:
                return True

            if redis_client.sismember(TOKEN_HASH_SET_KEY, token_hash):
                cache_token(token)
                return True
    except Exception as e:
        logger.error(f"Token validation error: {e}")

    return False


def cache_token(token: str, ttl: int = 300):
    if not redis_client:
        return
    try:
        redis_client.setex(f"{TOKEN_CACHE_PREFIX}{_hash_token(token)}", ttl, "1")
    except Exception as e:
        logger.error(f"Token caching error: {e}")
