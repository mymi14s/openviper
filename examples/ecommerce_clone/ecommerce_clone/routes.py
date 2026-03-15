"""Routes for Ecommerce Clone apps."""

from cart.routes import router as cart_router
from chat.routes import router as chat_router
from orders.routes import router as orders_router
from products.routes import router as products_router
from reviews.routes import router as reviews_router
from users.routes import router as users_router

from openviper.admin import get_admin_site

from .views import router as root_router

route_paths = [
    ("/", root_router),
    ("/admin", get_admin_site()),
    ("/api", users_router),
    ("/api", products_router),
    ("/api", cart_router),
    ("/api", orders_router),
    ("/api", reviews_router),
    ("/api", chat_router),
]
