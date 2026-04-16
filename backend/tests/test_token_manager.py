from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("REDIS_PASSWORD", "test_redis_password")
os.environ.setdefault("API_SECRET", "legacy_secret_value_that_must_not_define_tokens")
os.environ.setdefault("API_TOKEN", "kvx_bootstrap_token_for_tests")
os.environ.setdefault("ENCRYPTION_KEY", "test_encryption_key")

config_stub = ModuleType("config")
config_stub.settings = SimpleNamespace(
    DATABASE_URL=os.environ["DATABASE_URL"],
    REDIS_URL=os.environ["REDIS_URL"],
    REDIS_PASSWORD=os.environ["REDIS_PASSWORD"],
    API_SECRET=os.environ["API_SECRET"],
    API_TOKEN=os.environ["API_TOKEN"],
    ENCRYPTION_KEY=os.environ["ENCRYPTION_KEY"],
)
sys.modules.setdefault("config", config_stub)

redis_stub = ModuleType("redis")


class RedisError(Exception):
    pass


redis_stub.exceptions = SimpleNamespace(RedisError=RedisError)
redis_stub.from_url = lambda *args, **kwargs: None
sys.modules.setdefault("redis", redis_stub)

from services import token_manager


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value

    def sadd(self, key: str, value: str) -> None:
        self.sets.setdefault(key, set()).add(value)

    def sismember(self, key: str, value: str) -> bool:
        return value in self.sets.get(key, set())


class TokenManagerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.original_redis = token_manager.redis_client
        self.original_bootstrap = token_manager.BOOTSTRAP_API_KEY
        self.fake_redis = FakeRedis()
        token_manager.redis_client = self.fake_redis
        token_manager.BOOTSTRAP_API_KEY = None

    def tearDown(self) -> None:
        token_manager.redis_client = self.original_redis
        token_manager.BOOTSTRAP_API_KEY = self.original_bootstrap

    def test_bootstrap_token_is_independent_from_api_secret(self) -> None:
        legacy_token = f"kvx_{os.environ['API_SECRET'][:32]}"

        self.assertEqual(token_manager.get_bootstrap_api_key(), os.environ["API_TOKEN"])
        self.assertFalse(token_manager.validate_api_token(legacy_token))
        self.assertTrue(token_manager.validate_api_token(os.environ["API_TOKEN"]))

    def test_generate_api_token_persists_only_hash(self) -> None:
        token = token_manager.generate_api_token()
        token_hash = token_manager._hash_token(token)

        self.assertTrue(token.startswith(token_manager.TOKEN_PREFIX))
        self.assertIn(token_hash, self.fake_redis.sets[token_manager.TOKEN_HASH_SET_KEY])
        self.assertNotIn(token, self.fake_redis.sets[token_manager.TOKEN_HASH_SET_KEY])

    def test_validate_generated_token_uses_hash_storage(self) -> None:
        token = token_manager.generate_api_token()

        self.assertTrue(token_manager.validate_api_token(token))
        self.assertEqual(
            self.fake_redis.get(f"{token_manager.TOKEN_CACHE_PREFIX}{token_manager._hash_token(token)}"),
            "1",
        )

    def test_generate_api_token_requires_redis_for_persistence(self) -> None:
        token_manager.redis_client = None

        with self.assertRaises(RuntimeError):
            token_manager.generate_api_token()


if __name__ == "__main__":
    unittest.main()
