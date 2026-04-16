from click.testing import CliRunner
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cli.main as cli_main
from models.database import Base
from models.server import Server


def test_normalize_ssh_key_text_strips_terminal_artifacts():
    result = cli_main._normalize_ssh_key_text(
        [
            "\x1b[200~",
            "-----BEGIN OPENSSH PRIVATE KEY-----",
            "test-key",
            "-----END OPENSSH PRIVATE KEY-----",
            "\udcd1",
            "\x1b[201~",
        ]
    )

    assert result == "-----BEGIN OPENSSH PRIVATE KEY-----\ntest-key\n-----END OPENSSH PRIVATE KEY-----\n"


def test_add_server_interactive_supports_custom_port_and_ssh_key(tmp_path, monkeypatch):
    key_path = tmp_path / "id_ed25519"
    key_value = "-----BEGIN OPENSSH PRIVATE KEY-----\ntest-key\n-----END OPENSSH PRIVATE KEY-----\n"
    key_path.write_text(key_value, encoding="utf-8")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(cli_main, "SessionLocal", testing_session)

    runner = CliRunner()
    result = runner.invoke(
        cli_main.cli,
        ["add-server"],
        input=f"Moscow\n31.56.211.178\n2222\nzeno\nkey\n{key_path}\n",
    )

    assert result.exit_code == 0, result.output
    assert "SSH порт" in result.output
    assert "Тип SSH-аутентификации" in result.output

    db = testing_session()
    try:
        server = db.query(Server).one()
        assert server.port == 2222
        assert server.password is None
        assert server.ssh_key == key_value
    finally:
        db.close()


def test_add_server_interactive_supports_pasted_ssh_key(monkeypatch):
    key_value = "-----BEGIN OPENSSH PRIVATE KEY-----\ntest-key\n-----END OPENSSH PRIVATE KEY-----\n"

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(cli_main, "SessionLocal", testing_session)

    runner = CliRunner()
    result = runner.invoke(
        cli_main.cli,
        ["add-server"],
        input="Moscow\n31.56.211.178\n49152\nzeno\nkey\n\n-----BEGIN OPENSSH PRIVATE KEY-----\ntest-key\n-----END OPENSSH PRIVATE KEY-----\n\n",
    )

    assert result.exit_code == 0, result.output
    assert "Вставьте приватный SSH-ключ" in result.output

    db = testing_session()
    try:
        server = db.query(Server).one()
        assert server.port == 49152
        assert server.password is None
        assert server.ssh_key == key_value
    finally:
        db.close()
