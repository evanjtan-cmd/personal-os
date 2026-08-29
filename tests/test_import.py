import os
from pathlib import Path
import subprocess
import sys


def test_package_import() -> None:
    import personal_os

    assert personal_os.__version__ == "0.1.0"


def test_import_does_not_create_default_data_directory(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    environment.pop("PERSONAL_OS_DATA_DIR", None)

    result = subprocess.run(
        [sys.executable, "-c", "import personal_os"],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert not (home / ".personal-os").exists()
