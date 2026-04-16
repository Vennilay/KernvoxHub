"""Тесты шифрования чувствительных полей."""

import os
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from utils.encryption import encrypt_value, decrypt_value


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    """Подменяет ключ шифрования."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", key)


class TestEncryptionUtils:
    def test_encrypt_decrypt_roundtrip(self):
        secret = "my_super_secret_password"
        encrypted = encrypt_value(secret)
        assert encrypted != secret
        assert encrypted.startswith("gAAAAA")
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
        """Проверяет ошибку на нешифрованной строке."""
        plaintext = "not_encrypted_password"
        with pytest.raises(Exception):
            decrypt_value(plaintext)

    def test_different_encryption_outputs(self):
        """Проверяет различие ciphertext для одинакового ввода."""
        secret = "same_secret"
        enc1 = encrypt_value(secret)
        enc2 = encrypt_value(secret)
        assert enc1 != enc2
        assert decrypt_value(enc1) == secret
        assert decrypt_value(enc2) == secret


class TestServerEncryption:
    def test_password_encrypted_in_db(self, db_session):
        """Проверяет шифрование password в БД."""
        from models.server import Server

        server = Server(
            name="test-srv",
            host="10.0.0.1",
            username="admin",
            password="plain_password_123",
        )
        db_session.add(server)
        db_session.commit()

        row = db_session.execute(
            text("SELECT password FROM servers WHERE id = :id"),
            {"id": server.id},
        ).fetchone()
        assert row is not None
        assert row[0].startswith("gAAAAA")

    def test_password_decrypted_on_read(self, db_session):
        """Проверяет чтение password через property."""
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
        """Проверяет шифрование SSH-ключа в БД."""
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
        """Проверяет чтение SSH-ключа через property."""
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
        """Проверяет обработку None."""
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
        """Проверяет обновление password через setattr."""
        from models.server import Server

        server = Server(
            name="test-srv",
            host="10.0.0.1",
            username="admin",
        )
        db_session.add(server)
        db_session.commit()

        setattr(server, "password", "new_password_456")
        db_session.commit()
        db_session.refresh(server)

        assert server.password == "new_password_456"

        row = db_session.execute(
            text("SELECT password FROM servers WHERE id = :id"),
            {"id": server.id},
        ).fetchone()
        assert row[0].startswith("gAAAAA")


class TestServerAPIEncryption:
    def test_create_server_response_excludes_secrets(self, client, auth_headers):
        """Проверяет отсутствие секретов в ответе POST /servers."""
        response = client.post(
            "/api/v1/servers",
            json={
                "name": "test-srv",
                "host": "10.0.0.1",
                "username": "admin",
                "password": "secret123",
                "ssh_key": "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert "password" not in data
        assert "ssh_key" not in data

    def test_get_servers_excludes_secrets(self, client, auth_headers):
        """Проверяет отсутствие секретов в ответе GET /servers."""
        client.post(
            "/api/v1/servers",
            json={
                "name": "test-srv",
                "host": "10.0.0.1",
                "username": "admin",
                "password": "secret123",
            },
            headers=auth_headers,
        )
        response = client.get("/api/v1/servers", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert "password" not in data[0]
        assert "ssh_key" not in data[0]
