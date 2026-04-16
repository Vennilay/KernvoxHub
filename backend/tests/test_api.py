import pytest
from fastapi import status


class TestServersAPI:
    def test_get_servers_empty(self, client, auth_headers):
        response = client.get("/api/v1/servers", headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_create_server(self, client, auth_headers):
        server_data = {
            "name": "test-server",
            "host": "192.168.1.100",
            "port": 22,
            "username": "root"
        }
        response = client.post("/api/v1/servers", json=server_data, headers=auth_headers)
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == server_data["name"]
        assert data["host"] == server_data["host"]
        assert "id" in data
        assert data["is_active"] is True

    def test_get_server(self, client, db_session, auth_headers):
        from models.server import Server
        server = Server(
            name="test-server",
            host="192.168.1.100",
            port=22,
            username="root"
        )
        db_session.add(server)
        db_session.commit()

        response = client.get(f"/api/v1/servers/{server.id}", headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == server.id

    def test_get_server_not_found(self, client, auth_headers):
        response = client.get("/api/v1/servers/999", headers=auth_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_server(self, client, db_session, auth_headers):
        from models.server import Server
        server = Server(
            name="test-server",
            host="192.168.1.100",
            port=22,
            username="root"
        )
        db_session.add(server)
        db_session.commit()

        update_data = {"name": "updated-server"}
        response = client.put(f"/api/v1/servers/{server.id}", json=update_data, headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "updated-server"

    def test_delete_server(self, client, db_session, auth_headers):
        from models.server import Server
        server = Server(
            name="test-server",
            host="192.168.1.100",
            port=22,
            username="root"
        )
        db_session.add(server)
        db_session.commit()

        response = client.delete(f"/api/v1/servers/{server.id}", headers=auth_headers)
        assert response.status_code == status.HTTP_204_NO_CONTENT

        response = client.get(f"/api/v1/servers/{server.id}", headers=auth_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_server_resets_host_key_on_endpoint_change(self, client, db_session, auth_headers):
        from models.server import Server

        server = Server(
            name="test-server",
            host="192.168.1.100",
            port=22,
            username="root",
        )
        server.host_key = "ssh-ed25519 AAAAexisting"
        db_session.add(server)
        db_session.commit()

        response = client.put(
            f"/api/v1/servers/{server.id}",
            json={"host": "192.168.1.200"},
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        db_session.refresh(server)
        assert server.host_key is None

    def test_missing_api_key_is_rejected(self, client):
        response = client.get("/api/v1/servers")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestHealthCheck:
    def test_health_check(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_root(self, client):
        response = client.get("/")
        assert response.status_code == status.HTTP_200_OK
        assert "message" in response.json()
