from fastapi import status
from datetime import datetime, timezone


class TestMetricsAPI:
    def test_metrics_history_requires_limit_and_hides_inactive_servers(self, client, db_session, auth_headers):
        from models.metric import Metric
        from models.server import Server

        server = Server(name="test-server", host="192.168.1.100", username="root", is_active=False)
        db_session.add(server)
        db_session.commit()
        db_session.add(Metric(server_id=server.id, cpu_percent=10.0, ram_percent=20.0, is_available=1))
        db_session.commit()

        response = client.get(f"/api/v1/servers/{server.id}/metrics/history?limit=1", headers=auth_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_metric_uses_path_server_id(self, client, db_session, auth_headers, internal_headers):
        from models.server import Server

        server = Server(name="test-server", host="192.168.1.100", username="root")
        db_session.add(server)
        db_session.commit()

        payload = {
            "cpu_percent": 10.0,
            "ram_used_mb": 100.0,
            "ram_total_mb": 200.0,
            "ram_percent": 50.0,
            "disk_used_percent": 20.0,
            "network_rx_bytes": 1.0,
            "network_tx_bytes": 2.0,
            "uptime_seconds": 3.0,
            "is_available": True,
        }
        response = client.post(
            f"/api/v1/servers/{server.id}/metrics",
            json=payload,
            headers={**auth_headers, **internal_headers},
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["server_id"] == server.id

    def test_current_metrics_prefer_latest_id_when_timestamps_match(self, client, db_session, auth_headers):
        from models.metric import Metric
        from models.server import Server

        server = Server(name="test-server", host="192.168.1.100", username="root")
        db_session.add(server)
        db_session.commit()

        shared_timestamp = datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc)
        db_session.add_all(
            [
                Metric(server_id=server.id, cpu_percent=10.0, ram_percent=20.0, is_available=1, timestamp=shared_timestamp),
                Metric(server_id=server.id, cpu_percent=30.0, ram_percent=40.0, is_available=1, timestamp=shared_timestamp),
            ]
        )
        db_session.commit()

        response = client.get(f"/api/v1/servers/{server.id}/metrics?limit=1", headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()[0]["cpu_percent"] == 30.0
        assert response.json()[0]["ram_percent"] == 40.0

    def test_metrics_timeseries_returns_raw_points_in_ascending_order(self, client, db_session, auth_headers):
        from models.metric import Metric
        from models.server import Server

        server = Server(name="test-server", host="192.168.1.100", username="root")
        db_session.add(server)
        db_session.commit()

        db_session.add_all(
            [
                Metric(
                    server_id=server.id,
                    cpu_percent=40.0,
                    ram_percent=60.0,
                    disk_used_percent=70.0,
                    is_available=1,
                    timestamp=datetime(2026, 4, 17, 12, 5, tzinfo=timezone.utc),
                ),
                Metric(
                    server_id=server.id,
                    cpu_percent=20.0,
                    ram_percent=30.0,
                    disk_used_percent=50.0,
                    is_available=0,
                    timestamp=datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc),
                ),
            ]
        )
        db_session.commit()

        response = client.get(
            f"/api/v1/servers/{server.id}/metrics/timeseries?interval=raw&order=asc",
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["interval"] == "raw"
        assert data["order"] == "asc"
        assert data["point_count"] == 2
        assert data["points"][0]["cpu_percent_avg"] == 20.0
        assert data["points"][0]["availability_ratio"] == 0.0
        assert data["points"][1]["cpu_percent_avg"] == 40.0
        assert data["points"][1]["availability_ratio"] == 1.0

    def test_metrics_timeseries_aggregates_into_buckets(self, client, db_session, auth_headers):
        from models.metric import Metric
        from models.server import Server

        server = Server(name="test-server", host="192.168.1.100", username="root")
        db_session.add(server)
        db_session.commit()

        db_session.add_all(
            [
                Metric(
                    server_id=server.id,
                    cpu_percent=10.0,
                    ram_used_mb=100.0,
                    ram_total_mb=200.0,
                    ram_percent=50.0,
                    disk_used_percent=70.0,
                    network_rx_bytes=1000.0,
                    network_tx_bytes=2000.0,
                    uptime_seconds=300.0,
                    is_available=1,
                    timestamp=datetime(2026, 4, 17, 12, 1, tzinfo=timezone.utc),
                ),
                Metric(
                    server_id=server.id,
                    cpu_percent=30.0,
                    ram_used_mb=120.0,
                    ram_total_mb=200.0,
                    ram_percent=60.0,
                    disk_used_percent=90.0,
                    network_rx_bytes=3000.0,
                    network_tx_bytes=5000.0,
                    uptime_seconds=600.0,
                    is_available=0,
                    timestamp=datetime(2026, 4, 17, 12, 4, tzinfo=timezone.utc),
                ),
            ]
        )
        db_session.commit()

        response = client.get(
            f"/api/v1/servers/{server.id}/metrics/timeseries?interval=5m",
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK

        point = response.json()["points"][0]
        assert point["sample_count"] == 2
        assert point["cpu_percent_avg"] == 20.0
        assert point["cpu_percent_min"] == 10.0
        assert point["cpu_percent_max"] == 30.0
        assert point["ram_used_mb_avg"] == 110.0
        assert point["ram_percent_avg"] == 55.0
        assert point["disk_used_percent_avg"] == 80.0
        assert point["network_rx_bytes_avg"] == 2000.0
        assert point["network_tx_bytes_avg"] == 3500.0
        assert point["uptime_seconds_avg"] == 450.0
        assert point["availability_ratio"] == 0.5
