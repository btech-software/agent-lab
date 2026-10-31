import logging
import os
import re
from dataclasses import dataclass, field
from importlib import resources
from urllib.parse import urlencode

from dependency_injector import providers
from fastapi import APIRouter, FastAPI, HTTPException, Request
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles
from typing_extensions import List, Optional, Sequence

from agent_lab.core.config import ConfigSource, default_config_source, load_config
from agent_lab.core.container import Container
from agent_lab.infrastructure.auth.user import map_user
from agent_lab.infrastructure.metrics.logging_middleware import LoggingMiddleware
from agent_lab.interface.mcp import bootstrap as mcp_bootstrap
from agent_lab.interface.mcp.server import build_mcp_server
from agent_lab.services.agent_types import discovery
from agent_lab.services.agent_types.registry import AgentRegistry

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Scanned when create_app() is called without scan_packages: Agent-Lab's own
# agents and MCP capabilities. An explicit scan_packages list *replaces* these
# defaults — include them (e.g. [*DEFAULT_SCAN_PACKAGES, "myapp.agents"]) to
# keep the built-ins, or list individual modules to cherry-pick.
DEFAULT_SCAN_PACKAGES: Sequence[str] = (
    "agent_lab.services.agent_types",
    "agent_lab.interface.mcp",
)


@dataclass(frozen=True)
class RouterMount:
    """A router plus the auth policy for its routes.

    Patterns in ``auth_exclude_patterns`` are added to the Keycloak middleware
    exclude list, so a mount without them defaults to authenticated.
    """

    router: APIRouter
    prefix: str
    tags: List[str]
    auth_exclude_patterns: List[str] = field(default_factory=list)
    requires_auth_enabled: bool = False


def create_app(
    *,
    container: Optional[Container] = None,
    scan_packages: Optional[Sequence[str]] = None,
    config_source: Optional[ConfigSource] = None,
    extra_routers: Sequence[RouterMount] = (),
    mcp_instructions: Sequence[str] = (),
) -> FastAPI:
    """Builds the FastAPI application (composition root).

    Downstream apps pass their own container subclass instance, the packages
    to scan for discoverable capabilities (agents, MCP tools, prompts, and
    registrars), a config source, extra RouterMounts, and MCP instruction
    fragments — extension happens through these parameters, never by editing
    library code.

    Omitting ``scan_packages`` scans ``DEFAULT_SCAN_PACKAGES`` (all built-in
    capabilities); an explicit list replaces the defaults, so a capability not
    reachable from the scan is simply absent from the app.
    """
    if scan_packages is None:
        scan_packages = DEFAULT_SCAN_PACKAGES
    discovery.scan_packages(scan_packages)
    discovery.load_entry_point_agents()

    container = container or Container()
    wire_framework_modules(container)
    load_config(container, config_source or default_config_source())
    bind_agent_registry(container)

    mounts = _builtin_router_mounts() + list(extra_routers)

    mcp_bootstrap.load_framework_registrars()
    mcp_registrars = mcp_bootstrap.build_registrars(container)
    mcp_server = build_mcp_server(
        container, mcp_registrars, extra_instructions=tuple(mcp_instructions)
    )
    mcp_app = mcp_server.http_app(path="/", stateless_http=True)

    application = FastAPI(
        title=os.getenv("SERVICE_NAME", "Agent-Lab"),
        version=os.getenv("SERVICE_VERSION", "snapshot"),
        dependencies=[],
        lifespan=mcp_app.lifespan,
    )
    application.container = container

    setup_tracing(container, application)
    setup_auth(container, application, mounts)
    setup_routers(container, application, mounts)
    application.mount("/mcp", mcp_app)
    setup_resource_metadata(container, application)
    setup_exception_handlers(application)
    setup_middleware(application)
    setup_mcp_slash_rewrite(application)
    setup_mcp_authorize_resource_rewrite(container, application)
    setup_static(container, application)

    return application


def wire_framework_modules(container: Container) -> None:
    """Wires the framework endpoint modules to a live container instance.

    dependency-injector does not inherit ``wiring_config`` on container
    subclasses (a subclass gets a fresh, empty configuration), so a downstream
    ``Container`` subclass would silently lose endpoint injection and every
    DI-injected endpoint would 500. Like ``bind_agent_registry``, the binding
    happens at the composition root so any container instance works.
    """
    container.wire(modules=Container.wiring_config.modules)


def bind_agent_registry(container: Container) -> None:
    """Binds the agent registry to a live container instance.

    create_app() calls this automatically; call it directly only when using a
    Container outside the app factory (tests, notebooks, scripts). The
    registry resolves each agent's extra_deps off the live container
    instance; providers.Self() breaks under container subclassing, so the
    binding happens at the composition root.
    """
    container.agent_registry.override(
        providers.Singleton(AgentRegistry, container=container)
    )


def _builtin_router_mounts() -> List[RouterMount]:
    from agent_lab.interface.api.agents.endpoints import router as agents_router
    from agent_lab.interface.api.attachments.endpoints import (
        router as attachments_router,
    )
    from agent_lab.interface.api.auth.endpoints import router as auth_router
    from agent_lab.interface.api.integrations.endpoints import (
        router as integrations_router,
    )
    from agent_lab.interface.api.language_models.endpoints import (
        router as language_models_router,
    )
    from agent_lab.interface.api.messages.endpoints import router as messages_router
    from agent_lab.interface.api.status.endpoints import router as status_router

    return [
        RouterMount(auth_router, "/auth", ["auth"], requires_auth_enabled=True),
        RouterMount(agents_router, "/agents", ["agents"]),
        RouterMount(attachments_router, "/attachments", ["attachments"]),
        RouterMount(integrations_router, "/integrations", ["integrations"]),
        RouterMount(language_models_router, "/llms", ["llms"]),
        RouterMount(messages_router, "/messages", ["messages"]),
        RouterMount(status_router, "/status", ["status"]),
    ]


def setup_auth(container, application, mounts: List[RouterMount]):
    config = container.config()
    if config["auth"]["enabled"]:
        from fastapi_keycloak_middleware import (
            KeycloakConfiguration,
            setup_keycloak_middleware,
        )

        keycloak_config = KeycloakConfiguration(
            url=config["auth"]["url"],
            realm=config["auth"]["realm"],
            client_id=config["auth"]["client_id"],
            client_secret=config["auth"]["client_secret"],
        )

        exclude_patterns = [
            "/auth/login(/|$)",
            "/auth/renew(/|$)",
            "/auth/exchange(/|$)",
            "/openapi.json(/|$)",
            # matched with re.fullmatch: each entry must cover the whole path
            "/status(/.*)?$",
            r"/\.well-known(/.*)?$",
            "/mcp(/.*)?$",
            "/static(/.*)?$",
        ]
        for mount in mounts:
            exclude_patterns.extend(mount.auth_exclude_patterns)

        spa_pattern = _spa_auth_exclude_pattern(mounts, config.get("static") or {})
        if spa_pattern:
            exclude_patterns.append(spa_pattern)

        setup_keycloak_middleware(
            application,
            keycloak_configuration=keycloak_config,
            exclude_patterns=exclude_patterns,
            user_mapper=map_user,
        )

    else:
        logger.warning("Authentication disabled")


# Framework paths that must stay behind auth (or keep their own auth) even
# though they are not RouterMounts: the MCP server, the OpenAPI docs, and the
# branding/static-logo route.
_RESERVED_PROTECTED_PREFIXES = ["mcp", "static", "docs", "redoc", "openapi.json"]


def _spa_auth_exclude_pattern(
    mounts: List[RouterMount], static_config: dict
) -> Optional[str]:
    """Auth exclusion that makes a root-mounted static SPA publicly reachable.

    A SPA needs *every* non-API path to bypass auth so unknown deep links fall
    through to ``index.html`` (the auth middleware answers 401 before routing,
    so the 404→index fallback never sees them otherwise). Rather than list the
    public paths, we derive the protected surface — the API router prefixes plus
    a few reserved framework paths — and exclude everything else via a negative
    lookahead. This can't drift as the frontend adds routes.

    Only applies when static serving is enabled at ``mount_path: "/"``; a static
    mount under a sub-path leaves the default-authenticated model untouched.
    """
    if not static_config.get("enabled", False):
        return None
    if static_config.get("mount_path", "/") != "/":
        return None

    protected = [mount.prefix.strip("/") for mount in mounts]
    protected += _RESERVED_PROTECTED_PREFIXES
    alternation = "|".join(re.escape(prefix) for prefix in protected)
    return rf"^/(?!(?:{alternation})(?:/|$)).*"


def setup_resource_metadata(container: Container, application: FastAPI):
    config = container.config()
    if not config["auth"]["enabled"]:
        return

    base_url = config["api_base_url"]
    authorization_server = f"{base_url}/mcp"

    def build_resource_metadata(request: Request) -> dict:
        user_agent = request.headers.get("user-agent") or ""
        resource = base_url if not user_agent else f"{base_url}/mcp"
        return {
            "resource": resource,
            "authorization_servers": [authorization_server],
            "scopes_supported": ["openid", "profile", "email"],
            "bearer_methods_supported": ["header"],
        }

    @application.get("/.well-known/oauth-protected-resource/mcp")
    async def oauth_protected_resource_metadata(request: Request):
        return JSONResponse(build_resource_metadata(request))

    @application.get("/.well-known/oauth-protected-resource/mcp/")
    async def oauth_protected_resource_metadata_slash(request: Request):
        return JSONResponse(build_resource_metadata(request))

    auth_server_metadata = {
        "issuer": authorization_server,
        "authorization_endpoint": f"{authorization_server}/authorize",
        "token_endpoint": f"{authorization_server}/token",
        "registration_endpoint": f"{authorization_server}/register",
        "scopes_supported": ["openid", "profile", "email"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_post",
            "client_secret_basic",
        ],
        "code_challenge_methods_supported": ["S256"],
    }

    @application.get("/.well-known/oauth-authorization-server/mcp")
    async def oauth_authorization_server_metadata():
        return JSONResponse(auth_server_metadata)

    @application.get("/.well-known/oauth-authorization-server/mcp/")
    async def oauth_authorization_server_metadata_slash():
        return JSONResponse(auth_server_metadata)


def setup_routers(
    container: Container, application: FastAPI, mounts: List[RouterMount]
):
    config = container.config()
    for mount in mounts:
        if mount.requires_auth_enabled and not config["auth"]["enabled"]:
            continue
        application.include_router(mount.router, prefix=mount.prefix, tags=mount.tags)


def setup_exception_handlers(application: FastAPI):
    @application.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        match = re.match(r"^(\d+):", exc.detail)
        if match:
            status_code = int(match.group(1))
            detail = exc.detail[len(match.group(0)) :].strip()
        else:
            status_code = exc.status_code
            detail = exc.detail

        return JSONResponse(
            status_code=status_code,
            content={"detail": detail},
        )


def setup_tracing(container: Container, application: FastAPI):
    tracer = container.tracer()
    tracer.setup(application)


def setup_middleware(application: FastAPI):
    application.add_middleware(
        LoggingMiddleware,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def setup_mcp_slash_rewrite(application: FastAPI):
    @application.middleware("http")
    async def mcp_slash_rewrite(request: Request, call_next):
        if request.url.path == "/mcp":
            scope = request.scope
            scope["path"] = "/mcp/"
            scope["raw_path"] = b"/mcp/"
        return await call_next(request)


def setup_mcp_authorize_resource_rewrite(container: Container, application: FastAPI):
    config = container.config()
    if not config["auth"]["enabled"]:
        return

    bare = config["api_base_url"].rstrip("/")
    target = f"{bare}/mcp"

    def is_bare(value: str) -> bool:
        return value.rstrip("/") == bare

    @application.middleware("http")
    async def mcp_authorize_resource_rewrite(request: Request, call_next):
        if request.url.path == "/mcp/authorize":
            items = list(request.query_params.multi_items())
            if any(k == "resource" and is_bare(v) for k, v in items):
                rewritten = [
                    (k, target if (k == "resource" and is_bare(v)) else v)
                    for k, v in items
                ]
                request.scope["query_string"] = urlencode(rewritten).encode("ascii")
        return await call_next(request)


def setup_static(container: Container, application: FastAPI):
    _setup_branding(application)
    _setup_spa_fallback(container, application)


def _setup_spa_fallback(container: Container, application: FastAPI):
    """Serves a static site (e.g. a SPA build) from a configured directory.

    Gated behind the optional ``static.enabled`` config key and a no-op by
    default. The 404→index fallback fires on any HTML-accepting 404 site-wide,
    which is only correct for ``mount_path: "/"`` (the default). A configured
    but missing directory fails fast at boot.
    """
    static_config = container.config().get("static") or {}
    if not static_config.get("enabled", False):
        return

    directory = static_config["directory"]
    index_file = os.path.join(directory, static_config.get("index_file", "index.html"))

    @application.middleware("http")
    async def spa_fallback(request: Request, call_next):
        response = await call_next(request)
        accept = request.headers.get("accept", "")
        if response.status_code == 404 and "text/html" in accept:
            return FileResponse(index_file)
        return response

    application.mount(
        path=static_config.get("mount_path", "/"),
        app=StaticFiles(directory=directory, html=True),
        name="static",
    )


def _setup_branding(application: FastAPI):
    # Resolved via importlib.resources so the logo is found when agent_lab is
    # an installed wheel, independent of the process working directory.
    logo_file = str(resources.files("agent_lab").joinpath("static", "logo.svg"))

    # Cache-Control is set on the FileResponse directly: FastAPI only merges
    # dependency-set headers (e.g. cache_control()) into non-Response returns.
    @application.get("/static/logo.svg")
    async def logo() -> FileResponse:
        return FileResponse(
            logo_file,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400, s-maxage=86400"},
        )
