from api.routes.servers import router as servers_router
from api.routes.metrics import router as metrics_router
from api.routes.android import router as android_router

__all__ = ["servers_router", "metrics_router", "android_router"]
