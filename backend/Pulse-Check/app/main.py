import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# limiter is defined here (before the router import) so that monitors.py can
# safely do `from app.main import limiter` without triggering a circular-import error.
limiter = Limiter(key_func=get_remote_address)

from app.database import Base, engine  # noqa: E402
from app.routers.api_keys import router as api_keys_router  # noqa: E402
from app.routers.auth import router as auth_router  # noqa: E402
from app.routers.monitors import router as monitors_router  # noqa: E402
from app.security import verify_jwt  # noqa: E402
from app.services.scheduler import start_scheduler, stop_scheduler, startup_check  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Pulse-Check API starting up...")

    # Create all tables (Alembic handles versioned migrations in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema verified")

    # Detect any monitors that timed out while the server was down
    await startup_check()

    start_scheduler()
    logger.info("Pulse-Check API is ready")

    yield  # API serves requests here

    stop_scheduler()
    await engine.dispose()
    logger.info("Pulse-Check API shut down cleanly")


app = FastAPI(
    title="Pulse-Check API",
    description=(
        "Dead Man's Switch monitoring for remote IoT devices. "
        "Powered by Claude AI. — CritMon Servers Inc."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Pulse-Check API",
        version="1.0.0",
        description=(
            "Dead Man's Switch monitoring for remote IoT devices. "
            "Powered by Claude AI. — CritMon Servers Inc.\n\n"
            "## Authentication\n\n"
            "### For Engineers (JWT)\n"
            "1. Register at POST /auth/register\n"
            "2. Login at POST /auth/login to get token\n"
            "3. Click Authorize button and enter: Bearer <your_token>\n\n"
            "### For Devices (API Key)\n"
            "1. Engineer generates key at POST /api-keys/generate\n"
            "2. Use key in X-API-Key header\n"
        ),
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Enter JWT token for engineer access",
        },
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "Enter API key for device access",
        },
    }
    openapi_schema["security"] = [
        {"BearerAuth": []},
        {"ApiKeyAuth": []},
    ]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # Restrict to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


app.add_middleware(RequestIDMiddleware)

app.include_router(auth_router)
app.include_router(monitors_router)
app.include_router(api_keys_router)


@app.get("/health", tags=["health"], dependencies=[Depends(verify_jwt)])
async def health_check():
    return {"status": "ok", "service": "Pulse-Check API", "version": "1.0.0"}
