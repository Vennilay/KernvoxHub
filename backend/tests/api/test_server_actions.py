from fastapi import status


class TestServerRebootAction:
    def test_reboot_action_records_audit_and_saves_discovered_host_key(
        self,
        client,
        db_session,
        auth_headers,
        action_headers,
        monkeypatch,
    ):
        """Проверяет успешный reboot action без реальной перезагрузки.

        Что делает: подменяет SSH reboot сервис, вызывает `POST /servers/{id}/actions/reboot` с API-ключом и action-key.
        Ожидаемая реакция: API возвращает `202 Accepted`, сохраняет впервые найденный host key и пишет audit-запись со статусом `accepted`.
        """
        from api.routes import actions as actions_route
        from models.action_audit import ActionAudit
        from models.server import Server
        from services.server_actions import ServerActionResult

        server = Server(name="test-server", host="192.168.1.100", username="root")
        db_session.add(server)
        db_session.commit()

        def fake_reboot(connection):
            assert connection.host == server.host
            assert connection.saved_host_key is None
            return ServerActionResult(
                status="accepted",
                message="Reboot command accepted by server",
                discovered_host_key="ssh-ed25519 AAAAdiscovered",
            )

        monkeypatch.setattr(actions_route, "reboot_server", fake_reboot)

        response = client.post(
            f"/api/v1/servers/{server.id}/actions/reboot",
            headers={**auth_headers, **action_headers},
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert data["server_id"] == server.id
        assert data["action"] == "reboot"
        assert data["status"] == "accepted"

        db_session.refresh(server)
        assert server.host_key == "ssh-ed25519 AAAAdiscovered"

        audit = db_session.query(ActionAudit).one()
        assert audit.server_id == server.id
        assert audit.action == "reboot"
        assert audit.status == "accepted"

    def test_reboot_action_requires_action_key_when_configured(
        self,
        client,
        db_session,
        auth_headers,
        action_headers,
        monkeypatch,
    ):
        """Проверяет обязательность `X-Action-Key` для reboot endpoint.

        Что делает: сначала вызывает reboot без action-key, затем повторяет запрос с корректным action-key и подменённым SSH-результатом.
        Ожидаемая реакция: первый запрос получает `403`, второй доходит до сервиса и возвращает ожидаемый `503` от подменённой команды.
        """
        from api.routes import actions as actions_route
        from models.server import Server

        server = Server(name="test-server", host="192.168.1.100", username="root")
        db_session.add(server)
        db_session.commit()

        response = client.post(
            f"/api/v1/servers/{server.id}/actions/reboot",
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

        def fake_reboot(_connection):
            from services.server_actions import ServerActionResult

            return ServerActionResult(status="failed", message="sudo is required")

        monkeypatch.setattr(actions_route, "reboot_server", fake_reboot)
        response = client.post(
            f"/api/v1/servers/{server.id}/actions/reboot",
            headers={**auth_headers, **action_headers},
        )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_reboot_action_fails_closed_when_action_key_is_not_configured(
        self,
        client,
        db_session,
        auth_headers,
        monkeypatch,
    ):
        """Проверяет fail-closed режим destructive endpoints.

        Что делает: временно очищает `SERVER_ACTION_TOKEN` и вызывает reboot endpoint с обычным API-ключом.
        Ожидаемая реакция: API возвращает `503` и не выполняет действие, чтобы пустая конфигурация не открывала reboot.
        """
        from config import settings
        from models.server import Server

        server = Server(name="test-server", host="192.168.1.100", username="root")
        db_session.add(server)
        db_session.commit()
        monkeypatch.setattr(settings, "SERVER_ACTION_TOKEN", "")

        response = client.post(
            f"/api/v1/servers/{server.id}/actions/reboot",
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_reboot_action_returns_503_on_host_key_mismatch(
        self,
        client,
        db_session,
        auth_headers,
        action_headers,
        monkeypatch,
    ):
        """Проверяет реакцию reboot endpoint на несовпадение SSH host key.

        Что делает: подменяет reboot сервис результатом `host_key_mismatch` и вызывает endpoint с корректными ключами.
        Ожидаемая реакция: API возвращает `503 Host key verification failed` и сохраняет audit-запись со статусом `host_key_mismatch`.
        """
        from api.routes import actions as actions_route
        from models.action_audit import ActionAudit
        from models.server import Server
        from services.server_actions import ServerActionResult

        server = Server(name="test-server", host="192.168.1.100", username="root")
        server.host_key = "ssh-ed25519 AAAAexpected"
        db_session.add(server)
        db_session.commit()

        monkeypatch.setattr(
            actions_route,
            "reboot_server",
            lambda _connection: ServerActionResult(
                status="host_key_mismatch",
                message="Host key verification failed",
            ),
        )

        response = client.post(
            f"/api/v1/servers/{server.id}/actions/reboot",
            headers={**auth_headers, **action_headers},
        )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["detail"] == "Host key verification failed"
        assert db_session.query(ActionAudit).one().status == "host_key_mismatch"

    def test_get_server_actions(self, client, db_session, auth_headers):
        """Проверяет выдачу audit history по серверу.

        Что делает: создаёт audit-запись reboot и вызывает `GET /api/v1/servers/{id}/actions`.
        Ожидаемая реакция: API возвращает `200 OK` и список действий, где первая запись содержит action `reboot`.
        """
        from models.action_audit import ActionAudit
        from models.server import Server

        server = Server(name="test-server", host="192.168.1.100", username="root")
        db_session.add(server)
        db_session.commit()
        db_session.add(
            ActionAudit(
                server_id=server.id,
                action="reboot",
                status="accepted",
                requested_by="127.0.0.1",
                message="ok",
            )
        )
        db_session.commit()

        response = client.get(f"/api/v1/servers/{server.id}/actions", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()[0]["action"] == "reboot"
