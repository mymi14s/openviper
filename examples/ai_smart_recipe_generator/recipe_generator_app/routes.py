"""recipe_generator_app routes."""

from openviper.routing import Router
from recipe_generator_app.views import (
    dashboard,
    generate_recipes,
    home,
    ingredients_page,
    login_page,
    logout_page,
    mealplan_detail,
    mealplan_page,
    profile_page,
    recipe_detail,
    recipe_nutrition,
    recipes_list,
    register_page,
    shopping_list,
)

router = Router(prefix="")

# Public routes
router.add("/", home, methods=["GET"])
router.add("/register", register_page, methods=["GET", "POST"])
router.add("/login", login_page, methods=["GET", "POST"])
router.add("/logout", logout_page, methods=["GET", "POST"])

# Protected routes
router.add("/dashboard", dashboard, methods=["GET"])
router.add("/ingredients", ingredients_page, methods=["GET", "POST"])
router.add("/ingredients/generate", generate_recipes, methods=["GET", "POST"])
router.add("/recipes", recipes_list, methods=["GET"])
router.add("/recipes/{recipe_id:int}", recipe_detail, methods=["GET"])
router.add("/recipes/{recipe_id:int}/nutrition", recipe_nutrition, methods=["POST"])
router.add("/mealplan", mealplan_page, methods=["GET", "POST"])
router.add("/mealplan/{plan_id:int}", mealplan_detail, methods=["GET"])
router.add("/shopping", shopping_list, methods=["GET"])
router.add("/profile", profile_page, methods=["GET", "POST"])
