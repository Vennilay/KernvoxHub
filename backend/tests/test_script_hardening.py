from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"


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
                unset POSTGRES_PASSWORD API_SECRET ENCRYPTION_KEY REDIS_PASSWORD INTERNAL_API_KEY
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
                unset POSTGRES_PASSWORD API_SECRET ENCRYPTION_KEY REDIS_PASSWORD INTERNAL_API_KEY
                load_existing_env
                docker_run() {{
                    if [ "$1" = "container" ] && [ "$2" = "inspect" ] && [ "$3" = "kernvox-postgres" ]; then
                        return 0
                    fi
                    return 1
                }}
                ensure_existing_installation_secrets
                printf '%s|%s|%s\\n' "$POSTGRES_PASSWORD" "$API_SECRET" "$INTERNAL_API_KEY"
                """
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.strip().endswith("db-secret|api-secret|internal-secret"))
        finally:
            script_copy.unlink(missing_ok=True)
            env_file.unlink(missing_ok=True)


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
