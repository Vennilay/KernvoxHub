import logging
from typing import Callable
from fastapi import Request, HTTPException, status
from fastapi.responses import Response
from services.token_manager import validate_api_token

logger = logging.getLogger(__name__)

API_KEY_HEADER = "X-API-Key"
PUBLIC_PATHS = {"/", "/docs", "/openapi.json", "/api/v1/health", "/redoc"}


async def api_key_middleware(request: Request, call_next: Callable) -> Response:
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    api_key = request.headers.get(API_KEY_HEADER)

    if not api_key:
        logger.warning(f"Missing API key for {request.url.path}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key header missing"
        )

    if not validate_api_token(api_key):
        logger.warning(f"Invalid API key for {request.url.path}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )

    response = await call_next(request)
    return response
