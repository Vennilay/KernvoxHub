from fastapi import status


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
