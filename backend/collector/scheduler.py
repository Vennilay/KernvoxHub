import logging
from datetime import datetime, timezone
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.orm import Session

from models.database import SessionLocal
from models.server import Server
from models.metric import Metric
from collector.ssh_client import SSHClient
from collector.metrics_fetcher import MetricsFetcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def collect_metrics(server_id: int, host: str, port: int, username: str,
                    password: str = None, ssh_key: str = None) -> None:
    db: Session = SessionLocal()
    try:
        logger.info(f"Collecting metrics from server {server_id} ({host})")

        with SSHClient(host, port, username, password, ssh_key) as ssh:
            if not ssh.client:
                logger.error(f"Failed to connect to server {server_id}")
                metric = Metric(
                    server_id=server_id,
                    is_available=False,
                    timestamp=datetime.now(timezone.utc)
                )
                db.add(metric)
                db.commit()
                return

            fetcher = MetricsFetcher(ssh)
            metrics_data = fetcher.fetch_all()

            if metrics_data:
                metric = Metric(
                    server_id=server_id,
                    cpu_percent=metrics_data.get("cpu_percent", 0.0),
                    ram_used_mb=metrics_data.get("ram_used_mb", 0.0),
                    ram_total_mb=metrics_data.get("ram_total_mb", 0.0),
                    ram_percent=metrics_data.get("ram_percent", 0.0),
                    disk_used_percent=metrics_data.get("disk_used_percent", 0.0),
                    network_rx_bytes=metrics_data.get("network_rx_bytes", 0.0),
                    network_tx_bytes=metrics_data.get("network_tx_bytes", 0.0),
                    uptime_seconds=metrics_data.get("uptime_seconds", 0.0),
                    is_available=metrics_data.get("is_available", True),
                    timestamp=datetime.now(timezone.utc)
                )
                db.add(metric)
                db.commit()
                logger.info(f"Metrics collected from server {server_id}: CPU={metrics_data.get('cpu_percent')}%")
            else:
                logger.error(f"Failed to fetch metrics from server {server_id}")

    except Exception as e:
        logger.error(f"Error collecting metrics from server {server_id}: {e}")
        db.rollback()
    finally:
        db.close()


def run_scheduler(interval: int = 60) -> None:
    db: Session = SessionLocal()
    try:
        servers = db.query(Server).filter(Server.is_active == True).all()
        logger.info(f"Found {len(servers)} active servers")

        scheduler = BlockingScheduler()

        for server in servers:
            scheduler.add_job(
                collect_metrics,
                'interval',
                seconds=interval,
                args=[server.id, server.host, server.port, server.username,
                      server.password, server.ssh_key],
                id=f"server_{server.id}",
                name=f"Collect metrics from {server.name}",
                next_run_time=datetime.now(timezone.utc)
            )
            logger.info(f"Scheduled collection for server {server.name} (ID: {server.id})")

        logger.info(f"Scheduler started with {len(servers)} servers, interval: {interval}s")
        scheduler.start()

    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
    except Exception as e:
        logger.error(f"Scheduler error: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    import os
    interval = int(os.environ.get("COLLECTOR_INTERVAL", 60))
    run_scheduler(interval)
