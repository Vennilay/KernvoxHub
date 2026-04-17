from pydantic import BaseModel, ConfigDict
from typing import List, Optional
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
    pass


class MetricResponse(MetricBase):
    id: int
    server_id: int
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


class MetricsHistoryResponse(BaseModel):
    server_id: int
    server_name: str
    metrics: List[MetricResponse]


class MetricSeriesPoint(BaseModel):
    timestamp: datetime
    bucket_start: datetime
    bucket_end: datetime
    sample_count: int

    cpu_percent_avg: float
    cpu_percent_min: float
    cpu_percent_max: float

    ram_used_mb_avg: float
    ram_total_mb_avg: float
    ram_percent_avg: float
    ram_percent_min: float
    ram_percent_max: float

    disk_used_percent_avg: float
    disk_used_percent_min: float
    disk_used_percent_max: float

    network_rx_bytes_avg: float
    network_tx_bytes_avg: float
    uptime_seconds_avg: float
    availability_ratio: float


class MetricsSeriesResponse(BaseModel):
    server_id: int
    server_name: str
    interval: str
    order: str
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    point_count: int
    points: List[MetricSeriesPoint]
