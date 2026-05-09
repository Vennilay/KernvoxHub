"""Тесты проверки SSH host key."""

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from utils.encryption import encrypt_value, decrypt_value
from collector.ssh_client import HostKeyMismatchError


class TestHostKeyMismatchError:
    def test_message_contains_host_and_port(self):
        """Проверяет информативность ошибки SSH host key mismatch.

        Что делает: создаёт `HostKeyMismatchError` с host/port и разными ключами.
        Ожидаемая реакция: текст ошибки содержит endpoint и MITM-предупреждение для логов и диагностики.
        """
        exc = HostKeyMismatchError(
            host="192.168.1.100",
            port=22,
            expected="ssh-rsa AAAA_expected_key",
            got="ssh-rsa AAAA_got_key",
        )
        assert "192.168.1.100:22" in str(exc)
        assert "MITM" in str(exc)

    def test_fingerprint_truncation(self):
        """Проверяет безопасное сокращение fingerprint в сообщениях.

        Что делает: вызывает `_fingerprint` для короткого и длинного host key.
        Ожидаемая реакция: короткий ключ не меняется, длинный обрезается с `...`, чтобы логи не раздувались полным ключом.
        """
        short = HostKeyMismatchError._fingerprint("ssh-rsa abc")
        assert "..." not in short

        long = HostKeyMismatchError._fingerprint("ssh-rsa " + "A" * 200)
        assert "..." in long

    def test_fingerprint_empty(self):
        """Проверяет fingerprint для пустого host key.

        Что делает: вызывает `_fingerprint` с пустой строкой и `None`.
        Ожидаемая реакция: функция возвращает `<none>`, не падая при неполных данных ошибки.
        """
        assert HostKeyMismatchError._fingerprint("") == "<none>"
        assert HostKeyMismatchError._fingerprint(None) == "<none>"


class TestHostKeyEncryption:
    """Проверяет работу host_key в модели."""

    def test_host_key_encrypted_in_model(self, db_session):
        """Проверяет шифрование SSH host key в модели Server.

        Что делает: присваивает `server.host_key` и читает сырой столбец `host_key` из БД.
        Ожидаемая реакция: БД содержит Fernet-token, а не открытый host key.
        """
        from models.server import Server

        server = Server(
            name="test-srv",
            host="10.0.0.1",
            username="admin",
        )
        server.host_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQ..."
        db_session.add(server)
        db_session.commit()

        row = db_session.execute(
            text("SELECT host_key FROM servers WHERE id = :id"),
            {"id": server.id},
        ).fetchone()
        assert row is not None
        assert row[0].startswith("gAAAAA")

    def test_host_key_decrypted_on_read(self, db_session):
        """Проверяет прозрачное чтение SSH host key.

        Что делает: сохраняет host key через property, refresh-ит модель и читает `server.host_key`.
        Ожидаемая реакция: property возвращает исходный host key для последующей проверки SSH-соединения.
        """
        from models.server import Server

        original_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG_test_key"
        server = Server(
            name="test-srv",
            host="10.0.0.1",
            username="admin",
        )
        server.host_key = original_key
        db_session.add(server)
        db_session.commit()
        db_session.refresh(server)

        assert server.host_key == original_key

    def test_host_key_none(self, db_session):
        """Проверяет отсутствие host key у нового сервера.

        Что делает: создаёт Server без сохранённого host key.
        Ожидаемая реакция: `server.host_key` равен `None`, что означает режим первого доверенного обнаружения ключа.
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

        assert server.host_key is None

    def test_host_key_mismatch_detection(self):
        """Проверяет модель обнаружения несовпадения host key.

        Что делает: сравнивает расшифрованный сохранённый ключ с отличающимся ключом и создаёт `HostKeyMismatchError`.
        Ожидаемая реакция: ошибка содержит endpoint и MITM-предупреждение, подтверждая критичность расхождения.
        """
        saved_key = encrypt_value("ssh-rsa AAAA_original_key")
        got_key = "ssh-rsa AAAA_fake_key_from_server"

        decrypted_saved = decrypt_value(saved_key)
        assert decrypted_saved != got_key

        with pytest.raises(HostKeyMismatchError) as exc_info:
            raise HostKeyMismatchError(
                host="10.0.0.1", port=22,
                expected=saved_key, got=got_key,
            )

        assert "10.0.0.1:22" in str(exc_info.value)
        assert "MITM" in str(exc_info.value)

    def test_host_key_match_simulation(self):
        """Проверяет позитивный сценарий совпадения host key.

        Что делает: шифрует исходный host key, расшифровывает его и сравнивает с ключом от сервера.
        Ожидаемая реакция: значения совпадают, что соответствует безопасному повторному SSH-подключению.
        """
        original = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG_match_key"
        saved_key = encrypt_value(original)
        got_key = original

        decrypted = decrypt_value(saved_key)
        assert decrypted == got_key
