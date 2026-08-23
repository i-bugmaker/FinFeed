from fastapi.testclient import TestClient
from finfeed.ui.web_fastapi.routers.realtime import LegacyNewsEventPublisher, create_router


async def _socket_handler(_websocket):
    return None


def test_realtime_router_owns_public_transport_routes():
    router = create_router(LegacyNewsEventPublisher(), _socket_handler)
    paths = {route.path for route in router.routes}

    assert {"/api/events", "/api/sse/health", "/ws/market"} <= paths


def test_application_exposes_realtime_health_endpoint():
    # FastAPI 0.11x+ keeps included routers lazily, so exercise dispatch rather
    # than inspecting app.routes directly.
    from finfeed.ui.web_fastapi.app import app

    response = TestClient(app).get("/api/sse/health")

    assert response.status_code == 200
    assert "watermark_initialized" in response.json()
