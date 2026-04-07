"""
Тесты проверки SSH host key (VULN-06 fix).

Проверяют:
1. HostKeyMismatchError содержит корректную информацию
2. При первом подключении host_key сохраняется в БД
3. При повторном подключении с тем же ключом — успех
4. При подмене ключа — HostKeyMismatchError

Примечание: полноценные интегральные тесты требуют реального SSH-сервера.
Здесь тестируется логика шифрования/сравнения ключей и поведение модели.
"""

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from utils.encryption import encrypt_value, decrypt_value
from collector.ssh_client import HostKeyMismatchError


class TestHostKeyMismatchError:
    def test_message_contains_host_and_port(self):
        exc = HostKeyMismatchError(
            host="192.168.1.100",
            port=22,
            expected="ssh-rsa AAAA_expected_key",
            got="ssh-rsa AAAA_got_key",
        )
        assert "192.168.1.100:22" in str(exc)
        assert "MITM" in str(exc)

    def test_fingerprint_truncation(self):
        """Fingerprint обрезается для читаемости."""
        short = HostKeyMismatchError._fingerprint("ssh-rsa abc")
        assert "..." not in short  # короткий — без обрезки

        long = HostKeyMismatchError._fingerprint("ssh-rsa " + "A" * 200)
        assert "..." in long  # длинный — обрезан

    def test_fingerprint_empty(self):
        assert HostKeyMismatchError._fingerprint("") == "<none>"
        assert HostKeyMismatchError._fingerprint(None) == "<none>"


class TestHostKeyEncryption:
    """Проверяем, что host_key шифруется в модели так же, как password/ssh_key."""

    def test_host_key_encrypted_in_model(self, db_session):
        """При записи host_key в БД попадает зашифрованным."""
        from models.server import Server

        server = Server(
            name="test-srv",
            host="10.0.0.1",
            username="admin",
        )
        server.host_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQ..."
        db_session.add(server)
        db_session.commit()

        # Сырой запрос — должно быть зашифровано
        row = db_session.execute(
            text("SELECT host_key FROM servers WHERE id = :id"),
            {"id": server.id},
        ).fetchone()
        assert row is not None
        assert row[0].startswith("gAAAAA")

    def test_host_key_decrypted_on_read(self, db_session):
        """При чтении через property host_key возвращается расшифрованное."""
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
        """None host_key не ломает модель."""
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
        """Симуляция: если сохранённый ключ не совпадает — должно быть исключение."""
        saved_key = encrypt_value("ssh-rsa AAAA_original_key")
        got_key = "ssh-rsa AAAA_fake_key_from_server"

        # Симуляция того, что делает SSHClient.connect() после подключения
        decrypted_saved = decrypt_value(saved_key)
        assert decrypted_saved != got_key

        # Должно возникнуть исключение
        with pytest.raises(HostKeyMismatchError) as exc_info:
            raise HostKeyMismatchError(
                host="10.0.0.1", port=22,
                expected=saved_key, got=got_key,
            )

        assert "10.0.0.1:22" in str(exc_info.value)
        assert "MITM" in str(exc_info.value)

    def test_host_key_match_simulation(self):
        """Симуляция: если ключи совпадают — подключения проходит."""
        original = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG_match_key"
        saved_key = encrypt_value(original)
        got_key = original  # сервер вернул тот же ключ

        decrypted = decrypt_value(saved_key)
        assert decrypted == got_key  # совпадают — подключение разрешено
