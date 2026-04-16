import paramiko
import io
import logging
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class HostKeyMismatchError(Exception):
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
        self.discovered_host_key: Optional[str] = None

    def _load_private_key(self):
        key_types = []
        for key_type_name in ("Ed25519Key", "ECDSAKey", "RSAKey", "DSSKey"):
            key_type = getattr(paramiko, key_type_name, None)
            if key_type is not None:
                key_types.append(key_type)

        last_error = None
        for key_type in key_types:
            try:
                return key_type.from_private_key(io.StringIO(self.ssh_key))
            except Exception as exc:
                last_error = exc

        raise paramiko.SSHException(
            f"Unsupported or invalid private key format: {last_error}"
        )

    def connect(
        self,
        timeout: int = 10,
        retries: int = 2,
        saved_host_key: Optional[str] = None,
    ) -> bool:
        self.discovered_host_key = None

        for attempt in range(retries):
            try:
                self.client = paramiko.SSHClient()
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
                    pkey = self._load_private_key()
                    connect_kwargs["pkey"] = pkey
                else:
                    connect_kwargs["password"] = self.password

                self.client.connect(**connect_kwargs)

                transport = self.client.get_transport()
                if transport is None:
                    raise RuntimeError("Transport is None after connect")

                remote_key = transport.get_remote_server_key()
                remote_key_string = f"{remote_key.get_name()} {remote_key.get_base64()}"
                self.discovered_host_key = remote_key_string

                if saved_host_key is not None:
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
                    logger.info(
                        "Discovered new host key for %s:%d (type: %s)",
                        self.host, self.port, remote_key.get_name(),
                    )

                logger.info(
                    "SSH connected to %s:%d (attempt %d)",
                    self.host, self.port, attempt + 1,
                )
                return True

            except HostKeyMismatchError:
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
