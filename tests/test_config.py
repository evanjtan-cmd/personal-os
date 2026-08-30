from pathlib import Path

import pytest

from personal_os.config import (
    DATA_DIR_ENV_VAR,
    DEFAULT_DATABASE_FILENAME,
    TIMEZONE_ENV_VAR,
    ConfigurationError,
    get_data_dir,
    get_database_path,
    get_timezone_name,
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


def test_explicit_timezone_is_validated_and_returned_unchanged() -> None:
    assert get_timezone_name("America/New_York", {}) == "America/New_York"


def test_environment_timezone_is_used() -> None:
    assert get_timezone_name(None, {TIMEZONE_ENV_VAR: "Europe/London"}) == "Europe/London"


def test_explicit_timezone_overrides_environment() -> None:
    assert get_timezone_name(
        "America/Chicago", {TIMEZONE_ENV_VAR: "Europe/London"}
    ) == "America/Chicago"


@pytest.mark.parametrize("explicit,environ", [(None, {}), ("", {}), ("  ", {}), (None, {TIMEZONE_ENV_VAR: " "})])
def test_missing_or_blank_timezone_fails(
    explicit: str | None, environ: dict[str, str]
) -> None:
    with pytest.raises(ConfigurationError, match="timezone"):
        get_timezone_name(explicit, environ)


def test_invalid_timezone_is_normalized_to_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="Not/A_Real_Zone"):
        get_timezone_name("Not/A_Real_Zone", {})


def test_zoneinfo_library_failure_does_not_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_key: str) -> None:
        raise KeyError("unavailable zone data")

    monkeypatch.setattr("personal_os.config.ZoneInfo", fail)
    with pytest.raises(ConfigurationError, match="invalid IANA timezone"):
        get_timezone_name("America/New_York", {})
