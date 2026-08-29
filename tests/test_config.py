from pathlib import Path

import pytest

from personal_os.config import (
    DATA_DIR_ENV_VAR,
    DEFAULT_DATABASE_FILENAME,
    ConfigurationError,
    get_data_dir,
    get_database_path,
)


def test_default_data_directory_is_external_to_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_home = tmp_path / "home"
    working_directory = tmp_path / "repository"
    working_directory.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.chdir(working_directory)

    data_dir = get_data_dir({})

    assert data_dir == fake_home / ".personal-os"
    assert not data_dir.is_relative_to(working_directory)
    assert not data_dir.exists()


def test_environment_override_is_expanded_and_normalized(tmp_path: Path) -> None:
    configured = tmp_path / "data" / ".." / "runtime"

    data_dir = get_data_dir({DATA_DIR_ENV_VAR: str(configured)})

    assert data_dir == tmp_path / "runtime"
    assert get_database_path({DATA_DIR_ENV_VAR: str(configured)}) == (
        tmp_path / "runtime" / DEFAULT_DATABASE_FILENAME
    )
    assert not data_dir.exists()


def test_empty_environment_override_fails() -> None:
    with pytest.raises(ConfigurationError, match="must not be empty"):
        get_data_dir({DATA_DIR_ENV_VAR: "  "})

