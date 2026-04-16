import click
import re
import sys
from pathlib import Path
from sqlalchemy import text

from models.database import SessionLocal
from models.server import Server
from models.metric import Metric
from services.token_manager import generate_api_token


@click.group()
def cli():
    """CLI-команды проекта."""
    pass


@cli.command()
def generate_token():
    """Выпускает API-токен."""
    try:
        token = generate_api_token()
    except Exception as e:
        click.echo(f"❌ Ошибка выпуска API токена: {e}", err=True)
        sys.exit(1)

    click.echo(f"\n🔑 Новый API токен:\n   {token}\n")
    click.echo("Сохраните его в безопасном месте.\n")


@cli.command()
@click.option("--name", prompt="Имя сервера", help="Имя сервера")
@click.option("--host", prompt="IP адрес или домен", help="IP адрес или домен")
@click.option("--port", prompt="SSH порт", default=22, show_default=True, type=int, help="SSH порт")
@click.option("--username", prompt="SSH пользователь", help="SSH пользователь")
@click.option(
    "--auth-method",
    type=click.Choice(["password", "key"], case_sensitive=False),
    prompt="Тип SSH-аутентификации",
    default="password",
    show_default=True,
    help="Способ SSH-аутентификации",
)
@click.option("--password", hide_input=True, help="SSH пароль")
@click.option("--ssh-key", help="Содержимое приватного SSH-ключа")
@click.option(
    "--ssh-key-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Путь к приватному SSH-ключу",
)
def add_server(name, host, port, username, auth_method, password, ssh_key, ssh_key_file):
    """Добавляет сервер."""
    db = SessionLocal()
    try:
        password, ssh_key = _resolve_ssh_credentials(auth_method, password, ssh_key, ssh_key_file)
        server = Server(
            name=name,
            host=host,
            port=port,
            username=username,
            password=password,
            ssh_key=ssh_key,
        )
        db.add(server)
        db.commit()
        db.refresh(server)
        click.echo(f"\n✅ Сервер '{name}' добавлен с ID: {server.id}\n")
    except Exception as e:
        db.rollback()
        click.echo(f"❌ Ошибка: {e}", err=True)
        sys.exit(1)
    finally:
        db.close()


def _resolve_ssh_credentials(auth_method, password, ssh_key, ssh_key_file):
    """Подготавливает SSH-учётные данные."""
    auth_method = auth_method.lower()

    if auth_method == "password":
        if ssh_key or ssh_key_file is not None:
            raise click.UsageError("Для парольной аутентификации не указывайте SSH-ключ.")
        password = password or click.prompt("SSH пароль", hide_input=True)
        if not password:
            raise click.UsageError("SSH пароль не может быть пустым.")
        return password, None

    if password:
        raise click.UsageError("Для key-аутентификации не указывайте пароль.")
    if ssh_key and ssh_key_file is not None:
        raise click.UsageError("Укажите либо --ssh-key, либо --ssh-key-file.")

    if ssh_key_file is None and not ssh_key:
        ssh_key = _prompt_for_ssh_key()

    if ssh_key_file is not None:
        ssh_key = ssh_key_file.read_text(encoding="utf-8")

    if not ssh_key or not ssh_key.strip():
        raise click.UsageError("SSH-ключ не может быть пустым.")

    return None, ssh_key


def _prompt_for_ssh_key():
    """Запрашивает SSH-ключ."""
    while True:
        key_path = click.prompt(
            "Путь к приватному SSH-ключу (оставьте пустым для вставки)",
            default="",
            show_default=False,
        ).strip()
        if not key_path:
            return _read_multiline_ssh_key()

        path = Path(key_path)
        if path.is_file():
            return path.read_text(encoding="utf-8")

        click.echo("Файл недоступен внутри контейнера. Оставьте поле пустым и вставьте ключ напрямую.")


def _read_multiline_ssh_key():
    """Читает приватный SSH-ключ из stdin."""
    click.echo("Вставьте приватный SSH-ключ целиком и завершите ввод пустой строкой.")
    lines = []

    while True:
        line = _read_stdin_line()
        if not line:
            break
        if line.strip() == "":
            break
        lines.append(line)

    return _normalize_ssh_key_text(lines)


def _read_stdin_line():
    """Читает строку stdin."""
    raw_line = sys.stdin.readline()
    if not raw_line:
        return ""
    return raw_line.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="ignore").rstrip("\r\n")


def _normalize_ssh_key_text(lines):
    """Нормализует текст SSH-ключа."""
    text = "\n".join(lines).replace("\r", "")
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)

    normalized_lines = [line.strip() for line in text.splitlines() if line.strip()]
    begin_index = next((index for index, line in enumerate(normalized_lines) if line.startswith("-----BEGIN ")), None)

    if begin_index is not None:
        end_index = next(
            (index for index in range(begin_index, len(normalized_lines)) if normalized_lines[index].startswith("-----END ")),
            None,
        )
        if end_index is not None:
            normalized_lines = normalized_lines[begin_index:end_index + 1]

    return "\n".join(normalized_lines).strip() + "\n" if normalized_lines else ""


@cli.command()
@click.option("--limit", default=10, help="Количество серверов")
def list_servers(limit):
    """Показывает список серверов."""
    db = SessionLocal()
    try:
        servers = db.query(Server).limit(limit).all()
        if not servers:
            click.echo("\n⚠️  Серверов нет\n")
            return

        click.echo(f"\n📊 Серверы ({len(servers)}):")
        click.echo("-" * 60)
        for server in servers:
            status = "🟢" if server.is_active else "🔴"
            click.echo(f"{status} ID:{server.id} | {server.name} | {server.host}:{server.port}")
        click.echo()
    finally:
        db.close()


@cli.command()
@click.argument("server_id", type=int)
def delete_server(server_id):
    """Деактивирует сервер."""
    db = SessionLocal()
    try:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            click.echo(f"\n❌ Сервер с ID {server_id} не найден\n")
            sys.exit(1)

        server.is_active = False
        db.commit()
        click.echo(f"\n✅ Сервер '{server.name}' удалён (деактивирован)\n")
    except Exception as e:
        db.rollback()
        click.echo(f"❌ Ошибка: {e}", err=True)
        sys.exit(1)
    finally:
        db.close()


@cli.command()
def status():
    """Показывает статус системы."""
    db = SessionLocal()
    try:
        total_servers = db.query(Server).count()
        active_servers = db.query(Server).filter(Server.is_active == True).count()
        total_metrics = db.query(Metric).count()

        click.echo("\n📊 KernvoxHub Статус")
        click.echo("=" * 40)
        click.echo(f"🖥  Всего серверов: {total_servers}")
        click.echo(f"🟢 Активных серверов: {active_servers}")
        click.echo(f"📈 Всего метрик: {total_metrics}")

        result = db.execute(text("SELECT version()")).scalar()
        click.echo(f"🗄️  PostgreSQL: {result[:50]}...")

        click.echo()
    except Exception as e:
        click.echo(f"❌ Ошибка: {e}", err=True)
        sys.exit(1)
    finally:
        db.close()


@cli.command()
@click.argument("server_id", type=int)
@click.option("--limit", default=1, help="Количество последних метрик")
def metrics(server_id, limit):
    """Показывает последние метрики."""
    db = SessionLocal()
    try:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            click.echo(f"\n❌ Сервер с ID {server_id} не найден\n")
            sys.exit(1)

        metrics = (
            db.query(Metric)
            .filter(Metric.server_id == server_id)
            .order_by(Metric.timestamp.desc())
            .limit(limit)
            .all()
        )

        if not metrics:
            click.echo(f"\n⚠️  Нет метрик для сервера '{server.name}'\n")
            return

        click.echo(f"\n📈 Метрики сервера '{server.name}' (ID: {server_id}):")
        click.echo("=" * 60)
        for metric in metrics:
            status = "🟢" if metric.is_available else "🔴"
            click.echo(f"{status} {metric.timestamp}")
            click.echo(f"   CPU: {metric.cpu_percent:.1f}%")
            click.echo(f"   RAM: {metric.ram_used_mb:.0f}MB / {metric.ram_total_mb:.0f}MB ({metric.ram_percent:.1f}%)")
            click.echo(f"   Disk: {metric.disk_used_percent:.1f}%")
            click.echo(f"   Network: RX {metric.network_rx_bytes:.0f} | TX {metric.network_tx_bytes:.0f}")
            click.echo()
    finally:
        db.close()


if __name__ == "__main__":
    cli()
