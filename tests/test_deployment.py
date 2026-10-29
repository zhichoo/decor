"""Deployment bootstrap contracts; no Docker daemon or real credentials are used."""
import importlib.util
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("decor_container_entrypoint", ROOT / "docker/entrypoint.py")
entrypoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entrypoint)


class DeploymentTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("openssl") and shutil.which("bash"), "requires bash and openssl")
    def test_bootstrap_generates_private_passwords_and_never_rotates_existing_config(self):
        with tempfile.TemporaryDirectory(prefix="decor-deploy-test-") as directory:
            root = Path(directory)
            shutil.copy(ROOT / "deploy.sh", root / "deploy.sh")
            shutil.copy(ROOT / ".env.docker.example", root / ".env.docker.example")
            binary = root / "bin"
            binary.mkdir()
            docker = binary / "docker"
            docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$DEPLOY_TEST_LOG"\n')
            docker.chmod(0o700)
            env = os.environ | {"PATH": str(binary) + os.pathsep + os.environ["PATH"],
                                "DEPLOY_TEST_LOG": str(root / "commands")}
            first = subprocess.run(["bash", str(root / "deploy.sh")], env=env, capture_output=True, text=True, check=True)
            config = root / ".env.docker"
            text = config.read_text()
            passwords = re.findall(r"^(?:POSTGRES_PASSWORD|ADMIN_PASSWORD)=(.+)$", text, re.M)
            self.assertEqual(len(passwords), 2)
            self.assertNotEqual(*passwords)
            for password in passwords:
                self.assertRegex(password, r"^[0-9a-f]{48}$")
                self.assertNotIn(password, first.stdout + first.stderr)
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
            self.assertIn("DEEPSEEK_API_KEY=\n", text)
            second = subprocess.run(["bash", str(root / "deploy.sh"), "ps"], env=env, capture_output=True, text=True, check=True)
            self.assertEqual(config.read_text(), text)
            self.assertNotIn(passwords[1], second.stdout + second.stderr)
            commands = (root / "commands").read_text()
            self.assertIn("up -d --build", commands)
            self.assertIn("-f compose.deploy.yaml ps", commands)

    def test_writable_container_refuses_missing_or_weak_configuration(self):
        for settings in ({}, {"DATABASE_URL": "unused", "ADMIN_PASSWORD": "short"}):
            with self.subTest(settings=settings), patch.dict(os.environ, settings, clear=True), \
                 patch.object(entrypoint.psycopg2, "connect") as connect:
                with self.assertRaises(RuntimeError):
                    entrypoint.main()
                connect.assert_not_called()

    def test_read_only_container_requires_no_admin_password_or_api_key(self):
        with patch.dict(os.environ, {"DATABASE_URL": "unused", "PUBLIC_READ_ONLY": "true"}, clear=True), \
             patch.object(entrypoint.psycopg2, "connect") as connect, \
             patch.object(entrypoint.subprocess, "run") as run, \
             patch.object(entrypoint.os, "execvp") as execute, \
             patch.object(entrypoint.os, "umask"):
            entrypoint.main()
            connect.assert_called_once()
            self.assertEqual(run.call_count, 3)
            execute.assert_called_once()
            self.assertEqual(execute.call_args.args[0], "xvfb-run")


if __name__ == "__main__":
    unittest.main()
