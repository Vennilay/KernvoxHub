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
        """Проверяет базовый roundtrip Fernet-шифрования.

        Что делает: шифрует строковый секрет и затем расшифровывает результат.
        Ожидаемая реакция: ciphertext отличается от plaintext, выглядит как Fernet-token и decrypt возвращает исходный секрет.
        """
        secret = "my_super_secret_password"
        encrypted = encrypt_value(secret)
        assert encrypted != secret
        assert encrypted.startswith("gAAAAA")
        decrypted = decrypt_value(encrypted)
        assert decrypted == secret

    def test_encrypt_none_returns_none(self):
        """Проверяет обработку `None` при шифровании.

        Что делает: вызывает `encrypt_value(None)`.
        Ожидаемая реакция: функция возвращает `None`, чтобы optional secret-поля можно было хранить пустыми.
        """
        assert encrypt_value(None) is None

    def test_encrypt_empty_string_returns_empty(self):
        """Проверяет обработку пустой строки при шифровании.

        Что делает: вызывает `encrypt_value("")`.
        Ожидаемая реакция: функция возвращает пустую строку без создания Fernet-token для отсутствующего значения.
        """
        assert encrypt_value("") == ""

    def test_decrypt_none_returns_none(self):
        """Проверяет обработку `None` при расшифровке.

        Что делает: вызывает `decrypt_value(None)`.
        Ожидаемая реакция: функция возвращает `None`, не падая на optional encrypted-полях.
        """
        assert decrypt_value(None) is None

    def test_decrypt_empty_string_returns_empty(self):
        """Проверяет обработку пустой строки при расшифровке.

        Что делает: вызывает `decrypt_value("")`.
        Ожидаемая реакция: функция возвращает пустую строку, сохраняя симметрию с `encrypt_value("")`.
        """
        assert decrypt_value("") == ""

    def test_decrypt_unencrypted_raises(self):
        """Проверяет отказ при попытке расшифровать plaintext.

        Что делает: передаёт не-Fernet строку в `decrypt_value`.
        Ожидаемая реакция: cryptography выбрасывает исключение, чтобы незашифрованные секреты не считались валидными.
        """
        plaintext = "not_encrypted_password"
        with pytest.raises(Exception):
            decrypt_value(plaintext)

    def test_different_encryption_outputs(self):
        """Проверяет недетерминированность Fernet ciphertext.

        Что делает: дважды шифрует один и тот же секрет.
        Ожидаемая реакция: ciphertext-ы разные, но оба успешно расшифровываются в исходное значение.
        """
        secret = "same_secret"
        enc1 = encrypt_value(secret)
        enc2 = encrypt_value(secret)
        assert enc1 != enc2
        assert decrypt_value(enc1) == secret
        assert decrypt_value(enc2) == secret


class TestServerEncryption:
    def test_password_encrypted_in_db(self, db_session):
        """Проверяет, что SSH password хранится в БД зашифрованным.

        Что делает: создаёт Server с plaintext password и читает сырой столбец `password` SQL-запросом.
        Ожидаемая реакция: в БД лежит Fernet-token, а не исходный пароль.
        """
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
        """Проверяет прозрачное чтение SSH password через model property.

        Что делает: сохраняет сервер с password, обновляет объект из БД и читает `server.password`.
        Ожидаемая реакция: property возвращает исходный plaintext только на уровне Python-модели.
        """
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
        """Проверяет, что приватный SSH key хранится в БД зашифрованным.

        Что делает: создаёт Server с приватным ключом и читает сырой столбец `ssh_key`.
        Ожидаемая реакция: в БД лежит Fernet-token, а не PEM-текст ключа.
        """
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
        """Проверяет прозрачное чтение SSH key через model property.

        Что делает: сохраняет сервер с приватным ключом, обновляет объект из БД и читает `server.ssh_key`.
        Ожидаемая реакция: property возвращает исходный PEM-текст для подключения, не раскрывая его в API response.
        """
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
        """Проверяет optional SSH credential поля модели.

        Что делает: создаёт Server без password и ssh_key.
        Ожидаемая реакция: оба property возвращают `None`, а модель не падает на пустых credential.
        """
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
        """Проверяет шифрование password при обновлении через `setattr`.

        Что делает: создаёт Server без password, затем задаёт новый password через `setattr` и читает сырой столбец БД.
        Ожидаемая реакция: property возвращает plaintext, а в БД хранится Fernet-token.
        """
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
        """Проверяет, что `POST /servers` не возвращает секреты.

        Что делает: создаёт сервер через API с password и анализирует JSON response.
        Ожидаемая реакция: ответ содержит публичные поля сервера, но не содержит `password` и `ssh_key`.
        """
        response = client.post(
            "/api/v1/servers",
            json={
                "name": "test-srv",
                "host": "10.0.0.1",
                "username": "admin",
                "password": "secret123",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert "password" not in data
        assert "ssh_key" not in data

    def test_get_servers_excludes_secrets(self, client, auth_headers):
        """Проверяет, что `GET /servers` не раскрывает секреты.

        Что делает: создаёт сервер с password и запрашивает список серверов.
        Ожидаемая реакция: элементы списка не содержат `password` и `ssh_key`, даже если они есть в БД.
        """
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
