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
    def test_collect_configuration_reprompts_until_valid_values(self) -> None:
        script_copy = make_script_copy(REPO_ROOT / "setup.sh")

        try:
            result = run_shell(
                f"""
                sed -i '$d' "{script_copy}"
                . "{script_copy}"
                unset CORS_ORIGINS
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
    def test_parse_args_supports_ref_skip_git_and_ssl(self) -> None:
        script_copy = make_script_copy(REPO_ROOT / "update.sh")

        try:
            result = run_shell(
                f"""
                sed -i '$d' "{script_copy}"
                . "{script_copy}"
                parse_args --ref main --skip-git --with-ssl
                printf '%s|%s|%s\\n' "$UPDATE_REF" "$SKIP_GIT_UPDATE" "$RUN_SSL_UPDATE"
                """
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "main|y|y")
        finally:
            script_copy.unlink(missing_ok=True)

    def test_parse_args_supports_install_dir(self) -> None:
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

    def test_update_rejects_dirty_git_worktree(self) -> None:
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
            self.assertIn("Рабочее дерево Git содержит незакоммиченные изменения", result.stderr)
        finally:
            script_copy.unlink(missing_ok=True)

    def test_install_dir_override_updates_root_and_env_file(self) -> None:
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
        result = run_shell(f'bash "{KERNVOX_CLI}" help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("KernvoxHub CLI", result.stdout)
        self.assertIn("kernvoxhub update", result.stdout)

    def test_cli_update_uses_saved_installation_path(self) -> None:
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

    def test_cli_shows_status_and_declines_update(self) -> None:
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
            self.assertIn("Обновление не запускалось.", result.stdout)
            self.assertFalse(marker_file.exists())
        finally:
            shutil.rmtree(temp_home, ignore_errors=True)
            shutil.rmtree(fake_install, ignore_errors=True)

    def test_update_launcher_alias_runs_cli_update(self) -> None:
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
