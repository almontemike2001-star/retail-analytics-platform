"""Shared fixtures: an isolated temporary 'repository' with the real tables.yml and schema files."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from beanflow_ingest.config import load_config

INGESTION_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = INGESTION_DIR.parent


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "ingestion").mkdir(parents=True)
    shutil.copytree(INGESTION_DIR / "config", root / "ingestion" / "config")
    shutil.copytree(INGESTION_DIR / "schemas", root / "ingestion" / "schemas")
    return root


@pytest.fixture
def repo(tmp_path) -> Path:
    return make_repo(tmp_path)


@pytest.fixture
def cfg(repo):
    return load_config(repo_root=repo, env={})
