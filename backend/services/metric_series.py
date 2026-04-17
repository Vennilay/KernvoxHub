from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from models.metric import Metric
from schemas.metric import MetricSeriesPoint, MetricsSeriesResponse


SERIES_INTERVAL_SECONDS = {
    "raw": 0,
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "6h": 21600,
    "1d": 86400,
}


def normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass
class _BucketAccumulator:
    bucket_start: datetime
    bucket_end: datetime
    sample_count: int = 0
    cpu_percent_sum: float = 0.0
    cpu_percent_min: float = float("inf")
    cpu_percent_max: float = float("-inf")
    ram_used_mb_sum: float = 0.0
    ram_total_mb_sum: float = 0.0
    ram_percent_sum: float = 0.0
    ram_percent_min: float = float("inf")
    ram_percent_max: float = float("-inf")
    disk_used_percent_sum: float = 0.0
    disk_used_percent_min: float = float("inf")
    disk_used_percent_max: float = float("-inf")
    network_rx_bytes_sum: float = 0.0
    network_tx_bytes_sum: float = 0.0
    uptime_seconds_sum: float = 0.0
    available_count: int = 0

    def add(self, metric: Metric) -> None:
        self.sample_count += 1

        self.cpu_percent_sum += metric.cpu_percent
        self.cpu_percent_min = min(self.cpu_percent_min, metric.cpu_percent)
        self.cpu_percent_max = max(self.cpu_percent_max, metric.cpu_percent)

        self.ram_used_mb_sum += metric.ram_used_mb
        self.ram_total_mb_sum += metric.ram_total_mb
        self.ram_percent_sum += metric.ram_percent
        self.ram_percent_min = min(self.ram_percent_min, metric.ram_percent)
        self.ram_percent_max = max(self.ram_percent_max, metric.ram_percent)

        self.disk_used_percent_sum += metric.disk_used_percent
        self.disk_used_percent_min = min(self.disk_used_percent_min, metric.disk_used_percent)
        self.disk_used_percent_max = max(self.disk_used_percent_max, metric.disk_used_percent)

        self.network_rx_bytes_sum += metric.network_rx_bytes
        self.network_tx_bytes_sum += metric.network_tx_bytes
        self.uptime_seconds_sum += metric.uptime_seconds

        if metric.is_available:
            self.available_count += 1

    def to_point(self) -> MetricSeriesPoint:
        count = float(self.sample_count)
        return MetricSeriesPoint(
            timestamp=self.bucket_start,
            bucket_start=self.bucket_start,
            bucket_end=self.bucket_end,
            sample_count=self.sample_count,
            cpu_percent_avg=self.cpu_percent_sum / count,
            cpu_percent_min=self.cpu_percent_min,
            cpu_percent_max=self.cpu_percent_max,
            ram_used_mb_avg=self.ram_used_mb_sum / count,
            ram_total_mb_avg=self.ram_total_mb_sum / count,
            ram_percent_avg=self.ram_percent_sum / count,
            ram_percent_min=self.ram_percent_min,
            ram_percent_max=self.ram_percent_max,
            disk_used_percent_avg=self.disk_used_percent_sum / count,
            disk_used_percent_min=self.disk_used_percent_min,
            disk_used_percent_max=self.disk_used_percent_max,
            network_rx_bytes_avg=self.network_rx_bytes_sum / count,
            network_tx_bytes_avg=self.network_tx_bytes_sum / count,
            uptime_seconds_avg=self.uptime_seconds_sum / count,
            availability_ratio=self.available_count / count,
        )


def _bucket_start(timestamp: datetime, interval_seconds: int) -> datetime:
    epoch_seconds = int(timestamp.timestamp())
    floored_seconds = epoch_seconds - (epoch_seconds % interval_seconds)
    return datetime.fromtimestamp(floored_seconds, tz=timezone.utc)


def build_metrics_series_response(
    *,
    server_id: int,
    server_name: str,
    metrics: Iterable[Metric],
    interval: str,
    order: str,
    from_date: datetime | None,
    to_date: datetime | None,
    limit: int,
) -> MetricsSeriesResponse:
    interval_seconds = SERIES_INTERVAL_SECONDS[interval]
    normalized_metrics = sorted(
        metrics,
        key=lambda item: (normalize_timestamp(item.timestamp), item.id),
    )

    if interval_seconds == 0:
        points = []
        for metric in normalized_metrics:
            timestamp = normalize_timestamp(metric.timestamp)
            accumulator = _BucketAccumulator(bucket_start=timestamp, bucket_end=timestamp)
            accumulator.add(metric)
            points.append(accumulator.to_point())
    else:
        buckets: dict[datetime, _BucketAccumulator] = {}
        for metric in normalized_metrics:
            timestamp = normalize_timestamp(metric.timestamp)
            start = _bucket_start(timestamp, interval_seconds)
            accumulator = buckets.setdefault(
                start,
                _BucketAccumulator(
                    bucket_start=start,
                    bucket_end=start + timedelta(seconds=interval_seconds),
                ),
            )
            accumulator.add(metric)

        points = [buckets[key].to_point() for key in sorted(buckets)]

    if order == "desc":
        points.reverse()

    points = points[:limit]

    return MetricsSeriesResponse(
        server_id=server_id,
        server_name=server_name,
        interval=interval,
        order=order,
        from_date=from_date,
        to_date=to_date,
        point_count=len(points),
        points=points,
    )
