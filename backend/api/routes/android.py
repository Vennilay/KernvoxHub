from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from datetime import datetime, timezone
import logging

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

router = APIRouter(prefix="/api/v1/android", tags=["android"])


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(db: Session = Depends(get_db)) -> DashboardResponse:
    servers = db.query(Server).filter(Server.is_active == True).all()
    
    dashboard_servers = []
    active_count = 0
    available_count = 0
    
    for server in servers:
        active_count += 1
        latest_metric = (
            db.query(Metric)
            .filter(Metric.server_id == server.id)
            .order_by(desc(Metric.timestamp))
            .first()
        )
        
        dashboard_servers.append(DashboardServer(
            id=server.id,
            name=server.name,
            host=server.host,
            is_active=server.is_active,
            is_available=latest_metric.is_available if latest_metric else None,
            cpu_percent=latest_metric.cpu_percent if latest_metric else None,
            ram_percent=latest_metric.ram_percent if latest_metric else None,
            disk_used_percent=latest_metric.disk_used_percent if latest_metric else None,
            last_update=latest_metric.timestamp if latest_metric else None
        ))
        
        if latest_metric and latest_metric.is_available:
            available_count += 1
    
    return DashboardResponse(
        total_servers=len(servers),
        active_servers=active_count,
        available_servers=available_count,
        servers=dashboard_servers,
        timestamp=datetime.now(timezone.utc)
    )


@router.get("/servers/{server_id}/details", response_model=ServerDetails)
def get_server_details(server_id: int, db: Session = Depends(get_db)) -> ServerDetails:
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

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
        last_metric_timestamp=latest_metric.timestamp if latest_metric else None
    )


@router.get("/servers/{server_id}/processes", response_model=ServerProcesses)
def get_server_processes(
    server_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> ServerProcesses:
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    ssh = SSHClient(
        host=server.host,
        port=server.port,
        username=server.username,
        password=server.password,
        ssh_key=server.ssh_key,
    )

    try:
        if not ssh.connect(server=server, db=db, timeout=10):
            raise HTTPException(status_code=503, detail="Cannot connect to server")
    except HostKeyMismatchError as e:
        logging.getLogger(__name__).critical(str(e))
        raise HTTPException(status_code=503, detail="Host key verification failed")

    try:
        fetcher = MetricsFetcher(ssh)
        processes_data = fetcher.get_processes(limit=limit)

        processes = [ProcessInfo(**p) for p in processes_data]

        return ServerProcesses(
            server_id=server_id,
            server_name=server.name,
            processes=processes,
            total_processes=len(processes),
            timestamp=datetime.now(timezone.utc),
        )
    finally:
        ssh.close()


@router.get("/servers/{server_id}/metrics/history", response_model=dict)
def get_metrics_history(
    server_id: int,
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db)
) -> dict:
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
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
                "timestamp": m.timestamp
            }
            for m in metrics
        ]
    }
