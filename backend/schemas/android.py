from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class ProcessInfo(BaseModel):
    pid: int
    user: str
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    command: str


class ServerProcesses(BaseModel):
    server_id: int
    server_name: str
    processes: List[ProcessInfo]
    total_processes: int
    timestamp: datetime


class ServerDetails(BaseModel):
    id: int
    name: str
    host: str
    port: int
    username: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    cpu_cores: Optional[int] = None
    uptime_seconds: Optional[float] = None
    uptime_formatted: Optional[str] = None
    network_rx_bytes: Optional[float] = None
    network_tx_bytes: Optional[float] = None
    cpu_percent: Optional[float] = None
    ram_used_mb: Optional[float] = None
    ram_total_mb: Optional[float] = None
    ram_percent: Optional[float] = None
    disk_used_percent: Optional[float] = None
    is_available: Optional[bool] = None
    last_metric_timestamp: Optional[datetime] = None


class DashboardServer(BaseModel):
    id: int
    name: str
    host: str
    is_active: bool
    is_available: Optional[bool] = None
    cpu_percent: Optional[float] = None
    ram_percent: Optional[float] = None
    disk_used_percent: Optional[float] = None
    last_update: Optional[datetime] = None


class DashboardResponse(BaseModel):
    total_servers: int
    active_servers: int
    available_servers: int
    servers: List[DashboardServer]
    timestamp: datetime
