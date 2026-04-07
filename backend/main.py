from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.middleware.auth import api_key_middleware
from api.routes import servers_router, metrics_router, android_router
from models.database import Base, engine
from config import settings

app = FastAPI(
    title="KernvoxHub API",
    description="Backend для сбора метрик с серверов и предоставления данных Android-приложению Kernvox",
    version="1.0.0"
)

# --- Rate limiting ---
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Try again later."},
    )


# --- CORS из env (не wildcard *) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(api_key_middleware)

app.include_router(servers_router)
app.include_router(metrics_router)
app.include_router(android_router)


@app.on_event("startup")
async def startup_event():
    Base.metadata.create_all(bind=engine)


@app.get("/")
async def root():
    return {"message": "Welcome to KernvoxHub API", "docs": "/docs"}


@app.get("/api/v1/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}
