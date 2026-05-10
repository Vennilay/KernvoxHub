from services import server_actions
from services.server_actions import ServerConnectionData, configure_reboot_sudo, reboot_server


class _FakeSSHClient:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.discovered_host_key = "ssh-ed25519 AAAAfake"
        self.calls = []
        self.closed = False
        _FakeSSHClient.instances.append(self)

    def connect(self, saved_host_key=None, timeout=10):
        self.saved_host_key = saved_host_key
        self.connect_timeout = timeout
        return True

    def execute(self, command, timeout=10, input_data=None, get_pty=False):
        self.calls.append(
            {
                "command": command,
                "timeout": timeout,
                "input_data": input_data,
                "get_pty": get_pty,
            }
        )
        if len(self.calls) == 1:
            return 1, "", "sudo: a password is required"
        return 0, "", ""

    def close(self):
        self.closed = True


class _SuccessfulSSHClient(_FakeSSHClient):
    def execute(self, command, timeout=10, input_data=None, get_pty=False):
        self.calls.append(
            {
                "command": command,
                "timeout": timeout,
                "input_data": input_data,
                "get_pty": get_pty,
            }
        )
        return 0, "", ""


def test_reboot_uses_password_sudo_fallback(monkeypatch):
    """Проверяет fallback на sudo -S, когда passwordless sudo недоступен.

    Что делает: подменяет SSH-клиент, первый reboot возвращает ошибку sudo без пароля, второй проходит через stdin-пароль.
    Ожидаемая реакция: сервис принимает reboot, передаёт пароль только в stdin и запрашивает PTY для совместимости с sudo requiretty.
    """
    _FakeSSHClient.instances = []
    monkeypatch.setattr(server_actions, "SSHClient", _FakeSSHClient)

    result = reboot_server(
        ServerConnectionData(
            host="127.0.0.1",
            port=22,
            username="ops",
            password="secret",
            ssh_key=None,
            saved_host_key=None,
        )
    )

    ssh = _FakeSSHClient.instances[0]
    assert result.status == "accepted"
    assert len(ssh.calls) == 2
    assert "sudo -S -p '' -v" in ssh.calls[1]["command"]
    assert ssh.calls[1]["input_data"] == "secret\n"
    assert ssh.calls[1]["get_pty"] is True
    assert ssh.closed is True


def test_reboot_without_password_reports_sudo_guidance(monkeypatch):
    """Проверяет диагностическое сообщение для key-only сервера без sudoers.

    Что делает: подменяет SSH-клиент и имитирует отказ sudo из-за отсутствия NOPASSWD.
    Ожидаемая реакция: fallback не запускается, а сообщение объясняет, как настроить reboot без интерактивного пароля.
    """
    _FakeSSHClient.instances = []
    monkeypatch.setattr(server_actions, "SSHClient", _FakeSSHClient)

    result = reboot_server(
        ServerConnectionData(
            host="127.0.0.1",
            port=22,
            username="ops",
            password=None,
            ssh_key="private-key",
            saved_host_key=None,
        )
    )

    ssh = _FakeSSHClient.instances[0]
    assert result.status == "failed"
    assert len(ssh.calls) == 1
    assert "Configure NOPASSWD sudoers" in result.message


def test_configure_reboot_sudo_uses_one_time_sudo_password(monkeypatch):
    """Проверяет настройку sudoers с одноразовым sudo-паролем.

    Что делает: подменяет SSH-клиент и вызывает configure_reboot_sudo для key-only сервера.
    Ожидаемая реакция: sudo-пароль передаётся только через stdin, команда использует sudo -S и пишет sudoers-файл.
    """
    _FakeSSHClient.instances = []
    monkeypatch.setattr(server_actions, "SSHClient", _SuccessfulSSHClient)

    result = configure_reboot_sudo(
        ServerConnectionData(
            host="127.0.0.1",
            port=22,
            username="ops",
            password=None,
            ssh_key="private-key",
            saved_host_key=None,
        ),
        sudo_password="sudo-secret",
    )

    ssh = _FakeSSHClient.instances[0]
    assert result.status == "configured"
    assert len(ssh.calls) == 1
    assert "sudo -S -p ''" in ssh.calls[0]["command"]
    assert "/etc/sudoers.d/kernvoxhub-reboot" in ssh.calls[0]["command"]
    assert ssh.calls[0]["input_data"] == "sudo-secret\n"
    assert ssh.calls[0]["get_pty"] is True


def test_configure_reboot_sudo_rejects_unsafe_username(monkeypatch):
    """Проверяет отказ от записи небезопасного username в sudoers.

    Что делает: передаёт username с пробелом и подменяет SSH-клиент классом, который не должен создаваться.
    Ожидаемая реакция: сервис возвращает failed до SSH-подключения.
    """
    def fail_if_called(**_kwargs):
        raise AssertionError("SSHClient must not be created for unsafe sudoers username")

    monkeypatch.setattr(server_actions, "SSHClient", fail_if_called)

    result = configure_reboot_sudo(
        ServerConnectionData(
            host="127.0.0.1",
            port=22,
            username="bad user",
            password=None,
            ssh_key="private-key",
            saved_host_key=None,
        )
    )

    assert result.status == "failed"
    assert "username" in result.message
