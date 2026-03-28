from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.middleware.auth import api_key_middleware
from api.routes import servers_router, metrics_router, android_router
from models.database import Base, engine

app = FastAPI(
    title="KernvoxHub API",
    description="Backend для сбора метрик с серверов и предоставления данных Android-приложению Kernvox",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
