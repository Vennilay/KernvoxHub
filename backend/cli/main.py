import click
import sys
from sqlalchemy import text

from models.database import SessionLocal, engine
from models.server import Server
from models.metric import Metric
from services.token_manager import generate_api_token


@click.group()
def cli():
    """KernvoxHub CLI утилиты"""
    pass


@cli.command()
def generate_token():
    """Генерация нового API токена"""
    token = generate_api_token()
    click.echo(f"\n🔑 Ваш API токен:\n   {token}\n")
    click.echo("Сохраните его в безопасном месте!\n")


@cli.command()
@click.option("--name", prompt="Имя сервера", help="Имя сервера")
@click.option("--host", prompt="IP адрес или домен", help="IP адрес или домен")
@click.option("--port", default=22, help="SSH порт")
@click.option("--username", prompt="SSH пользователь", help="SSH пользователь")
@click.option("--password", prompt="SSH пароль", hide_input=True, help="SSH пароль")
def add_server(name, host, port, username, password):
    """Добавление нового сервера"""
    db = SessionLocal()
    try:
        server = Server(
            name=name,
            host=host,
            port=port,
            username=username,
            password=password
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


@cli.command()
@click.option("--limit", default=10, help="Количество серверов")
def list_servers(limit):
    """Список серверов"""
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
    """Удаление сервера по ID"""
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
    """Статус системы"""
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
    """Последние метрики сервера"""
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
