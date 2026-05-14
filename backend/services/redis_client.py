import logging
import redis
from urllib.parse import urlparse, urlunparse
from config import settings

logger = logging.getLogger(__name__)


def _redis_url_without_password(redis_url: str) -> str:
    parsed = urlparse(redis_url)
    if not parsed.hostname:
        return redis_url

    netloc = parsed.hostname
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"

    return urlunparse(parsed._replace(netloc=netloc))


try:
    if settings.REDIS_PASSWORD:
        redis_client = redis.from_url(
            _redis_url_without_password(settings.REDIS_URL),
            password=settings.REDIS_PASSWORD,
            decode_responses=True,
        )
    else:
        redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
except (ValueError, redis.exceptions.RedisError) as e:
    logger.error(f"Failed to connect to Redis: {e}")
    redis_client = None
