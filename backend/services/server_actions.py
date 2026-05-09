from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from collector.ssh_client import HostKeyMismatchError, SSHClient


REBOOT_COMMAND = (
    'if [ "$(id -u)" -eq 0 ]; then '
    "nohup sh -c 'sleep 1; "
    "if command -v systemctl >/dev/null 2>&1; then systemctl reboot; "
    "elif command -v shutdown >/dev/null 2>&1; then shutdown -r now; "
    "else reboot; fi' >/dev/null 2>&1 & "
    "else "
    "if ! command -v sudo >/dev/null 2>&1; then "
    "echo 'sudo is required for non-root reboot' >&2; exit 126; "
    "fi; "
    "sudo -n /sbin/shutdown -r now || "
    "sudo -n /usr/sbin/shutdown -r now || "
    "sudo -n shutdown -r now || "
    "sudo -n systemctl reboot || "
    "sudo -n reboot; "
    "fi"
)


@dataclass(frozen=True)
class ServerConnectionData:
    host: str
    port: int
    username: str
    password: Optional[str]
    ssh_key: Optional[str]
    saved_host_key: Optional[str]


@dataclass(frozen=True)
class ServerActionResult:
    status: str
    message: str
    discovered_host_key: Optional[str] = None


def reboot_server(connection: ServerConnectionData, *, timeout: int = 15) -> ServerActionResult:
    ssh = SSHClient(
        host=connection.host,
        port=connection.port,
        username=connection.username,
        password=connection.password,
        ssh_key=connection.ssh_key,
    )

    try:
        if not ssh.connect(saved_host_key=connection.saved_host_key, timeout=10):
            return ServerActionResult(
                status="connect_failed",
                message="Cannot connect to server over SSH",
                discovered_host_key=ssh.discovered_host_key,
            )

        exit_code, _, error = ssh.execute(REBOOT_COMMAND, timeout=timeout)
        if exit_code == 0:
            return ServerActionResult(
                status="accepted",
                message="Reboot command accepted by server",
                discovered_host_key=ssh.discovered_host_key,
            )

        return ServerActionResult(
            status="failed",
            message=(error or f"Reboot command failed with exit code {exit_code}")[:1000],
            discovered_host_key=ssh.discovered_host_key,
        )
    except HostKeyMismatchError as exc:
        return ServerActionResult(
            status="host_key_mismatch",
            message=str(exc),
            discovered_host_key=None,
        )
    except Exception as exc:
        return ServerActionResult(
            status="error",
            message=str(exc)[:1000],
            discovered_host_key=ssh.discovered_host_key,
        )
    finally:
        ssh.close()
