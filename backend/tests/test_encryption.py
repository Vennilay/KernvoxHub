"""
Тесты шифрования чувствительных полей Server (VULN-07 fix).

Проверяют:
1. encrypt_value / decrypt_value корректно работают
2. None и пустые строки возвращаются как есть
3. Модель Server шифрует при записи и расшифровывает при чтении
4. В БД хранится ciphertext, а не plaintext
5. API-ответы не содержат password/ssh_key
"""

import os
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from utils.encryption import encrypt_value, decrypt_value


# ---------------------------------------------------------------------------
# Фикстура: валидный Fernet-ключ (переопределяет env до импорта settings)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    """Генерируем валидный Fernet-ключ и ставим в env."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", key)


# ---------------------------------------------------------------------------
# Тесты утилит шифрования
# ---------------------------------------------------------------------------

class TestEncryptionUtils:
    def test_encrypt_decrypt_roundtrip(self):
        secret = "my_super_secret_password"
        encrypted = encrypt_value(secret)
        assert encrypted != secret
        assert encrypted.startswith("gAAAAA")  # Fernet prefix
        decrypted = decrypt_value(encrypted)
        assert decrypted == secret

    def test_encrypt_none_returns_none(self):
        assert encrypt_value(None) is None

    def test_encrypt_empty_string_returns_empty(self):
        assert encrypt_value("") == ""

    def test_decrypt_none_returns_none(self):
        assert decrypt_value(None) is None

    def test_decrypt_empty_string_returns_empty(self):
        assert decrypt_value("") == ""

    def test_decrypt_unencrypted_raises(self):
        """Строка, не являющаяся Fernet-токеном, вызывает ошибку."""
        plaintext = "not_encrypted_password"
        with pytest.raises(Exception):
            decrypt_value(plaintext)

    def test_different_encryption_outputs(self):
        """Один и тот же plaintext даёт разный ciphertext (Fernet включает timestamp)."""
        secret = "same_secret"
        enc1 = encrypt_value(secret)
        enc2 = encrypt_value(secret)
        assert enc1 != enc2
        assert decrypt_value(enc1) == secret
        assert decrypt_value(enc2) == secret


# ---------------------------------------------------------------------------
# Тесты модели Server
# ---------------------------------------------------------------------------

class TestServerEncryption:
    def test_password_encrypted_in_db(self, db_session):
        """При записи password в БД попадает зашифрованным."""
        from models.server import Server

        server = Server(
            name="test-srv",
            host="10.0.0.1",
            username="admin",
            password="plain_password_123",
        )
        db_session.add(server)
        db_session.commit()

        # Сырой запрос к БД — должно быть зашифровано
        row = db_session.execute(
            text("SELECT password FROM servers WHERE id = :id"),
            {"id": server.id},
        ).fetchone()
        assert row is not None
        assert row[0].startswith("gAAAAA")

    def test_password_decrypted_on_read(self, db_session):
        """При чтении через property password возвращается расшифрованное."""
        from models.server import Server

        server = Server(
            name="test-srv",
            host="10.0.0.1",
            username="admin",
            password="plain_password_123",
        )
        db_session.add(server)
        db_session.commit()
        db_session.refresh(server)

        assert server.password == "plain_password_123"

    def test_ssh_key_encrypted_in_db(self, db_session):
        """SSH-ключ хранится в БД зашифрованным."""
        from models.server import Server

        key = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
        server = Server(
            name="test-srv",
            host="10.0.0.1",
            username="admin",
            ssh_key=key,
        )
        db_session.add(server)
        db_session.commit()

        row = db_session.execute(
            text("SELECT ssh_key FROM servers WHERE id = :id"),
            {"id": server.id},
        ).fetchone()
        assert row is not None
        assert row[0].startswith("gAAAAA")

    def test_ssh_key_decrypted_on_read(self, db_session):
        """При чтении через property ssh_key возвращается расшифрованное."""
        from models.server import Server

        key = "-----BEGIN RSA PRIVATE KEY-----\ntest_key_content\n-----END RSA PRIVATE KEY-----"
        server = Server(
            name="test-srv",
            host="10.0.0.1",
            username="admin",
            ssh_key=key,
        )
        db_session.add(server)
        db_session.commit()
        db_session.refresh(server)

        assert server.ssh_key == key

    def test_none_password_and_ssh_key(self, db_session):
        """None-значения не ломают шифрование."""
        from models.server import Server

        server = Server(
            name="test-srv",
            host="10.0.0.1",
            username="admin",
        )
        db_session.add(server)
        db_session.commit()
        db_session.refresh(server)

        assert server.password is None
        assert server.ssh_key is None

    def test_password_update_via_setattr(self, db_session):
        """setattr(obj, 'password', val) корректно шифрует (через property setter)."""
        from models.server import Server

        server = Server(
            name="test-srv",
            host="10.0.0.1",
            username="admin",
        )
        db_session.add(server)
        db_session.commit()

        # Эмуляция того, что делает update_server в API
        setattr(server, "password", "new_password_456")
        db_session.commit()
        db_session.refresh(server)

        assert server.password == "new_password_456"

        row = db_session.execute(
            text("SELECT password FROM servers WHERE id = :id"),
            {"id": server.id},
        ).fetchone()
        assert row[0].startswith("gAAAAA")


# ---------------------------------------------------------------------------
# Тесты API: password/ssh_key не утекают в ответ
# ---------------------------------------------------------------------------

class TestServerAPIEncryption:
    def test_create_server_response_excludes_secrets(self, client):
        """POST /servers не возвращает password/ssh_key в ответе."""
        response = client.post(
            "/api/v1/servers",
            json={
                "name": "test-srv",
                "host": "10.0.0.1",
                "username": "admin",
                "password": "secret123",
                "ssh_key": "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert "password" not in data
        assert "ssh_key" not in data

    def test_get_servers_excludes_secrets(self, client):
        """GET /servers не возвращает password/ssh_key."""
        # Сначала создаём сервер
        client.post(
            "/api/v1/servers",
            json={
                "name": "test-srv",
                "host": "10.0.0.1",
                "username": "admin",
                "password": "secret123",
            },
        )
        response = client.get("/api/v1/servers")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert "password" not in data[0]
        assert "ssh_key" not in data[0]
