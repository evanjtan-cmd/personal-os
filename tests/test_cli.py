import subprocess
from pathlib import Path
import sqlite3
import sys

import pytest

from personal_os.cli import main
from personal_os.config import DATA_DIR_ENV_VAR, DEFAULT_DATABASE_FILENAME
from personal_os.database import CURRENT_SCHEMA_VERSION


def test_module_help_succeeds() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "personal_os", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "usage: personal-os" in result.stdout
    assert "init-db" in result.stdout


def test_init_db_command_uses_configured_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))

    status = main(["init-db"])

    database_path = tmp_path / DEFAULT_DATABASE_FILENAME
    assert status == 0
    assert database_path.exists()
    assert f"schema version {CURRENT_SCHEMA_VERSION}" in capsys.readouterr().out


def test_init_db_command_reports_incompatible_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = tmp_path / DEFAULT_DATABASE_FILENAME
    with sqlite3.connect(database_path) as connection:
        connection.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION + 1}")
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))

    status = main(["init-db"])

    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == ""
    assert "newer than supported" in captured.err
