from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Optional

from collector.ssh_client import HostKeyMismatchError, SSHClient


ROOT_REBOOT_COMMAND = (
    "nohup sh -c 'sleep 1; "
    "if command -v systemctl >/dev/null 2>&1; then systemctl reboot; "
    "elif command -v shutdown >/dev/null 2>&1; then shutdown -r now; "
    "else reboot; fi' >/dev/null 2>&1 & "
)

PASSWORDLESS_REBOOT_COMMAND = (
    'if [ "$(id -u)" -eq 0 ]; then '
    f"{ROOT_REBOOT_COMMAND}"
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

PASSWORD_AUTH_REBOOT_COMMAND = (
    'if [ "$(id -u)" -eq 0 ]; then '
    f"{ROOT_REBOOT_COMMAND}"
    "else "
    "if ! command -v sudo >/dev/null 2>&1; then "
    "echo 'sudo is required for non-root reboot' >&2; exit 126; "
    "fi; "
    "sudo -S -p '' -v || exit $?; "
    "sudo -n /sbin/shutdown -r now || "
    "sudo -n /usr/sbin/shutdown -r now || "
    "sudo -n shutdown -r now || "
    "sudo -n systemctl reboot || "
    "sudo -n reboot; "
    "fi"
)

SUDO_REBOOT_GUIDANCE = (
    "Reboot requires root or sudo permissions. Configure NOPASSWD sudoers for "
    "shutdown/systemctl/reboot, or use password-based SSH auth so KernvoxHub can "
    "validate sudo non-interactively."
)

SUDOERS_FILE = "/etc/sudoers.d/kernvoxhub-reboot"
REBOOT_SUDOERS_COMMANDS = (
    "/sbin/shutdown -r now",
    "/usr/sbin/shutdown -r now",
    "/bin/systemctl reboot",
    "/usr/bin/systemctl reboot",
    "/sbin/reboot",
    "/usr/sbin/reboot",
    "/bin/reboot",
)
SAFE_SUDOERS_USER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


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


def _failed_reboot_message(error: str, exit_code: int) -> str:
    detail = error or f"Reboot command failed with exit code {exit_code}"
    return f"{detail.strip()}\n\n{SUDO_REBOOT_GUIDANCE}"[:1000]


def _sudoers_content(username: str) -> str:
    return f"{username} ALL=(root) NOPASSWD: {', '.join(REBOOT_SUDOERS_COMMANDS)}\n"


def _install_sudoers_script(username: str) -> str:
    content = shlex.quote(_sudoers_content(username))
    sudoers_file = shlex.quote(SUDOERS_FILE)
    return (
        "set -eu; "
        "tmp=$(mktemp); "
        "trap 'rm -f \"$tmp\"' EXIT; "
        f"printf %s {content} > \"$tmp\"; "
        "if command -v visudo >/dev/null 2>&1; then visudo -cf \"$tmp\" >/dev/null; fi; "
        f"install -o root -g root -m 0440 \"$tmp\" {sudoers_file}"
    )


def _configure_sudoers_command(username: str, *, use_password: bool = False) -> str:
    script = shlex.quote(_install_sudoers_script(username))
    sudo_prefix = "sudo -S -p ''" if use_password else "sudo -n"
    return (
        'if [ "$(id -u)" -eq 0 ]; then '
        f"sh -c {script}; "
        "else "
        "if ! command -v sudo >/dev/null 2>&1; then "
        "echo 'sudo is required to configure reboot permissions' >&2; exit 126; "
        "fi; "
        f"{sudo_prefix} sh -c {script}; "
        "fi"
    )


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

        exit_code, _, error = ssh.execute(PASSWORDLESS_REBOOT_COMMAND, timeout=timeout)
        if exit_code == 0:
            return ServerActionResult(
                status="accepted",
                message="Reboot command accepted by server",
                discovered_host_key=ssh.discovered_host_key,
            )

        if connection.password:
            exit_code, _, password_error = ssh.execute(
                PASSWORD_AUTH_REBOOT_COMMAND,
                timeout=timeout,
                input_data=f"{connection.password}\n",
                get_pty=True,
            )
            if exit_code == 0:
                return ServerActionResult(
                    status="accepted",
                    message="Reboot command accepted by server",
                    discovered_host_key=ssh.discovered_host_key,
                )
            error = password_error or error

        return ServerActionResult(
            status="failed",
            message=_failed_reboot_message(error, exit_code),
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


def configure_reboot_sudo(
    connection: ServerConnectionData,
    *,
    sudo_password: Optional[str] = None,
    timeout: int = 15,
) -> ServerActionResult:
    if not SAFE_SUDOERS_USER_RE.match(connection.username):
        return ServerActionResult(
            status="failed",
            message="SSH username contains characters that cannot be safely written to sudoers.",
        )

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

        command = _configure_sudoers_command(
            connection.username,
            use_password=sudo_password is not None,
        )
        exit_code, _, error = ssh.execute(
            command,
            timeout=timeout,
            input_data=f"{sudo_password}\n" if sudo_password is not None else None,
            get_pty=sudo_password is not None,
        )
        if exit_code == 0:
            return ServerActionResult(
                status="configured",
                message=f"Passwordless reboot sudoers installed at {SUDOERS_FILE}",
                discovered_host_key=ssh.discovered_host_key,
            )

        detail = error or f"sudoers setup failed with exit code {exit_code}"
        return ServerActionResult(
            status="failed",
            message=detail[:1000],
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
