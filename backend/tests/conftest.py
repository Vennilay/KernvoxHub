import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from cryptography.fernet import Fernet

_TEST_ENCRYPTION_KEY = Fernet.generate_key().decode()
_TEST_API_SECRET = "test_api_secret_for_development"
_TEST_API_TOKEN = "kvx_test_bootstrap_token"
_TEST_REDIS_PASSWORD = "test_redis_password"

os.environ.setdefault("ENCRYPTION_KEY", _TEST_ENCRYPTION_KEY)
os.environ.setdefault("API_SECRET", _TEST_API_SECRET)
os.environ.setdefault("API_TOKEN", _TEST_API_TOKEN)
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("REDIS_PASSWORD", _TEST_REDIS_PASSWORD)
os.environ.setdefault("CORS_ORIGINS", "*")
os.environ.setdefault("INTERNAL_API_KEY", "")

from main import app
from models.database import Base, get_db
from api.middleware import auth as auth_middleware


SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    original_auth_redis = auth_middleware.redis_client
    auth_middleware.redis_client = None

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        auth_middleware.redis_client = original_auth_redis
        app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def auth_headers():
    return {"X-API-Key": os.environ["API_TOKEN"]}


@pytest.fixture(scope="function")
def internal_headers():
    token = os.environ.get("INTERNAL_API_KEY", "")
    return {"X-Internal-Key": token} if token else {}
