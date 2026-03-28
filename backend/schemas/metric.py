from pydantic import BaseModel, ConfigDict
from typing import List
from datetime import datetime


class MetricBase(BaseModel):
    cpu_percent: float = 0.0
    ram_used_mb: float = 0.0
    ram_total_mb: float = 0.0
    ram_percent: float = 0.0
    disk_used_percent: float = 0.0
    network_rx_bytes: float = 0.0
    network_tx_bytes: float = 0.0
    uptime_seconds: float = 0.0
    is_available: bool = True


class MetricCreate(MetricBase):
    server_id: int


class MetricResponse(MetricBase):
    id: int
    server_id: int
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


class MetricsHistoryResponse(BaseModel):
    server_id: int
    server_name: str
    metrics: List[MetricResponse]
