import logging
import time
from typing import Callable

from fastapi import Request, status
from fastapi.responses import JSONResponse, Response
from services.token_manager import validate_api_token
from services.redis_client import redis_client

logger = logging.getLogger(__name__)

API_KEY_HEADER = "X-API-Key"
PUBLIC_PATHS = {"/", "/docs", "/openapi.json", "/api/v1/health", "/redoc"}

# Rate limiting: после N неудачных попыток за WINDOW секунд — бан на BAN_SECONDS
RATE_LIMIT_WINDOW = 60       # окно подсчёта (секунды)
RATE_LIMIT_MAX_ATTEMPTS = 10  # максимум неудачных попыток
RATE_LIMIT_BAN_SECONDS = 300  # длительность бана


def _get_client_ip(request: Request) -> str:
    """Получает реальный IP (учитывая X-Forwarded-For от Nginx)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _check_rate_limit(client_ip: str) -> None:
    """Проверяет, не забанен ли IP и не превышен ли лимит попыток."""
    if not redis_client:
        return

    ban_key = f"auth_ban:{client_ip}"
    if redis_client.get(ban_key):
        return "banned"

    attempts_key = f"auth_attempts:{client_ip}"
    attempts = int(redis_client.get(attempts_key) or 0)
    if attempts >= RATE_LIMIT_MAX_ATTEMPTS:
        redis_client.setex(ban_key, RATE_LIMIT_BAN_SECONDS, "1")
        redis_client.delete(attempts_key)
        return "banned"

    return None


async def _record_failed_attempt(client_ip: str) -> None:
    """Увеличивает счётчик неудачных попыток."""
    if not redis_client:
        return
    attempts_key = f"auth_attempts:{client_ip}"
    pipe = redis_client.pipeline()
    pipe.incr(attempts_key)
    pipe.expire(attempts_key, RATE_LIMIT_WINDOW)
    pipe.execute()


def _unauthorized(detail: str) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": detail})


def _too_many_requests() -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many failed attempts. Try again later."},
    )


async def api_key_middleware(request: Request, call_next: Callable) -> Response:
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    client_ip = _get_client_ip(request)
    rate_result = await _check_rate_limit(client_ip)
    if rate_result == "banned":
        return _too_many_requests()

    api_key = request.headers.get(API_KEY_HEADER)

    if not api_key:
        logger.warning(f"Missing API key for {request.url.path} from {client_ip}")
        await _record_failed_attempt(client_ip)
        return _unauthorized("API key header missing")

    if not validate_api_token(api_key):
        logger.warning(f"Invalid API key for {request.url.path} from {client_ip}")
        await _record_failed_attempt(client_ip)
        return _unauthorized("Invalid API key")

    response = await call_next(request)
    return response
