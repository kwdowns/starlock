"""The product version scheme (specs/start/SPEC_BUILD_RELEASE.md section 11)."""

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_version_is_plain_semver_and_matches_pyproject():
    app = json.loads((ROOT / "data" / "VERSION.json").read_text())["app_version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", app), f"{app!r} is not MAJOR.MINOR.PATCH"
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == app
