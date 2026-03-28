import logging
import redis
from config import settings

logger = logging.getLogger(__name__)

try:
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
except redis.exceptions.RedisError as e:
    logger.error(f"Failed to connect to Redis: {e}")
    redis_client = None
