from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


def find_repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "setup.sh").exists() and (candidate / "scripts").is_dir():
            return candidate
    raise RuntimeError("Could not locate repository root")


REPO_ROOT = find_repo_root()
SCRIPTS_DIR = REPO_ROOT / "scripts"
KERNVOX_CLI = SCRIPTS_DIR / "kernvoxhub"
UPDATE_LAUNCHER = SCRIPTS_DIR / "kernvoxhub-update"


def run_shell(script: str, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-lc", script],
        text=True,
        capture_output=True,
        cwd=cwd or REPO_ROOT,
        check=False,
    )


def make_script_copy(source: Path) -> Path:
    target = Path(tempfile.mkstemp(prefix=f"{source.stem}-test.", suffix=".sh")[1])
    content = source.read_text()
    content = content.replace(
        'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        f'ROOT_DIR="{REPO_ROOT}"',
    )
    content = content.replace(
        'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"',
        f'ROOT_DIR="{REPO_ROOT}"',
    )
    target.write_text(content)
    return target


class EnvHelpersTestCase(unittest.TestCase):
    def test_load_env_file_treats_values_as_data(self) -> None:
        """Проверяет безопасную загрузку `.env` как данных, а не shell-кода.

        Что делает: создаёт env-файл со значением вида `$(touch ...)`, загружает его через `load_env_file` и проверяет переменные.
        Ожидаемая реакция: значение сохраняется как строка, команда не выполняется, файл-маркер атаки не появляется.
        """
        env_file = Path(tempfile.mkstemp(prefix="kernvox-env.")[1])
        env_file.write_text(
            "DOMAIN=example.com\n"
            "EMAIL=ops@example.com\n"
            "MALICIOUS=$(touch /tmp/kernvox-script-test-should-not-exist)\n"
        )

        try:
            result = run_shell(
                f"""
                . "{SCRIPTS_DIR / 'lib' / 'env.sh'}"
                load_env_file "{env_file}"
                printf '%s|%s|%s\\n' "$DOMAIN" "$EMAIL" "$MALICIOUS"
                test ! -e /tmp/kernvox-script-test-should-not-exist
                """
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                "example.com|ops@example.com|$(touch /tmp/kernvox-script-test-should-not-exist)",
            )
        finally:
            env_file.unlink(missing_ok=True)
            Path("/tmp/kernvox-script-test-should-not-exist").unlink(missing_ok=True)

    def test_upsert_env_value_updates_existing_keys(self) -> None:
        """Проверяет безопасное обновление ключей в `.env`.

        Что делает: вызывает `upsert_env_value` для существующего `DOMAIN` и нового `INTERNAL_API_KEY`.
        Ожидаемая реакция: файл содержит обновлённые значения, не дублирует ключи и получает права `600`.
        """
        env_file = Path(tempfile.mkstemp(prefix="kernvox-upsert.")[1])
        env_file.write_text("DOMAIN=localhost\nEMAIL=admin@example.com\n")

        try:
            result = run_shell(
                f"""
                . "{SCRIPTS_DIR / 'lib' / 'env.sh'}"
                upsert_env_value "{env_file}" DOMAIN api.example.com
                upsert_env_value "{env_file}" INTERNAL_API_KEY secret-token
                """
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            content = env_file.read_text()
            self.assertIn("DOMAIN=api.example.com", content)
            self.assertIn("INTERNAL_API_KEY=secret-token", content)
            self.assertEqual(oct(env_file.stat().st_mode & 0o777), "0o600")
        finally:
            env_file.unlink(missing_ok=True)


class SetupScriptTestCase(unittest.TestCase):
    def test_compose_keeps_redis_password_out_of_redis_url(self) -> None:
        """Проверяет безопасную передачу Redis password в Docker Compose.

        Что делает: читает `docker-compose.yml` и проверяет, что `REDIS_URL` не собирается через raw password interpolation.
        Ожидаемая реакция: пароль передаётся отдельной переменной, чтобы спецсимволы не ломали URL parser backend.
        """
        compose_file = REPO_ROOT / "docker-compose.yml"
        content = compose_file.read_text()

        self.assertIn("REDIS_URL=redis://redis:6379/0", content)
        self.assertNotIn("REDIS_URL=redis://:${REDIS_PASSWORD", content)

    def test_http_probe_sends_api_key_when_available(self) -> None:
        """Проверяет authenticated health probe installer'а.

        Что делает: подменяет `curl` и вызывает `http_probe` с `API_TOKEN`.
        Ожидаемая реакция: probe отправляет `X-API-Key`, потому что внешний health endpoint закрыт auth middleware.
        """
        curl_args_file = Path(tempfile.mkstemp(prefix="kernvox-curl-args.")[1])

        try:
            result = run_shell(
                f"""
                . "{SCRIPTS_DIR / 'lib' / 'common.sh'}"
                API_TOKEN=kvx-test-token
                command_exists() {{ [ "$1" = "curl" ]; }}
                curl() {{
                    printf '%s\\n' "$*" > "{curl_args_file}"
                }}
                http_probe "http://127.0.0.1/api/v1/health"
                """
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("X-API-Key: kvx-test-token", curl_args_file.read_text())
        finally:
            curl_args_file.unlink(missing_ok=True)

    def test_installer_installs_apparmor_parser_when_apparmor_is_enabled(self) -> None:
        """Проверяет preflight для Docker build на AppArmor-хостах.

        Что делает: имитирует включённый AppArmor и отсутствие `apparmor_parser`.
        Ожидаемая реакция: installer ставит пакет `apparmor` до запуска Docker build.
        """
        apparmor_flag = Path(tempfile.mkstemp(prefix="kernvox-apparmor.")[1])
        apparmor_flag.write_text("Y")

        try:
            result = run_shell(
                f"""
                . "{SCRIPTS_DIR / 'lib' / 'common.sh'}"
                KERNVOX_APPARMOR_ENABLED_PATH="{apparmor_flag}"
                installed=n
                command_exists() {{
                    if [ "$1" = "apparmor_parser" ]; then
                        [ "$installed" = "y" ]
                        return
                    fi
                    command -v "$1" >/dev/null 2>&1
                }}
                run_privileged() {{
                    printf 'privileged:%s\\n' "$*"
                    return 0
                }}
                install_packages() {{
                    printf 'packages:%s\\n' "$*"
                    installed=y
                }}
                install_apparmor_parser_if_needed debian
                """
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("privileged:apt-get update", result.stdout)
            self.assertIn("packages:debian apparmor", result.stdout)
        finally:
            apparmor_flag.unlink(missing_ok=True)

    def test_installer_accepts_apparmor_parser_in_sbin(self) -> None:
        """Проверяет Debian-путь `apparmor_parser` вне user PATH.

        Что делает: имитирует включённый AppArmor, пустой `command -v apparmor_parser` и бинарник в `/usr/sbin`.
        Ожидаемая реакция: installer не пытается переустанавливать AppArmor и не падает на PATH обычного пользователя.
        """
        apparmor_flag = Path(tempfile.mkstemp(prefix="kernvox-apparmor.")[1])
        fake_sbin = Path(tempfile.mkdtemp(prefix="kernvox-sbin."))
        fake_parser = fake_sbin / "apparmor_parser"
        apparmor_flag.write_text("Y")
        fake_parser.write_text("#!/bin/sh\nexit 0\n")
        fake_parser.chmod(0o755)

        try:
            result = run_shell(
                f"""
                . "{SCRIPTS_DIR / 'lib' / 'common.sh'}"
                KERNVOX_APPARMOR_ENABLED_PATH="{apparmor_flag}"
                command_exists() {{
                    if [ "$1" = "apparmor_parser" ]; then
                        return 1
                    fi
                    command -v "$1" >/dev/null 2>&1
                }}
                apparmor_parser_exists() {{
                    command_exists apparmor_parser && return 0
                    [ -x "{fake_parser}" ] && return 0
                    return 1
                }}
                install_packages() {{
                    printf 'unexpected-install:%s\\n' "$*"
                }}
                install_apparmor_parser_if_needed debian
                """
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("unexpected-install", result.stdout)
        finally:
            apparmor_flag.unlink(missing_ok=True)
            shutil.rmtree(fake_sbin, ignore_errors=True)

    def test_collect_configuration_reprompts_until_valid_values(self) -> None:
        """Проверяет повторный запрос настроек installer при невалидном вводе.

        Что делает: подаёт в `collect_configuration` плохой email, затем корректный domain/email/interval.
        Ожидаемая реакция: installer сообщает об ошибке, повторяет ввод и в итоге выставляет валидные DOMAIN, EMAIL, INTERVAL и CORS.
        """
        script_copy = make_script_copy(REPO_ROOT / "setup.sh")

        try:
            result = run_shell(
                f"""
                sed -i '$d' "{script_copy}"
                . "{script_copy}"
                unset CORS_ORIGINS
                POSTGRES_PASSWORD=db-secret
                API_SECRET=api-secret
                API_TOKEN=kvx-bootstrap-token
                SERVER_ACTION_TOKEN=action-secret
                ENCRYPTION_KEY=encryption-secret
                REDIS_PASSWORD=redis-secret
                INTERNAL_API_KEY=internal-secret
                collect_configuration <<'EOF'
localhost
bad-email
localhost
admin@example.com
60

EOF
                printf '%s|%s|%s|%s|%s\\n' "$DOMAIN" "$EMAIL" "$INTERVAL" "$SSL_ENABLE" "$CORS_ORIGINS"
                """
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("имеет некорректный формат", result.stderr)
            self.assertTrue(
                result.stdout.strip().endswith(
                    "localhost|admin@example.com|60|n|http://localhost,http://127.0.0.1,http://localhost:3000,http://127.0.0.1:3000"
                )
            )
        finally:
            script_copy.unlink(missing_ok=True)

    def test_existing_installation_requires_all_persisted_secrets(self) -> None:
        """Проверяет защиту существующей инсталляции от потери секретов.

        Что делает: имитирует уже созданные Docker-ресурсы и `.env` без критичных секретов.
        Ожидаемая реакция: installer завершает работу с ошибкой и перечисляет отсутствующие секреты, чтобы не сломать доступ к БД/шифрованию.
        """
        script_copy = make_script_copy(REPO_ROOT / "setup.sh")
        env_file = Path(tempfile.mkstemp(prefix="kernvox-setup-env.")[1])
        env_file.write_text("DOMAIN=example.com\nEMAIL=ops@example.com\n")

        try:
            result = run_shell(
                f"""
                sed -i '$d' "{script_copy}"
                . "{script_copy}"
                ENV_FILE="{env_file}"
                unset POSTGRES_PASSWORD API_SECRET API_TOKEN ENCRYPTION_KEY REDIS_PASSWORD INTERNAL_API_KEY
                load_existing_env
                docker_run() {{
                    if [ "$1" = "container" ] && [ "$2" = "inspect" ] && [ "$3" = "kernvox-postgres" ]; then
                        return 0
                    fi
                    return 1
                }}
                ensure_existing_installation_secrets
                """
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Найдена существующая инсталляция", result.stderr)
            self.assertIn("POSTGRES_PASSWORD", result.stderr)
            self.assertIn("ENCRYPTION_KEY", result.stderr)
        finally:
            script_copy.unlink(missing_ok=True)
            env_file.unlink(missing_ok=True)

    def test_existing_installation_accepts_complete_secret_set(self) -> None:
        """Проверяет успешную загрузку полного набора секретов существующей инсталляции.

        Что делает: создаёт `.env` со всеми защищёнными ключами и запускает проверку `ensure_existing_installation_secrets`.
        Ожидаемая реакция: проверка проходит без ошибки, а значения остаются теми же, без регенерации.
        """
        script_copy = make_script_copy(REPO_ROOT / "setup.sh")
        env_file = Path(tempfile.mkstemp(prefix="kernvox-setup-env.")[1])
        env_file.write_text(
            "POSTGRES_PASSWORD=db-secret\n"
            "API_SECRET=api-secret\n"
            "API_TOKEN=kvx-bootstrap-token\n"
            "ENCRYPTION_KEY=encryption-secret\n"
            "REDIS_PASSWORD=redis-secret\n"
            "INTERNAL_API_KEY=internal-secret\n"
        )

        try:
            result = run_shell(
                f"""
                sed -i '$d' "{script_copy}"
                . "{script_copy}"
                ENV_FILE="{env_file}"
                unset POSTGRES_PASSWORD API_SECRET API_TOKEN ENCRYPTION_KEY REDIS_PASSWORD INTERNAL_API_KEY
                load_existing_env
                docker_run() {{
                    if [ "$1" = "container" ] && [ "$2" = "inspect" ] && [ "$3" = "kernvox-postgres" ]; then
                        return 0
                    fi
                    return 1
                }}
                ensure_existing_installation_secrets
                printf '%s|%s|%s|%s\\n' "$POSTGRES_PASSWORD" "$API_SECRET" "$API_TOKEN" "$INTERNAL_API_KEY"
                """
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.strip().endswith("db-secret|api-secret|kvx-bootstrap-token|internal-secret"))
        finally:
            script_copy.unlink(missing_ok=True)
            env_file.unlink(missing_ok=True)


class UpdateScriptTestCase(unittest.TestCase):
    def test_parse_args_supports_skip_git_and_ssl(self) -> None:
        """Проверяет технические флаги updater без сценария выбора коммитов.

        Что делает: вызывает `parse_args --skip-git --with-ssl`.
        Ожидаемая реакция: updater включает rebuild-only режим и SSL-шаг, не требуя ref/branch от пользователя.
        """
        script_copy = make_script_copy(REPO_ROOT / "update.sh")

        try:
            result = run_shell(
                f"""
                sed -i '$d' "{script_copy}"
                . "{script_copy}"
                parse_args --skip-git --with-ssl
                printf '%s|%s\\n' "$SKIP_GIT_UPDATE" "$RUN_SSL_UPDATE"
                """
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "y|y")
        finally:
            script_copy.unlink(missing_ok=True)

    def test_parse_args_supports_install_dir(self) -> None:
        """Проверяет указание каталога установленного проекта для updater.

        Что делает: вызывает `parse_args --install-dir /srv/kernvox --skip-git`.
        Ожидаемая реакция: updater сохраняет override пути и включает режим без скачивания новой версии.
        """
        script_copy = make_script_copy(REPO_ROOT / "update.sh")

        try:
            result = run_shell(
                f"""
                sed -i '$d' "{script_copy}"
                . "{script_copy}"
                parse_args --install-dir /srv/kernvox --skip-git
                printf '%s|%s\\n' "$INSTALL_DIR_OVERRIDE" "$SKIP_GIT_UPDATE"
                """
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "/srv/kernvox|y")
        finally:
            script_copy.unlink(missing_ok=True)

    def test_update_requires_existing_installation(self) -> None:
        """Проверяет запрет update до первичной установки.

        Что делает: имитирует отсутствие Docker-контейнеров/volume существующей инсталляции и вызывает `ensure_existing_installation`.
        Ожидаемая реакция: updater завершается ошибкой с сообщением, что для первого запуска нужен `setup.sh`.
        """
        script_copy = make_script_copy(REPO_ROOT / "update.sh")
        env_file = Path(tempfile.mkstemp(prefix="kernvox-update-env.")[1])
        env_file.write_text(
            "POSTGRES_PASSWORD=db-secret\n"
            "API_SECRET=api-secret\n"
            "API_TOKEN=kvx-bootstrap-token\n"
            "ENCRYPTION_KEY=encryption-secret\n"
            "REDIS_PASSWORD=redis-secret\n"
            "INTERNAL_API_KEY=internal-secret\n"
        )

        try:
            result = run_shell(
                f"""
                sed -i '$d' "{script_copy}"
                . "{script_copy}"
                ENV_FILE="{env_file}"
                load_existing_env
                docker_run() {{ return 1; }}
                ensure_existing_installation
                """
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Существующая инсталляция KernvoxHub не найдена", result.stderr)
        finally:
            script_copy.unlink(missing_ok=True)
            env_file.unlink(missing_ok=True)

    def test_update_adds_missing_server_action_token(self) -> None:
        """Проверяет миграцию старого `.env` на новый action-token.

        Что делает: загружает `.env` без `SERVER_ACTION_TOKEN`, подменяет генератор секрета и вызывает `ensure_runtime_env_defaults`.
        Ожидаемая реакция: updater добавляет `SERVER_ACTION_TOKEN` в файл и экспортирует его для последующего запуска контейнеров.
        """
        script_copy = make_script_copy(REPO_ROOT / "update.sh")
        env_file = Path(tempfile.mkstemp(prefix="kernvox-update-env.")[1])
        env_file.write_text(
            "POSTGRES_PASSWORD=db-secret\n"
            "API_SECRET=api-secret\n"
            "API_TOKEN=kvx-bootstrap-token\n"
            "ENCRYPTION_KEY=encryption-secret\n"
            "REDIS_PASSWORD=redis-secret\n"
            "INTERNAL_API_KEY=internal-secret\n"
        )

        try:
            result = run_shell(
                f"""
                sed -i '$d' "{script_copy}"
                . "{script_copy}"
                ENV_FILE="{env_file}"
                load_existing_env
                unset SERVER_ACTION_TOKEN
                generate_hex_secret() {{ printf '%s' action-secret; }}
                ensure_runtime_env_defaults
                grep -Fx SERVER_ACTION_TOKEN=action-secret "{env_file}"
                """
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            script_copy.unlink(missing_ok=True)
            env_file.unlink(missing_ok=True)

    def test_update_rejects_dirty_git_worktree(self) -> None:
        """Проверяет защиту updater от локально изменённых файлов.

        Что делает: подменяет `git diff` так, чтобы рабочее дерево считалось грязным, и вызывает `ensure_clean_git_worktree`.
        Ожидаемая реакция: updater останавливается с понятной ошибкой, чтобы автоматическое обновление не затёрло локальные правки.
        """
        script_copy = make_script_copy(REPO_ROOT / "update.sh")

        try:
            result = run_shell(
                f"""
                sed -i '$d' "{script_copy}"
                . "{script_copy}"
                git() {{
                    if [ "$1" = "diff" ]; then
                        return 1
                    fi
                    command git "$@"
                }}
                ensure_clean_git_worktree
                """
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("В файлах проекта есть локальные изменения", result.stderr)
        finally:
            script_copy.unlink(missing_ok=True)

    def test_install_dir_override_updates_root_and_env_file(self) -> None:
        """Проверяет применение `--install-dir` к root и `.env` путям.

        Что делает: создаёт fake installation root и вызывает `apply_installation_root_override`.
        Ожидаемая реакция: `ROOT_DIR` и `ENV_FILE` указывают на выбранную инсталляцию, а не на каталог запуска теста.
        """
        script_copy = make_script_copy(REPO_ROOT / "update.sh")
        install_root = Path(tempfile.mkdtemp(prefix="kernvox-install-root."))
        (install_root / "docker-compose.yml").write_text("services:\n")
        (install_root / "update.sh").write_text("#!/bin/bash\n")

        try:
            result = run_shell(
                f"""
                sed -i '$d' "{script_copy}"
                . "{script_copy}"
                INSTALL_DIR_OVERRIDE="{install_root}"
                apply_installation_root_override
                printf '%s|%s\\n' "$ROOT_DIR" "$ENV_FILE"
                """
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), f"{install_root}|{install_root / '.env'}")
        finally:
            script_copy.unlink(missing_ok=True)
            shutil.rmtree(install_root, ignore_errors=True)


class KernvoxCliTestCase(unittest.TestCase):
    def test_help_does_not_require_installation(self) -> None:
        """Проверяет, что `kernvoxhub help` работает без установленного проекта.

        Что делает: запускает wrapper с командой `help`, не создавая state-файл и контейнеры.
        Ожидаемая реакция: команда возвращает `0` и показывает help, включая `check-update` и `update`.
        """
        result = run_shell(f'bash "{KERNVOX_CLI}" help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("KernvoxHub CLI", result.stdout)
        self.assertIn("kernvoxhub check-update", result.stdout)
        self.assertIn("kernvoxhub update", result.stdout)

    def test_cli_update_uses_saved_installation_path(self) -> None:
        """Проверяет запуск updater из сохранённого installation path.

        Что делает: создаёт state-файл `install-dir`, fake `update.sh` и запускает `kernvoxhub update --skip-git --with-ssl`.
        Ожидаемая реакция: wrapper передаёт `KERNVOX_INSTALL_DIR` и аргументы в updater выбранной инсталляции.
        """
        temp_home = Path(tempfile.mkdtemp(prefix="kernvox-launcher-home."))
        fake_install = Path(tempfile.mkdtemp(prefix="kernvox-launcher-install."))
        state_dir = temp_home / ".config" / "kernvoxhub"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "install-dir").write_text(f"{fake_install}\n")
        (fake_install / "docker-compose.yml").write_text("services:\n")
        (fake_install / "scripts").mkdir(parents=True, exist_ok=True)
        update_script = fake_install / "update.sh"
        update_script.write_text(
            "#!/bin/bash\n"
            "set -eu\n"
            "printf '%s|%s|%s\\n' \"$KERNVOX_INSTALL_DIR\" \"$1\" \"$2\"\n"
        )
        update_script.chmod(0o755)

        try:
            result = run_shell(
                f'HOME="{temp_home}" bash "{KERNVOX_CLI}" update --skip-git --with-ssl'
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), f"{fake_install}|--skip-git|--with-ssl")
        finally:
            shutil.rmtree(temp_home, ignore_errors=True)
            shutil.rmtree(fake_install, ignore_errors=True)

    def test_cli_shows_status_and_update_check_warning(self) -> None:
        """Проверяет статусное меню wrapper при невозможности проверить обновления.

        Что делает: создаёт fake install root и fake docker, но не даёт рабочий git remote для проверки версии.
        Ожидаемая реакция: CLI показывает путь установки, сервисы и предупреждение о невозможности auto-check без запуска update.
        """
        temp_home = Path(tempfile.mkdtemp(prefix="kernvox-cli-home."))
        fake_install = Path(tempfile.mkdtemp(prefix="kernvox-cli-install."))
        state_dir = temp_home / ".config" / "kernvoxhub"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "install-dir").write_text(f"{fake_install}\n")
        (fake_install / "docker-compose.yml").write_text("services:\n")
        (fake_install / "scripts").mkdir(parents=True, exist_ok=True)
        update_script = fake_install / "update.sh"
        marker_file = fake_install / "update-called"
        update_script.write_text(
            "#!/bin/bash\n"
            "set -eu\n"
            f"touch '{marker_file}'\n"
        )
        update_script.chmod(0o755)

        fake_bin = fake_install / "bin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        docker_script = fake_bin / "docker"
        docker_script.write_text(
            "#!/bin/bash\n"
            "set -eu\n"
            "if [ \"$1\" = \"compose\" ] && [ \"$2\" = \"version\" ]; then\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$1\" = \"compose\" ] && [ \"$2\" = \"ps\" ]; then\n"
            "  printf '%s\\n' 'NAME STATUS'\n"
            "  printf '%s\\n' 'kernvox-backend Up'\n"
            "  exit 0\n"
            "fi\n"
            "exit 1\n"
        )
        docker_script.chmod(0o755)

        try:
            result = run_shell(
                f"printf 'n\\n' | PATH=\"{fake_bin}:$PATH\" HOME=\"{temp_home}\" bash \"{KERNVOX_CLI}\""
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(fake_install), result.stdout)
            self.assertIn("Не удалось проверить обновления", result.stdout)
            self.assertFalse(marker_file.exists())
        finally:
            shutil.rmtree(temp_home, ignore_errors=True)
            shutil.rmtree(fake_install, ignore_errors=True)

    def test_cli_check_update_reports_available_version(self) -> None:
        """Проверяет явную команду `kernvoxhub check-update`.

        Что делает: подменяет `git fetch/rev-list`, чтобы remote содержал две новые версии относительно local HEAD.
        Ожидаемая реакция: wrapper сообщает пользователю, что доступна новая версия.
        """
        temp_home = Path(tempfile.mkdtemp(prefix="kernvox-check-update-home."))
        fake_install = Path(tempfile.mkdtemp(prefix="kernvox-check-update-install."))
        state_dir = temp_home / ".config" / "kernvoxhub"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "install-dir").write_text(f"{fake_install}\n")
        (fake_install / "docker-compose.yml").write_text("services:\n")
        (fake_install / "scripts").mkdir(parents=True, exist_ok=True)
        (fake_install / ".git").mkdir(parents=True, exist_ok=True)
        (fake_install / "update.sh").write_text("#!/bin/bash\n")

        fake_bin = fake_install / "bin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        git_script = fake_bin / "git"
        git_script.write_text(
            "#!/bin/bash\n"
            "set -eu\n"
            "if [ \"$1\" = \"-C\" ]; then shift 2; fi\n"
            "case \"$1 $2\" in\n"
            "  'fetch --quiet') exit 0 ;;\n"
            "  'rev-parse --abbrev-ref') printf '%s\\n' 'origin/main'; exit 0 ;;\n"
            "  'rev-list --count') printf '%s\\n' '2'; exit 0 ;;\n"
            "esac\n"
            "exit 1\n"
        )
        git_script.chmod(0o755)

        try:
            result = run_shell(
                f'PATH="{fake_bin}:$PATH" HOME="{temp_home}" bash "{KERNVOX_CLI}" check-update'
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Доступна новая версия", result.stdout)
        finally:
            shutil.rmtree(temp_home, ignore_errors=True)
            shutil.rmtree(fake_install, ignore_errors=True)

    def test_update_launcher_alias_runs_cli_update(self) -> None:
        """Проверяет compatibility alias `kernvoxhub-update`.

        Что делает: запускает legacy launcher и fake update script через сохранённый installation path.
        Ожидаемая реакция: alias делегирует выполнение в `kernvoxhub update` и передаёт аргументы без потери.
        """
        temp_home = Path(tempfile.mkdtemp(prefix="kernvox-update-alias-home."))
        fake_install = Path(tempfile.mkdtemp(prefix="kernvox-update-alias-install."))
        state_dir = temp_home / ".config" / "kernvoxhub"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "install-dir").write_text(f"{fake_install}\n")
        (fake_install / "docker-compose.yml").write_text("services:\n")
        (fake_install / "scripts").mkdir(parents=True, exist_ok=True)
        update_script = fake_install / "update.sh"
        update_script.write_text(
            "#!/bin/bash\n"
            "set -eu\n"
            "printf '%s|%s\\n' \"$KERNVOX_INSTALL_DIR\" \"$1\"\n"
        )
        update_script.chmod(0o755)

        try:
            result = run_shell(
                f'HOME="{temp_home}" bash "{UPDATE_LAUNCHER}" --skip-git'
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), f"{fake_install}|--skip-git")
        finally:
            shutil.rmtree(temp_home, ignore_errors=True)
            shutil.rmtree(fake_install, ignore_errors=True)

    def test_cli_detects_installation_path_from_docker_mounts(self) -> None:
        """Проверяет автообнаружение установки по Docker mounts.

        Что делает: подменяет `docker inspect`, чтобы nginx container указывал mount на fake install root.
        Ожидаемая реакция: wrapper находит installation root без state-файла и запускает updater именно из него.
        """
        temp_dir = Path(tempfile.mkdtemp(prefix="kernvox-launcher-docker."))
        fake_install = temp_dir / "install"
        fake_install.mkdir(parents=True, exist_ok=True)
        (fake_install / "docker-compose.yml").write_text("services:\n")
        (fake_install / "scripts").mkdir(parents=True, exist_ok=True)
        (fake_install / "nginx").mkdir(parents=True, exist_ok=True)
        update_script = fake_install / "update.sh"
        update_script.write_text(
            "#!/bin/bash\n"
            "set -eu\n"
            "printf '%s\\n' \"$KERNVOX_INSTALL_DIR\"\n"
        )
        update_script.chmod(0o755)

        fake_bin = temp_dir / "bin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        docker_script = fake_bin / "docker"
        docker_script.write_text(
            "#!/bin/bash\n"
            "set -eu\n"
            "if [ \"$1\" = \"inspect\" ] && [ \"$2\" = \"--format\" ] && [ \"$4\" = \"kernvox-nginx\" ]; then\n"
            f"  printf '%s\\n' '{fake_install / 'nginx'}'\n"
            "  exit 0\n"
            "fi\n"
            "exit 1\n"
        )
        docker_script.chmod(0o755)

        try:
            result = run_shell(
                f'PATH="{fake_bin}:$PATH" HOME="{temp_dir}" bash "{KERNVOX_CLI}" update',
                cwd=temp_dir,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), str(fake_install))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class SslSetupScriptTestCase(unittest.TestCase):
    def test_collect_ssl_configuration_fails_cleanly_on_eof_after_invalid_input(self) -> None:
        """Проверяет корректный отказ SSL setup при EOF после невалидного ввода.

        Что делает: передаёт localhost/bad-email, затем обрывает ввод до завершения повторного prompt.
        Ожидаемая реакция: скрипт завершает работу с понятной ошибкой `Ввод прерван пользователем`, а не зависает.
        """
        script_copy = make_script_copy(SCRIPTS_DIR / "ssl-setup.sh")
        env_file = Path(tempfile.mkstemp(prefix="kernvox-ssl-env.")[1])
        env_file.write_text("DOMAIN=localhost\nEMAIL=bad-email\n")

        try:
            result = run_shell(
                f"""
                sed -i '$d' "{script_copy}"
                . "{script_copy}"
                ENV_FILE="{env_file}"
                collect_ssl_configuration <<'EOF'
localhost
bad-email
example.com
admin@example.com
EOF
                """
            )
            self.assertNotEqual(result.returncode, 0)
            combined_output = result.stdout + result.stderr
            self.assertIn("Исправьте DOMAIN и EMAIL и повторите ввод.", combined_output)
            self.assertIn("Ввод прерван пользователем.", result.stderr)
        finally:
            script_copy.unlink(missing_ok=True)
            env_file.unlink(missing_ok=True)

    def test_verify_tls_deployment_rejects_missing_certificates(self) -> None:
        """Проверяет отказ TLS verification при отсутствии сертификатов в nginx.

        Что делает: подменяет `compose_run exec nginx test -f`, чтобы проверка fullchain/privkey падала.
        Ожидаемая реакция: SSL setup завершает работу с ошибкой о недоступном certificate file.
        """
        script_copy = make_script_copy(SCRIPTS_DIR / "ssl-setup.sh")

        try:
            result = run_shell(
                f"""
                sed -i '$d' "{script_copy}"
                . "{script_copy}"
                DOMAIN="api.example.com"
                compose_run() {{
                    if [ "$1" = "exec" ] && [ "$2" = "-T" ] && [ "$3" = "nginx" ] && [ "$4" = "test" ]; then
                        return 1
                    fi
                    return 0
                }}
                verify_tls_deployment
                """
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Nginx не видит /etc/letsencrypt/live/api.example.com/fullchain.pem", result.stderr)
        finally:
            script_copy.unlink(missing_ok=True)

    def test_verify_tls_deployment_requires_loaded_https_config(self) -> None:
        """Проверяет, что SSL setup требует реально загруженный HTTPS config.

        Что делает: имитирует наличие сертификатов, но возвращает `nginx -T` без `listen 443 ssl`.
        Ожидаемая реакция: verification падает, потому что nginx не применил TLS-конфигурацию.
        """
        script_copy = make_script_copy(SCRIPTS_DIR / "ssl-setup.sh")

        try:
            result = run_shell(
                f"""
                sed -i '$d' "{script_copy}"
                . "{script_copy}"
                DOMAIN="api.example.com"
                compose_run() {{
                    if [ "$1" = "exec" ] && [ "$2" = "-T" ] && [ "$3" = "nginx" ] && [ "$4" = "test" ]; then
                        return 0
                    fi
                    if [ "$1" = "exec" ] && [ "$2" = "-T" ] && [ "$3" = "nginx" ] && [ "$4" = "nginx" ] && [ "$5" = "-T" ]; then
                        printf '%s\\n' 'server {{ listen 80; }}'
                        return 0
                    fi
                    return 1
                }}
                verify_tls_deployment
                """
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("nginx не слушает 443/TLS", result.stderr)
        finally:
            script_copy.unlink(missing_ok=True)

    def test_verify_tls_deployment_accepts_loaded_https_config(self) -> None:
        """Проверяет успешную TLS verification после применения HTTPS config.

        Что делает: имитирует наличие сертификатов и `nginx -T` с `listen 443 ssl` и правильным `ssl_certificate`.
        Ожидаемая реакция: verification проходит и скрипт продолжает выполнение.
        """
        script_copy = make_script_copy(SCRIPTS_DIR / "ssl-setup.sh")

        try:
            result = run_shell(
                f"""
                sed -i '$d' "{script_copy}"
                . "{script_copy}"
                DOMAIN="api.example.com"
                compose_run() {{
                    if [ "$1" = "exec" ] && [ "$2" = "-T" ] && [ "$3" = "nginx" ] && [ "$4" = "test" ]; then
                        return 0
                    fi
                    if [ "$1" = "exec" ] && [ "$2" = "-T" ] && [ "$3" = "nginx" ] && [ "$4" = "nginx" ] && [ "$5" = "-T" ]; then
                        printf '%s\\n' 'listen 443 ssl;'
                        printf '%s\\n' 'ssl_certificate /etc/letsencrypt/live/api.example.com/fullchain.pem;'
                        return 0
                    fi
                    return 1
                }}
                verify_tls_deployment
                echo ok
                """
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.strip().endswith("ok"))
        finally:
            script_copy.unlink(missing_ok=True)


class NginxEntrypointTestCase(unittest.TestCase):
    def test_renders_http_config_without_certificates(self) -> None:
        """Проверяет nginx entrypoint без TLS-сертификатов.

        Что делает: запускает render-only mode с пустым cert root и `DOMAIN=localhost`.
        Ожидаемая реакция: генерируется HTTP-конфигурация на 80 порту без `listen 443 ssl`.
        """
        temp_dir = Path(tempfile.mkdtemp(prefix="kernvox-nginx-http."))
        target_conf = temp_dir / "nginx.conf"

        try:
            result = run_shell(
                f"""
                TEMPLATE_DIR="{REPO_ROOT / 'nginx'}" \
                TARGET_CONF="{target_conf}" \
                CERT_ROOT="{temp_dir / 'certs'}" \
                DOMAIN=localhost \
                NGINX_RENDER_ONLY=1 \
                sh "{REPO_ROOT / 'nginx' / 'entrypoint.sh'}"
                """
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            rendered = target_conf.read_text()
            self.assertIn("listen 80;", rendered)
            self.assertNotIn("listen 443 ssl;", rendered)
            self.assertIn("server_name _;", rendered)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_renders_https_config_when_certificates_exist(self) -> None:
        """Проверяет nginx entrypoint при наличии TLS-сертификатов.

        Что делает: создаёт fake `fullchain.pem` и `privkey.pem`, затем запускает render-only mode.
        Ожидаемая реакция: генерируется HTTPS-конфигурация с `listen 443 ssl`, `ssl_certificate` и HTTP-to-HTTPS redirect.
        """
        temp_dir = Path(tempfile.mkdtemp(prefix="kernvox-nginx-https."))
        cert_dir = temp_dir / "certs" / "api.example.com"
        target_conf = temp_dir / "nginx.conf"
        cert_dir.mkdir(parents=True, exist_ok=True)
        (cert_dir / "fullchain.pem").write_text("dummy cert")
        (cert_dir / "privkey.pem").write_text("dummy key")

        try:
            result = run_shell(
                f"""
                TEMPLATE_DIR="{REPO_ROOT / 'nginx'}" \
                TARGET_CONF="{target_conf}" \
                CERT_ROOT="{temp_dir / 'certs'}" \
                DOMAIN=api.example.com \
                NGINX_RENDER_ONLY=1 \
                sh "{REPO_ROOT / 'nginx' / 'entrypoint.sh'}"
                """
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            rendered = target_conf.read_text()
            self.assertIn("listen 443 ssl;", rendered)
            self.assertIn("ssl_certificate /etc/letsencrypt/live/api.example.com/fullchain.pem;", rendered)
            self.assertIn("return 301 https://$host$request_uri;", rendered)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
