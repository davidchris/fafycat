"""Tests for the FastAPI app factory.

These cover concerns the packaging refactor changes directly: the static
files mount path, the app-state wiring, the router graph's import graph,
and the ``FAFYCAT_DATA_DIR`` env-var contract. Each assertion holds both
pre- and post-refactor.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def test_create_app_returns_fastapi_instance(app_factory):
    assert isinstance(app_factory(), FastAPI)


def test_create_app_is_idempotent(app_factory):
    """Two calls produce two distinct app instances (no hidden global app)."""
    assert app_factory() is not app_factory()


def test_app_has_state_config_and_db_manager(app_factory):
    app = app_factory()
    assert hasattr(app.state, "config")
    assert hasattr(app.state, "db_manager")


def test_app_uses_fafycat_data_dir_env(tmp_data_dir: Path, app_factory):
    """FAFYCAT_DATA_DIR flows through to ``app.state.config.data_dir``."""
    app = app_factory()
    assert Path(app.state.config.data_dir) == tmp_data_dir


def test_static_mount_exists(app_factory):
    """A ``/static`` route is mounted and backed by ``StaticFiles``."""
    app = app_factory()
    static_routes = [r for r in app.routes if getattr(r, "path", None) == "/static"]
    assert len(static_routes) == 1
    assert isinstance(static_routes[0].app, StaticFiles)


def test_static_mount_directory_exists_on_disk(app_factory):
    """The directory the app mounts must exist and contain css/ and js/.

    Pre-refactor it resolves relative to CWD; post-refactor it resolves
    to ``<package>/static``. Either way the directory must be real.
    """
    app = app_factory()
    static_route = next(r for r in app.routes if getattr(r, "path", None) == "/static")
    directory = Path(static_route.app.directory)
    assert directory.is_dir(), f"static mount directory does not exist: {directory}"
    assert (directory / "css").is_dir()
    assert (directory / "js").is_dir()


def test_openapi_schema_is_generatable(test_client):
    """``/openapi.json`` returns 200 — catches circular-import regressions."""
    resp = test_client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"] == "FafyCat - Family Finance Categorizer"
