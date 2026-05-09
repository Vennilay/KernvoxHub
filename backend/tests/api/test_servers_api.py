import pytest
from fastapi import status


class TestServersAPI:
    def test_get_servers_empty(self, client, auth_headers):
        """Проверяет пустой список серверов.

        Что делает: вызывает `GET /api/v1/servers` с валидным API-ключом на чистой тестовой базе.
        Ожидаемая реакция: API возвращает `200 OK` и пустой JSON-массив, без фиктивных или неактивных записей.
        """
        response = client.get("/api/v1/servers", headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_create_server(self, client, auth_headers):
        """Проверяет создание сервера через публичный API.

        Что делает: отправляет `POST /api/v1/servers` с минимальными SSH-данными и паролем.
        Ожидаемая реакция: API возвращает `201 Created`, присваивает `id`, сохраняет `is_active=True` и не искажает name/host.
        """
        server_data = {
            "name": "test-server",
            "host": "192.168.1.100",
            "port": 22,
            "username": "root",
            "password": "secret123",
        }
        response = client.post("/api/v1/servers", json=server_data, headers=auth_headers)
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == server_data["name"]
        assert data["host"] == server_data["host"]
        assert "id" in data
        assert data["is_active"] is True

    def test_create_server_requires_credentials(self, client, auth_headers):
        """Проверяет запрет сервера без SSH-учётных данных.

        Что делает: отправляет `POST /api/v1/servers` без `password` и `ssh_key`.
        Ожидаемая реакция: FastAPI/Pydantic возвращает `422`, чтобы collector не получил бесполезную запись без способа подключения.
        """
        response = client.post(
            "/api/v1/servers",
            json={
                "name": "test-server",
                "host": "192.168.1.100",
                "port": 22,
                "username": "root",
            },
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_create_server_rejects_multiple_credentials(self, client, auth_headers):
        """Проверяет запрет неоднозначной SSH-аутентификации при создании.

        Что делает: отправляет `POST /api/v1/servers` одновременно с `password` и `ssh_key`.
        Ожидаемая реакция: API возвращает `422`, потому что сервер должен иметь ровно один активный способ SSH-входа.
        """
        response = client.post(
            "/api/v1/servers",
            json={
                "name": "test-server",
                "host": "192.168.1.100",
                "port": 22,
                "username": "root",
                "password": "secret123",
                "ssh_key": "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
            },
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_get_server(self, client, db_session, auth_headers):
        """Проверяет получение активного сервера по id.

        Что делает: создаёт сервер напрямую в БД и вызывает `GET /api/v1/servers/{id}`.
        Ожидаемая реакция: API возвращает `200 OK` и тот же `id`, подтверждая корректную фильтрацию и сериализацию модели.
        """
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
        """Проверяет ответ на неизвестный id сервера.

        Что делает: вызывает `GET /api/v1/servers/999` без соответствующей записи в БД.
        Ожидаемая реакция: API возвращает `404 Not Found`, чтобы клиент не получил пустой или ошибочный объект.
        """
        response = client.get("/api/v1/servers/999", headers=auth_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_server(self, client, db_session, auth_headers):
        """Проверяет базовое обновление полей сервера.

        Что делает: создаёт сервер и отправляет `PUT /api/v1/servers/{id}` с новым именем.
        Ожидаемая реакция: API возвращает `200 OK`, а в ответе появляется обновлённое имя без изменения остальных обязательных полей.
        """
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

    def test_update_server_rejects_multiple_credentials(self, client, db_session, auth_headers):
        """Проверяет запрет двух SSH credential при обновлении.

        Что делает: пытается обновить сервер, передав одновременно новый `password` и новый `ssh_key`.
        Ожидаемая реакция: API возвращает `422`, не переводя сервер в неоднозначное состояние подключения.
        """
        from models.server import Server

        server = Server(
            name="test-server",
            host="192.168.1.100",
            port=22,
            username="root",
            password="old-password",
        )
        db_session.add(server)
        db_session.commit()

        response = client.put(
            f"/api/v1/servers/{server.id}",
            json={
                "password": "new-password",
                "ssh_key": "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_update_server_switches_credentials_exclusively(self, client, db_session, auth_headers):
        """Проверяет безопасную смену способа SSH-аутентификации.

        Что делает: у сервера с паролем задаёт новый `ssh_key` через `PUT /api/v1/servers/{id}`.
        Ожидаемая реакция: API возвращает `200 OK`, сохраняет новый ключ и очищает старый пароль из записи.
        """
        from models.server import Server

        server = Server(
            name="test-server",
            host="192.168.1.100",
            port=22,
            username="root",
            password="old-password",
        )
        db_session.add(server)
        db_session.commit()

        key = "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----"
        response = client.put(
            f"/api/v1/servers/{server.id}",
            json={"ssh_key": key},
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        db_session.refresh(server)
        assert server.password is None
        assert server.ssh_key == key

    def test_delete_server(self, client, db_session, auth_headers):
        """Проверяет мягкое удаление сервера.

        Что делает: вызывает `DELETE /api/v1/servers/{id}`, затем повторно запрашивает этот сервер.
        Ожидаемая реакция: удаление возвращает `204`, а последующий `GET` возвращает `404`, потому что запись стала неактивной.
        """
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
        """Проверяет сброс SSH host key при смене адреса сервера.

        Что делает: создаёт сервер с сохранённым host key и меняет `host` через `PUT`.
        Ожидаемая реакция: API возвращает `200 OK`, а сохранённый host key очищается, чтобы не доверять ключу от старого endpoint.
        """
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
        """Проверяет обязательность `X-API-Key` для закрытых endpoints.

        Что делает: вызывает `GET /api/v1/servers` без заголовка авторизации.
        Ожидаемая реакция: middleware возвращает `401 Unauthorized`, не пропуская запрос в бизнес-логику.
        """
        response = client.get("/api/v1/servers")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_auth_middleware_tolerates_redis_rate_limit_failure(self, client, auth_headers, monkeypatch):
        """Проверяет отказоустойчивость auth middleware при сбое Redis на чтении rate limit.

        Что делает: подменяет Redis-клиент объектом, который падает на `get`, и отправляет запрос с валидным API-ключом.
        Ожидаемая реакция: API возвращает `200 OK`; Redis-сбой логируется, но не превращает валидный запрос в `500`.
        """
        from api.middleware import auth as auth_middleware

        class FailingRedis:
            def get(self, _key):
                raise RuntimeError("redis unavailable")

        monkeypatch.setattr(auth_middleware, "redis_client", FailingRedis())

        response = client.get("/api/v1/servers", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK

    def test_auth_middleware_tolerates_redis_attempt_record_failure(self, client, monkeypatch):
        """Проверяет отказоустойчивость записи неудачной auth-попытки.

        Что делает: подменяет Redis pipeline объектом, падающим на `execute`, и отправляет запрос без API-ключа.
        Ожидаемая реакция: middleware возвращает `401 Unauthorized`, а сбой Redis не маскирует auth-ошибку как `500`.
        """
        from api.middleware import auth as auth_middleware

        class FailingPipeline:
            def incr(self, _key):
                return self

            def expire(self, _key, _ttl):
                return self

            def execute(self):
                raise RuntimeError("redis unavailable")

        class FailingRedis:
            def get(self, _key):
                return None

            def pipeline(self):
                return FailingPipeline()

        monkeypatch.setattr(auth_middleware, "redis_client", FailingRedis())

        response = client.get("/api/v1/servers")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestHealthCheck:
    def test_health_check_accepts_loopback_probe_without_api_key(self, client):
        """Проверяет локальный health probe без API-ключа.

        Что делает: вызывает `GET /api/v1/health` с `X-Real-IP: 127.0.0.1`, как это делают локальные health checks.
        Ожидаемая реакция: endpoint возвращает `200 OK`, `status=ok` и версию без раскрытия health наружу всему интернету.
        """
        response = client.get("/api/v1/health", headers={"X-Real-IP": "127.0.0.1"})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_check_requires_api_key_for_non_loopback_client(self, client):
        """Проверяет, что внешний health endpoint закрыт API-ключом.

        Что делает: вызывает `GET /api/v1/health` с внешним `X-Real-IP` и без `X-API-Key`.
        Ожидаемая реакция: middleware возвращает `401 Unauthorized`, чтобы health не был публичной fingerprint-точкой.
        """
        response = client.get("/api/v1/health", headers={"X-Real-IP": "203.0.113.10"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_health_check_accepts_api_key_for_non_loopback_client(self, client, auth_headers):
        """Проверяет доступ к health endpoint по API-ключу с внешнего адреса.

        Что делает: вызывает `GET /api/v1/health` с внешним `X-Real-IP` и валидным `X-API-Key`.
        Ожидаемая реакция: endpoint возвращает `200 OK`, потому что это штатный API-доступ по ключу.
        """
        response = client.get(
            "/api/v1/health",
            headers={**auth_headers, "X-Real-IP": "203.0.113.10"},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_root_returns_generic_not_found(self, client):
        """Проверяет, что корневая страница не раскрывает назначение сервиса.

        Что делает: вызывает `GET /` без API-ключа.
        Ожидаемая реакция: endpoint возвращает нейтральный `404 Not Found`, без названия проекта, ссылки на docs или упоминания API.
        """
        response = client.get("/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == {"detail": "Not Found"}

    def test_docs_routes_return_not_found_without_project_fingerprint(self, client):
        """Проверяет, что публичные documentation endpoints выключены.

        Что делает: вызывает `/docs`, `/redoc` и `/openapi.json` без API-ключа.
        Ожидаемая реакция: каждый endpoint возвращает `404 Not Found`, не показывая Swagger UI, ReDoc или OpenAPI schema.
        """
        for path in ("/docs", "/redoc", "/openapi.json"):
            response = client.get(path)
            assert response.status_code == status.HTTP_404_NOT_FOUND
            assert response.json() == {"detail": "Not Found"}
