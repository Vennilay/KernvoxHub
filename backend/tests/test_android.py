import pytest
from fastapi import status
from datetime import datetime, timezone


class TestAndroidDashboard:
    def test_dashboard_empty(self, client, auth_headers):
        response = client.get("/api/v1/android/dashboard", headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_servers"] == 0
        assert data["active_servers"] == 0
        assert data["available_servers"] == 0
        assert data["servers"] == []

    def test_dashboard_with_servers(self, client, db_session, auth_headers):
        from models.server import Server
        from models.metric import Metric

        server1 = Server(name="server1", host="192.168.1.1", username="root")
        server2 = Server(name="server2", host="192.168.1.2", username="root")
        db_session.add_all([server1, server2])
        db_session.commit()

        metric = Metric(
            server_id=server1.id,
            cpu_percent=45.5,
            ram_percent=60.0,
            disk_used_percent=70.0,
            is_available=1
        )
        db_session.add(metric)
        db_session.commit()

        response = client.get("/api/v1/android/dashboard", headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_servers"] == 2
        assert data["active_servers"] == 2
        assert len(data["servers"]) == 2


class TestAndroidServerDetails:
    def test_server_details(self, client, db_session, auth_headers):
        from models.server import Server
        from models.metric import Metric

        server = Server(name="test-server", host="192.168.1.1", username="root")
        db_session.add(server)
        db_session.commit()

        metric = Metric(
            server_id=server.id,
            cpu_percent=45.5,
            ram_used_mb=2048,
            ram_total_mb=4096,
            ram_percent=50.0,
            disk_used_percent=70.0,
            uptime_seconds=3600,
            network_rx_bytes=1000000,
            network_tx_bytes=500000,
            is_available=1
        )
        db_session.add(metric)
        db_session.commit()

        response = client.get(f"/api/v1/android/servers/{server.id}/details", headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == server.id
        assert data["name"] == server.name
        assert data["cpu_percent"] == 45.5
        assert data["uptime_formatted"] is not None

    def test_server_details_not_found(self, client, auth_headers):
        response = client.get("/api/v1/android/servers/999/details", headers=auth_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_server_details_hidden_for_inactive_server(self, client, db_session, auth_headers):
        from models.server import Server

        server = Server(name="test-server", host="192.168.1.1", username="root", is_active=False)
        db_session.add(server)
        db_session.commit()

        response = client.get(f"/api/v1/android/servers/{server.id}/details", headers=auth_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestAndroidMetricsHistory:
    def test_metrics_history(self, client, db_session, auth_headers):
        from models.server import Server
        from models.metric import Metric

        server = Server(name="test-server", host="192.168.1.1", username="root")
        db_session.add(server)
        db_session.commit()

        metric = Metric(
            server_id=server.id,
            cpu_percent=45.5,
            ram_percent=50.0,
            is_available=1
        )
        db_session.add(metric)
        db_session.commit()

        response = client.get(f"/api/v1/android/servers/{server.id}/metrics/history", headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["server_id"] == server.id
        assert data["count"] == 1
        assert len(data["metrics"]) == 1

    def test_metrics_history_limit(self, client, db_session, auth_headers):
        from models.server import Server
        from models.metric import Metric

        server = Server(name="test-server", host="192.168.1.1", username="root")
        db_session.add(server)
        db_session.commit()

        db_session.add_all(
            [
                Metric(server_id=server.id, cpu_percent=10.0, ram_percent=20.0, is_available=1),
                Metric(server_id=server.id, cpu_percent=30.0, ram_percent=40.0, is_available=1),
            ]
        )
        db_session.commit()

        response = client.get(
            f"/api/v1/android/servers/{server.id}/metrics/history?limit=1",
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1
