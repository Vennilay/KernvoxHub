from click.testing import CliRunner
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cli.main as cli_main
from models.database import Base
from models.action_audit import ActionAudit
from models.server import Server
from services.server_actions import ServerActionResult


def test_normalize_ssh_key_text_strips_terminal_artifacts():
    """Проверяет нормализацию вставленного SSH-ключа в CLI.

    Что делает: передаёт строки с bracketed paste escape-последовательностями и мусорным surrogate-символом.
    Ожидаемая реакция: функция возвращает чистый OpenSSH private key с корректными BEGIN/END строками.
    """
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
    """Проверяет интерактивное добавление сервера с ключом из файла.

    Что делает: запускает CLI `add-server`, вводит custom SSH port, пользователя и путь к key-файлу.
    Ожидаемая реакция: команда завершается успешно, сохраняет порт, ключ и не записывает password.
    """
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
    """Проверяет интерактивное добавление сервера со вставленным ключом.

    Что делает: запускает CLI `add-server`, выбирает key-auth и вставляет приватный ключ многострочным вводом.
    Ожидаемая реакция: CLI сохраняет нормализованный ключ, custom port и оставляет password пустым.
    """
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


def test_reboot_server_command_records_audit(monkeypatch):
    """Проверяет CLI-команду reboot без реальной перезагрузки.

    Что делает: подменяет reboot service успешным результатом и запускает `reboot-server <id> --yes`.
    Ожидаемая реакция: CLI пишет audit-запись, сохраняет discovered host key и сообщает об отправленной команде.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(cli_main, "SessionLocal", testing_session)
    monkeypatch.setattr(
        cli_main,
        "run_reboot_server",
        lambda _connection: ServerActionResult(
            status="accepted",
            message="Reboot command accepted by server",
            discovered_host_key="ssh-ed25519 AAAAdiscovered",
        ),
    )

    db = testing_session()
    try:
        server = Server(name="Moscow", host="31.56.211.178", port=2222, username="zeno")
        server.ssh_key = "-----BEGIN OPENSSH PRIVATE KEY-----\ntest-key\n-----END OPENSSH PRIVATE KEY-----\n"
        db.add(server)
        db.commit()
        server_id = server.id
    finally:
        db.close()

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, ["reboot-server", str(server_id), "--yes"])

    assert result.exit_code == 0, result.output
    assert "Команда перезагрузки отправлена" in result.output

    db = testing_session()
    try:
        server = db.query(Server).one()
        audit = db.query(ActionAudit).one()
        assert server.host_key == "ssh-ed25519 AAAAdiscovered"
        assert audit.action == "reboot"
        assert audit.status == "accepted"
        assert audit.requested_by == "cli"
    finally:
        db.close()


def test_setup_reboot_sudo_prompts_one_time_password_for_key_server(monkeypatch):
    """Проверяет настройку reboot sudoers для key-only сервера.

    Что делает: первый вызов сервиса без пароля возвращает failed, CLI спрашивает одноразовый sudo-пароль и повторяет настройку.
    Ожидаемая реакция: команда завершается успешно, пароль не сохраняется в БД, второй вызов получает введённый sudo-пароль.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(cli_main, "SessionLocal", testing_session)

    calls = []

    def fake_configure(_connection, sudo_password=None):
        calls.append(sudo_password)
        if sudo_password is None:
            return ServerActionResult(status="failed", message="sudo password required")
        return ServerActionResult(status="configured", message="configured")

    monkeypatch.setattr(cli_main, "configure_reboot_sudo", fake_configure)

    db = testing_session()
    try:
        server = Server(name="Moscow", host="31.56.211.178", port=2222, username="zeno")
        server.ssh_key = "-----BEGIN OPENSSH PRIVATE KEY-----\ntest-key\n-----END OPENSSH PRIVATE KEY-----\n"
        db.add(server)
        db.commit()
        server_id = server.id
    finally:
        db.close()

    runner = CliRunner()
    result = runner.invoke(
        cli_main.cli,
        ["setup-reboot-sudo", str(server_id), "--yes"],
        input="sudo-secret\n",
    )

    assert result.exit_code == 0, result.output
    assert calls == [None, "sudo-secret"]
    assert "Reboot sudoers настроен" in result.output

    db = testing_session()
    try:
        server = db.query(Server).one()
        assert server.password is None
    finally:
        db.close()
