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
