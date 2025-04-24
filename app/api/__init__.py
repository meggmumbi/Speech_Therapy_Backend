from .activities import router as activities_router
from .auth import router as auth_router
from .children import router as children_router

__all__ = ["activities_router", "auth_router", "children_router"]