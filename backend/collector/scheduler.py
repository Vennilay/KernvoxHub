import logging
from datetime import datetime, timezone
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.jobstores.base import JobLookupError
from sqlalchemy.orm import Session

from models.database import SessionLocal, ensure_runtime_schema
from models.server import Server
from models.metric import Metric
from collector.ssh_client import SSHClient
from collector.metrics_fetcher import MetricsFetcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
SERVER_JOB_PREFIX = "server_"
SYNC_JOB_ID = "sync_active_servers"


def collect_metrics(server_id: int) -> None:
    """Сбор метрик с одного сервера."""
    db: Session = SessionLocal()
    try:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            logger.warning(f"Server {server_id} not found in database")
            return

        logger.info(f"Collecting metrics from server {server_id} ({server.host})")

        ssh = SSHClient(
            host=server.host,
            port=server.port,
            username=server.username,
            password=server.password,
            ssh_key=server.ssh_key,
        )

        try:
            saved_host_key = server.host_key
            if not ssh.connect(saved_host_key=saved_host_key, timeout=10):
                logger.error(f"Failed to connect to server {server_id}")
                metric = Metric(
                    server_id=server_id,
                    is_available=False,
                    timestamp=datetime.now(timezone.utc),
                )
                db.add(metric)
                db.commit()
                return

            if saved_host_key is None and ssh.discovered_host_key is not None:
                server.host_key = ssh.discovered_host_key
                db.commit()

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
                    timestamp=datetime.now(timezone.utc),
                )
                db.add(metric)
                db.commit()
                logger.info(
                    f"Metrics collected from server {server_id}: "
                    f"CPU={metrics_data.get('cpu_percent')}%"
                )
            else:
                logger.error(f"Failed to fetch metrics from server {server_id}")

        finally:
            ssh.close()

    except Exception as e:
        logger.error(f"Error collecting metrics from server {server_id}: {e}")
        db.rollback()
    finally:
        db.close()


def sync_server_jobs(scheduler: BlockingScheduler, interval: int) -> None:
    db: Session = SessionLocal()
    try:
        servers = db.query(Server).filter(Server.is_active == True).all()
        active_server_ids = {server.id for server in servers}
        existing_server_jobs = {
            job.id: job
            for job in scheduler.get_jobs()
            if job.id.startswith(SERVER_JOB_PREFIX)
        }

        for server in servers:
            job_id = f"{SERVER_JOB_PREFIX}{server.id}"
            if job_id in existing_server_jobs:
                continue

            scheduler.add_job(
                collect_metrics,
                "interval",
                seconds=interval,
                args=[server.id],
                id=job_id,
                name=f"Collect metrics from {server.name}",
                next_run_time=datetime.now(timezone.utc),
                replace_existing=True,
            )
            logger.info(f"Scheduled collection for server {server.name} (ID: {server.id})")

        for job_id in existing_server_jobs:
            server_id = int(job_id.removeprefix(SERVER_JOB_PREFIX))
            if server_id in active_server_ids:
                continue

            try:
                scheduler.remove_job(job_id)
                logger.info(f"Removed collection job for server ID: {server_id}")
            except JobLookupError:
                continue
    finally:
        db.close()


def run_scheduler(interval: int = 60) -> None:
    try:
        ensure_runtime_schema()
        scheduler = BlockingScheduler()
        sync_interval = max(15, min(interval, 60))
        sync_server_jobs(scheduler, interval)
        scheduler.add_job(
            sync_server_jobs,
            "interval",
            seconds=sync_interval,
            args=[scheduler, interval],
            id=SYNC_JOB_ID,
            name="Sync active server jobs",
            replace_existing=True,
        )

        logger.info(f"Scheduler started, collection interval: {interval}s, sync interval: {sync_interval}s")
        scheduler.start()

    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
    except Exception as e:
        logger.error(f"Scheduler error: {e}")


if __name__ == "__main__":
    import os
    interval = int(os.environ.get("COLLECTOR_INTERVAL", 60))
    run_scheduler(interval)
