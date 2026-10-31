import os
import re
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from agent_lab.app_factory import (
    RouterMount,
    _setup_spa_fallback,
    _spa_auth_exclude_pattern,
)
from agent_lab.main import app


@pytest.fixture
def client():
    yield TestClient(app)


def _auth_headers():
    return {"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"}


class TestExceptionHandler:
    def test_http_exception_with_status_prefix(self, client):
        """Exception detail starting with 'NNN:' should override the status code."""
        # The auth endpoint raises AuthenticationError with status 401
        # and detail "Authentication failed: ...". We test via a real endpoint.
        response = client.post(
            "/auth/login",
            json={"username": "nonexistent", "password": "wrong"},
        )
        assert response.status_code == 401
        assert "detail" in response.json()

    def test_http_exception_with_409_prefix(self, client):
        """Exception detail starting with '409:' should return 409 status."""

        @client.app.get("/test-409-prefix")
        async def trigger_409():
            raise HTTPException(status_code=500, detail="409: Conflict occurred")

        response = client.get("/test-409-prefix", headers=_auth_headers())
        assert response.status_code == 409
        assert response.json()["detail"] == "Conflict occurred"

    def test_http_exception_without_prefix(self, client):
        """Exception without numeric prefix should keep original status code."""

        @client.app.get("/test-plain-error")
        async def trigger_plain():
            raise HTTPException(status_code=422, detail="Validation failed")

        response = client.get("/test-plain-error", headers=_auth_headers())
        assert response.status_code == 422
        assert response.json()["detail"] == "Validation failed"


class TestMcpSlashRewrite:
    def test_mcp_path_rewrite(self, client):
        """GET /mcp should be rewritten to /mcp/ and not return 404."""
        response = client.get("/mcp")
        # The MCP app is mounted at /mcp — a rewrite to /mcp/ should reach it
        assert response.status_code != 404

    def test_mcp_slash_path_works(self, client):
        """GET /mcp/ should work directly."""
        response = client.get("/mcp/")
        assert response.status_code != 404


class TestStaticBranding:
    def test_logo_served_with_svg_content_type(self, client):
        response = client.get("/static/logo.svg")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")

    def test_logo_has_cache_control_header(self, client):
        response = client.get("/static/logo.svg")
        assert "max-age" in response.headers.get("cache-control", "")


def _spa_app(static_config):
    container = MagicMock()
    container.config.return_value = (
        {"static": static_config} if static_config is not None else {}
    )
    application = FastAPI()
    _setup_spa_fallback(container, application)
    return application


class TestSpaFallback:
    def test_no_static_config_is_a_no_op(self):
        application = _spa_app(None)
        client = TestClient(application)
        assert client.get("/anything").status_code == 404

    def test_disabled_is_a_no_op(self, tmp_path):
        application = _spa_app({"enabled": False, "directory": str(tmp_path)})
        client = TestClient(application)
        assert client.get("/anything").status_code == 404

    def test_serves_static_files_when_enabled(self, tmp_path):
        (tmp_path / "asset.txt").write_text("asset-content")
        application = _spa_app({"enabled": True, "directory": str(tmp_path)})
        client = TestClient(application)
        response = client.get("/asset.txt")
        assert response.status_code == 200
        assert response.text == "asset-content"

    def test_html_404_falls_back_to_index(self, tmp_path):
        (tmp_path / "index.html").write_text("<html>spa-shell</html>")
        application = _spa_app({"enabled": True, "directory": str(tmp_path)})
        client = TestClient(application)
        response = client.get("/client/route", headers={"accept": "text/html"})
        assert response.status_code == 200
        assert "spa-shell" in response.text

    def test_non_html_404_stays_404(self, tmp_path):
        (tmp_path / "index.html").write_text("<html>spa-shell</html>")
        application = _spa_app({"enabled": True, "directory": str(tmp_path)})
        client = TestClient(application)
        response = client.get("/missing.json", headers={"accept": "application/json"})
        assert response.status_code == 404

    def test_custom_index_file(self, tmp_path):
        (tmp_path / "index.csr.html").write_text("<html>csr-shell</html>")
        application = _spa_app(
            {
                "enabled": True,
                "directory": str(tmp_path),
                "index_file": "index.csr.html",
            }
        )
        client = TestClient(application)
        response = client.get("/client/route", headers={"accept": "text/html"})
        assert "csr-shell" in response.text


class TestResourceMetadata:
    def test_oauth_protected_resource_metadata(self, client):
        response = client.get("/.well-known/oauth-protected-resource/mcp")
        assert response.status_code == 200
        data = response.json()
        assert "resource" in data
        assert "authorization_servers" in data
        assert "scopes_supported" in data
        assert "bearer_methods_supported" in data

    def test_oauth_protected_resource_metadata_trailing_slash(self, client):
        response = client.get("/.well-known/oauth-protected-resource/mcp/")
        assert response.status_code == 200

    def test_oauth_authorization_server_metadata(self, client):
        response = client.get("/.well-known/oauth-authorization-server/mcp")
        assert response.status_code == 200
        data = response.json()
        assert "issuer" in data
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "registration_endpoint" in data
        assert "code_challenge_methods_supported" in data
        assert "S256" in data["code_challenge_methods_supported"]

    def test_oauth_authorization_server_metadata_trailing_slash(self, client):
        response = client.get("/.well-known/oauth-authorization-server/mcp/")
        assert response.status_code == 200


class TestPublicPathAuth:
    @pytest.mark.parametrize("path", ["/status/liveness", "/status/readiness"])
    def test_status_probes_are_anonymous(self, client, path):
        assert client.get(path).status_code != 401

    @pytest.mark.parametrize(
        "path", ["/agents/list", "/static-evil/x", "/statusx", "/x/.well-known/y"]
    )
    def test_non_public_paths_still_require_auth(self, client, path):
        assert client.get(path).status_code == 401


class TestSpaAuthExclude:
    _mounts = [
        RouterMount(APIRouter(), "/agents", ["agents"]),
        RouterMount(APIRouter(), "/messages", ["messages"]),
        RouterMount(APIRouter(), "/auth", ["auth"]),
    ]

    def _pattern(self, static_config):
        return _spa_auth_exclude_pattern(self._mounts, static_config)

    def test_disabled_returns_none(self):
        assert self._pattern({"enabled": False}) is None

    def test_missing_config_returns_none(self):
        assert self._pattern({}) is None

    def test_sub_path_mount_returns_none(self):
        # Only a root-mounted SPA flips into the public-by-default model.
        assert self._pattern({"enabled": True, "mount_path": "/app"}) is None

    def test_public_paths_are_excluded(self):
        pattern = re.compile(self._pattern({"enabled": True}))
        for path in ("/", "/index.html", "/main-ABC123.js", "/favicon.ico"):
            assert pattern.match(path), path

    def test_spa_deep_links_are_excluded(self):
        pattern = re.compile(self._pattern({"enabled": True}))
        for path in ("/sobre", "/clientes/42", "/relatorios/2026/anual"):
            assert pattern.match(path), path

    def test_api_and_reserved_paths_are_not_excluded(self):
        pattern = re.compile(self._pattern({"enabled": True}))
        for path in (
            "/agents",
            "/agents/123",
            "/messages/abc",
            "/auth/token",
            "/mcp/",
            "/docs",
            "/openapi.json",
        ):
            assert not pattern.match(path), path
