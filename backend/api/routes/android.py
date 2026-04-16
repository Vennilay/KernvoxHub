from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func
from typing import Optional
from datetime import datetime, timezone
import logging
import asyncio

from api.routes.common import get_server_or_404
from models.database import get_db
from models.server import Server
from models.metric import Metric
from schemas.android import (
    DashboardResponse,
    DashboardServer,
    ServerDetails,
    ServerProcesses,
    ProcessInfo
)
from collector.ssh_client import SSHClient, HostKeyMismatchError
from collector.metrics_fetcher import MetricsFetcher

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/android", tags=["android"])


def _connect_and_fetch(
    host: str, port: int, username: str, password: Optional[str],
    ssh_key: Optional[str], saved_host_key: Optional[str], limit: int,
):
    """Синхронная функция для запуска в executor (блокирующий SSH)."""
    ssh = SSHClient(
        host=host, port=port, username=username,
        password=password, ssh_key=ssh_key,
    )

    try:
        if not ssh.connect(saved_host_key=saved_host_key, timeout=10):
            return None, "connect_failed", None, None

        fetcher = MetricsFetcher(ssh)
        processes = fetcher.get_processes(limit=limit)
        return processes, "ok", None, ssh.discovered_host_key

    except HostKeyMismatchError as e:
        logger.critical(str(e))
        return None, "host_key_mismatch", str(e), None
    except Exception as e:
        logger.error(f"SSH error in /processes: {e}")
        return None, "error", str(e), None
    finally:
        ssh.close()


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(db: Session = Depends(get_db)) -> DashboardResponse:
    servers = db.query(Server).filter(Server.is_active == True).all()
    latest_timestamp_subquery = (
        db.query(
            Metric.server_id.label("server_id"),
            func.max(Metric.timestamp).label("latest_timestamp"),
        )
        .group_by(Metric.server_id)
        .subquery()
    )
    latest_metrics = (
        db.query(Metric)
        .join(
            latest_timestamp_subquery,
            and_(
                Metric.server_id == latest_timestamp_subquery.c.server_id,
                Metric.timestamp == latest_timestamp_subquery.c.latest_timestamp,
            ),
        )
        .all()
    )
    latest_metrics_by_server = {metric.server_id: metric for metric in latest_metrics}

    dashboard_servers = []
    available_count = 0

    for server in servers:
        latest_metric = latest_metrics_by_server.get(server.id)

        dashboard_servers.append(DashboardServer(
            id=server.id,
            name=server.name,
            host=server.host,
            is_active=server.is_active,
            is_available=latest_metric.is_available if latest_metric else None,
            cpu_percent=latest_metric.cpu_percent if latest_metric else None,
            ram_percent=latest_metric.ram_percent if latest_metric else None,
            disk_used_percent=latest_metric.disk_used_percent if latest_metric else None,
            last_update=latest_metric.timestamp if latest_metric else None,
        ))

        if latest_metric and latest_metric.is_available:
            available_count += 1

    return DashboardResponse(
        total_servers=len(servers),
        active_servers=len(servers),
        available_servers=available_count,
        servers=dashboard_servers,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/servers/{server_id}/details", response_model=ServerDetails)
def get_server_details(server_id: int, db: Session = Depends(get_db)) -> ServerDetails:
    server = get_server_or_404(db, server_id, active_only=True)

    latest_metric = (
        db.query(Metric)
        .filter(Metric.server_id == server_id)
        .order_by(desc(Metric.timestamp))
        .first()
    )

    uptime_formatted = None
    if latest_metric and latest_metric.uptime_seconds:
        total_seconds = int(latest_metric.uptime_seconds)
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        uptime_formatted = f"{days}d {hours}h {minutes}m"

    return ServerDetails(
        id=server.id,
        name=server.name,
        host=server.host,
        port=server.port,
        username=server.username,
        is_active=server.is_active,
        created_at=server.created_at,
        updated_at=server.updated_at,
        cpu_cores=None,
        uptime_seconds=latest_metric.uptime_seconds if latest_metric else None,
        uptime_formatted=uptime_formatted,
        network_rx_bytes=latest_metric.network_rx_bytes if latest_metric else None,
        network_tx_bytes=latest_metric.network_tx_bytes if latest_metric else None,
        cpu_percent=latest_metric.cpu_percent if latest_metric else None,
        ram_used_mb=latest_metric.ram_used_mb if latest_metric else None,
        ram_total_mb=latest_metric.ram_total_mb if latest_metric else None,
        ram_percent=latest_metric.ram_percent if latest_metric else None,
        disk_used_percent=latest_metric.disk_used_percent if latest_metric else None,
        is_available=latest_metric.is_available if latest_metric else None,
        last_metric_timestamp=latest_metric.timestamp if latest_metric else None,
    )


@router.get("/servers/{server_id}/processes", response_model=ServerProcesses)
async def get_server_processes(
    server_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> ServerProcesses:
    server = get_server_or_404(db, server_id, active_only=True)

    saved_host_key = server.host_key
    processes, status, error, discovered_host_key = await asyncio.to_thread(
        _connect_and_fetch,
        server.host, server.port, server.username,
        server.password, server.ssh_key,
        saved_host_key, limit,
    )

    if saved_host_key is None and discovered_host_key is not None:
        server.host_key = discovered_host_key
        db.commit()

    if status == "connect_failed":
        raise HTTPException(status_code=503, detail="Cannot connect to server")
    if status == "host_key_mismatch":
        raise HTTPException(
            status_code=503,
            detail="Host key verification failed",
        )
    if status == "error":
        raise HTTPException(status_code=503, detail=f"SSH error: {error}")
    if processes is None:
        raise HTTPException(status_code=503, detail="Cannot connect to server")

    process_infos = [ProcessInfo(**p) for p in processes]

    return ServerProcesses(
        server_id=server_id,
        server_name=server.name,
        processes=process_infos,
        total_processes=len(process_infos),
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/servers/{server_id}/metrics/history", response_model=dict)
def get_metrics_history(
    server_id: int,
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    server = get_server_or_404(db, server_id, active_only=True)

    query = db.query(Metric).filter(Metric.server_id == server_id)

    if from_date:
        query = query.filter(Metric.timestamp >= from_date)
    if to_date:
        query = query.filter(Metric.timestamp <= to_date)

    metrics = query.order_by(desc(Metric.timestamp)).limit(limit).all()

    return {
        "server_id": server_id,
        "server_name": server.name,
        "count": len(metrics),
        "metrics": [
            {
                "id": m.id,
                "cpu_percent": m.cpu_percent,
                "ram_used_mb": m.ram_used_mb,
                "ram_total_mb": m.ram_total_mb,
                "ram_percent": m.ram_percent,
                "disk_used_percent": m.disk_used_percent,
                "network_rx_bytes": m.network_rx_bytes,
                "network_tx_bytes": m.network_tx_bytes,
                "uptime_seconds": m.uptime_seconds,
                "is_available": bool(m.is_available),
                "timestamp": m.timestamp,
            }
            for m in metrics
        ],
    }
