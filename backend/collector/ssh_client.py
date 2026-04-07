import paramiko
import io
import logging
import time
from typing import Optional, Tuple

from utils.encryption import encrypt_value

logger = logging.getLogger(__name__)


class HostKeyMismatchError(Exception):
    """Host key сервера не совпадает с сохранённым — возможна MITM-атака."""

    def __init__(self, host: str, port: int, expected: str, got: str):
        self.host = host
        self.port = port
        self.expected_key = expected
        self.got_key = got
        super().__init__(
            f"Host key mismatch for {host}:{port} — possible MITM attack! "
            f"Expected key fingerprint: {self._fingerprint(expected)}, "
            f"Got: {self._fingerprint(got)}"
        )

    @staticmethod
    def _fingerprint(key_string: str) -> str:
        """MD5-подобный отпечаток из base64-ключа (первые 16 символов)."""
        if not key_string:
            return "<none>"
        parts = key_string.split(None, 1)
        raw = parts[1] if len(parts) > 1 else parts[0]
        return raw[:32] + "..." if len(raw) > 32 else raw


class SSHClient:
    def __init__(self, host: str, port: int, username: str,
                 password: Optional[str] = None,
                 ssh_key: Optional[str] = None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.ssh_key = ssh_key
        self.client: Optional[paramiko.SSHClient] = None

    def connect(self, timeout: int = 10, retries: int = 2,
                server=None, db=None) -> bool:
        """
        Подключение к SSH с проверкой host-ключа.

        :param server: объект Server из БД (для проверки/сохранения host_key)
        :param db: SQLAlchemy Session (для commit при первом сохранении ключа)
        :param timeout: таймаут подключения в секундах
        :param retries: количество повторных попыток
        :return: True при успешном подключении
        :raises HostKeyMismatchError: если ключ не совпадает с сохранённым
        """
        saved_host_key: Optional[str] = None
        if server is not None:
            saved_host_key = server.host_key

        for attempt in range(retries):
            try:
                self.client = paramiko.SSHClient()
                # Всегда используем AutoAddPolicy, но ПРОВЕРЯЕМ ключ после
                # подключения вручную — так мы не теряем возможность первого
                # подключения, но при этом ловим MITM при повторных.
                self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                connect_kwargs = {
                    "hostname": self.host,
                    "port": self.port,
                    "username": self.username,
                    "timeout": timeout,
                    "allow_agent": False,
                    "look_for_keys": False,
                }

                if self.ssh_key:
                    pkey = paramiko.RSAKey.from_private_key(
                        io.StringIO(self.ssh_key)
                    )
                    connect_kwargs["pkey"] = pkey
                else:
                    connect_kwargs["password"] = self.password

                self.client.connect(**connect_kwargs)

                # --- Проверка host key ---
                transport = self.client.get_transport()
                if transport is None:
                    raise RuntimeError("Transport is None after connect")

                remote_key = transport.get_remote_server_key()
                remote_key_string = f"{remote_key.get_name()} {remote_key.get_base64()}"

                if saved_host_key is not None:
                    # Ключ уже был сохранён — сверяем
                    if remote_key_string != saved_host_key:
                        logger.critical(
                            "POSSIBLE MITM ATTACK on %s:%d! "
                            "Expected: %s... Got: %s...",
                            self.host, self.port,
                            HostKeyMismatchError._fingerprint(saved_host_key),
                            HostKeyMismatchError._fingerprint(remote_key_string),
                        )
                        self.close()
                        raise HostKeyMismatchError(
                            self.host, self.port, saved_host_key, remote_key_string
                        )
                else:
                    # Первое подключение — сохраняем ключ
                    if server is not None and db is not None:
                        server._host_key_encrypted = encrypt_value(remote_key_string)
                        db.commit()
                        logger.info(
                            "New host key saved for %s:%d (type: %s)",
                            self.host, self.port, remote_key.get_name(),
                        )

                logger.info(
                    "SSH connected to %s:%d (attempt %d)",
                    self.host, self.port, attempt + 1,
                )
                return True

            except HostKeyMismatchError:
                # Не ретраим — это фатальная ошибка безопасности
                raise
            except Exception as e:
                logger.warning(
                    "SSH connection attempt %d failed: %s",
                    attempt + 1, e,
                )
                if attempt < retries - 1:
                    time.sleep(2)
                self.close()

        logger.error(
            "Failed to connect to %s:%d after %d attempts",
            self.host, self.port, retries,
        )
        return False

    def execute(self, command: str, timeout: int = 10) -> Tuple[int, str, str]:
        if not self.client:
            return -1, "", "Not connected"

        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            output = stdout.read().decode('utf-8', errors='replace')
            error = stderr.read().decode('utf-8', errors='replace')
            return exit_code, output, error
        except Exception as e:
            logger.error(f"SSH command execution error: {e}")
            return -1, "", str(e)

    def close(self):
        if self.client:
            self.client.close()
            self.client = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
