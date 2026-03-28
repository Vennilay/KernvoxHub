import paramiko
import io
import logging
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


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

    def connect(self, timeout: int = 10, retries: int = 2) -> bool:
        """Подключение к SSH серверу с повторными попытками."""
        for attempt in range(retries):
            try:
                self.client = paramiko.SSHClient()
                self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                if self.ssh_key:
                    pkey = paramiko.RSAKey.from_private_key(io.StringIO(self.ssh_key))
                    self.client.connect(
                        hostname=self.host,
                        port=self.port,
                        username=self.username,
                        pkey=pkey,
                        timeout=timeout,
                        allow_agent=False,
                        look_for_keys=False
                    )
                else:
                    self.client.connect(
                        hostname=self.host,
                        port=self.port,
                        username=self.username,
                        password=self.password,
                        timeout=timeout,
                        allow_agent=False,
                        look_for_keys=False
                    )
                logger.info(f"SSH connected to {self.host}:{self.port} (attempt {attempt + 1})")
                return True
            except Exception as e:
                logger.warning(f"SSH connection attempt {attempt + 1} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(2)
                self.close()

        logger.error(f"Failed to connect to {self.host}:{self.port} after {retries} attempts")
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
