from collector import ssh_client as ssh_client_module
from collector.ssh_client import SSHClient


class _FailingKey:
    @staticmethod
    def from_private_key(_value):
        raise ValueError("unsupported")


class _WorkingKey:
    @staticmethod
    def from_private_key(_value):
        return "loaded-key"


def test_load_private_key_skips_missing_dss(monkeypatch):
    """Проверяет загрузку SSH private key при отсутствии DSSKey в Paramiko.

    Что делает: monkeypatch-ит key loaders так, что Ed25519/RSA падают, ECDSA успешен, а DSSKey отсутствует.
    Ожидаемая реакция: SSHClient пропускает отсутствующий DSSKey и возвращает первый успешно загруженный ключ.
    """
    monkeypatch.setattr(ssh_client_module.paramiko, "Ed25519Key", _FailingKey)
    monkeypatch.setattr(ssh_client_module.paramiko, "ECDSAKey", _WorkingKey)
    monkeypatch.setattr(ssh_client_module.paramiko, "RSAKey", _FailingKey)
    monkeypatch.delattr(ssh_client_module.paramiko, "DSSKey", raising=False)

    client = SSHClient(
        host="127.0.0.1",
        port=22,
        username="root",
        ssh_key="-----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END OPENSSH PRIVATE KEY-----",
    )

    assert client._load_private_key() == "loaded-key"


class _FakeChannel:
    def __init__(self):
        self.write_shutdown = False

    def recv_exit_status(self):
        return 0

    def shutdown_write(self):
        self.write_shutdown = True


class _FakeStream:
    def __init__(self, payload=b""):
        self.payload = payload
        self.channel = _FakeChannel()
        self.writes = []
        self.flushed = False

    def write(self, value):
        self.writes.append(value)

    def flush(self):
        self.flushed = True

    def read(self):
        return self.payload


class _FakeParamikoClient:
    def exec_command(self, command, timeout=None, get_pty=False):
        self.command = command
        self.timeout = timeout
        self.get_pty = get_pty
        self.stdin = _FakeStream()
        self.stdout = _FakeStream(b"ok")
        self.stderr = _FakeStream(b"")
        return self.stdin, self.stdout, self.stderr


def test_execute_passes_stdin_and_pty_to_paramiko():
    """Проверяет передачу stdin и PTY в SSH command execution.

    Что делает: подменяет Paramiko client fake-объектом и запускает execute с input_data/get_pty.
    Ожидаемая реакция: команда получает PTY, пароль записывается в stdin, stdin закрывается на запись.
    """
    fake_client = _FakeParamikoClient()
    client = SSHClient(host="127.0.0.1", port=22, username="ops")
    client.client = fake_client

    exit_code, output, error = client.execute(
        "sudo -S -v",
        timeout=3,
        input_data="secret\n",
        get_pty=True,
    )

    assert exit_code == 0
    assert output == "ok"
    assert error == ""
    assert fake_client.command == "sudo -S -v"
    assert fake_client.timeout == 3
    assert fake_client.get_pty is True
    assert fake_client.stdin.writes == ["secret\n"]
    assert fake_client.stdin.flushed is True
    assert fake_client.stdin.channel.write_shutdown is True
