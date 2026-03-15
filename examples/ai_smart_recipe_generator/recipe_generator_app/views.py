"""recipe_generator_app views — session-authenticated recipe app."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from openviper.auth import authenticate, get_user_model, login, logout
from openviper.conf import settings
from openviper.http.response import HTMLResponse, RedirectResponse, Response
from recipe_generator_app.ai.mealplan_generator import get_mealplan_generator
from recipe_generator_app.ai.nutrition_analyzer import get_nutrition_analyzer
from recipe_generator_app.ai.recipe_generator import get_recipe_generator
from recipe_generator_app.models import (
    MealPlan,
    NutritionInfo,
    Recipe,
    ShoppingList,
    UserIngredients,
)

if TYPE_CHECKING:
    from openviper.http.request import Request

logger = logging.getLogger(__name__)

User = get_user_model()


def _get_ai_model() -> str:
    return getattr(settings, "AI_DEFAULT_MODEL", "gemini-2.5-flash")


def _is_authenticated(request: Request) -> bool:
    return (
        hasattr(request, "user")
        and request.user
        and getattr(request.user, "is_authenticated", False)
    )


def _login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=302)


# ---------------------------------------------------------------------------
# Home / Landing
# ---------------------------------------------------------------------------


async def home(request: Request) -> Response:
    """Public landing page."""
    if _is_authenticated(request):
        return RedirectResponse("/dashboard", status_code=302)
    return HTMLResponse(template="home.html", context={"title": "AI Smart Recipe Generator"})


# ---------------------------------------------------------------------------
# Auth Views
# ---------------------------------------------------------------------------


async def register_page(request: Request) -> Response:
    """Render the registration form (GET) or process registration (POST)."""
    if _is_authenticated(request):
        return RedirectResponse("/dashboard", status_code=302)

    if request.method == "POST":
        form = await request.form()
        username = str(form.get("username", "")).strip()
        email = str(form.get("email", "")).strip()
        password = str(form.get("password", ""))
        confirm = str(form.get("confirm_password", ""))
        first_name = str(form.get("first_name", "")).strip()
        last_name = str(form.get("last_name", "")).strip()

        error = None
        if not username or not email or not password:
            error = "Username, email, and password are required."
        elif password != confirm:
            error = "Passwords do not match."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            existing = await User.objects.filter(username=username).first()
            if existing:
                error = "Username already taken."
            else:
                existing_email = await User.objects.filter(email=email).first()
                if existing_email:
                    error = "Email already registered."

        if error:
            return HTMLResponse(
                template="register.html",
                context={"title": "Register", "error": error, "form": dict(form)},
            )

        user = User(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            is_active=True,
        )
        await user.set_password(password)
        await user.save()

        response = RedirectResponse("/dashboard", status_code=302)
        await login(request, user, response)
        return response

    return HTMLResponse(template="register.html", context={"title": "Register"})


async def login_page(request: Request) -> Response:
    """Render the login form (GET) or process login (POST)."""
    if _is_authenticated(request):
        return RedirectResponse("/dashboard", status_code=302)

    if request.method == "POST":
        form = await request.form()
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))

        user = await authenticate(username=username, password=password)
        if not user:
            return HTMLResponse(
                template="login.html",
                context={"title": "Login", "error": "Invalid username or password."},
            )

        response = RedirectResponse("/dashboard", status_code=303)
        await login(request, user, response)
        return response

    return HTMLResponse(template="login.html", context={"title": "Login"})


async def logout_page(request: Request) -> Response:
    """Invalidate session and redirect to login."""
    response = RedirectResponse("/login", status_code=302)
    await logout(request, response)
    return response


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


async def dashboard(request: Request) -> Response:
    """User dashboard — session protected."""
    # The user might not have the cookie yet on immediate redirect after login,
    # but request.user should be set by the login() call
    if not _is_authenticated(request):
        # If we just logged in, request.user would be set even without cookie
        return _login_redirect()

    user = request.user
    recipes = await Recipe.objects.filter(user=user.pk).all()
    meal_plans = await MealPlan.objects.filter(user=user.pk).all()

    return HTMLResponse(
        template="dashboard.html",
        context={
            "title": "Dashboard",
            "user": user,
            "recipes": recipes,
            "meal_plans": meal_plans,
            "recipe_count": len(recipes),
            "meal_plan_count": len(meal_plans),
        },
    )


# ---------------------------------------------------------------------------
# Ingredients
# ---------------------------------------------------------------------------


async def ingredients_page(request: Request) -> Response:
    """Manage ingredients — session protected."""
    if not _is_authenticated(request):
        return _login_redirect()

    user = request.user

    if request.method == "POST":
        form = await request.form()
        ingredient_str = str(form.get("ingredients", "")).strip()
        if ingredient_str:
            existing = await UserIngredients.objects.filter(user=user.pk).first()
            if existing:
                existing.ingredients = ingredient_str
                await existing.save()
            else:
                entry = UserIngredients(user=user.pk, ingredients=ingredient_str)
                await entry.save()
        return RedirectResponse("/ingredients", status_code=302)

    saved = await UserIngredients.objects.filter(user=user.pk).first()
    return HTMLResponse(
        template="ingredients.html",
        context={
            "title": "My Ingredients",
            "user": user,
            "saved_ingredients": saved.ingredients if saved else "",
        },
    )


# ---------------------------------------------------------------------------
# Recipe Generation
# ---------------------------------------------------------------------------


async def generate_recipes(request: Request) -> Response:
    """Generate AI recipes from user's ingredients — session protected."""
    if not _is_authenticated(request):
        return _login_redirect()

    user = request.user
    error = None
    recipes = []
    dietary_pref = ""

    if request.method == "POST":
        form = await request.form()
        ingredient_input = str(form.get("ingredients", "")).strip()
        dietary_pref = str(form.get("dietary_preferences", "")).strip()

        if not ingredient_input:
            saved = await UserIngredients.objects.filter(user=user.pk).first()
            ingredient_input = saved.ingredients if saved else ""

        if not ingredient_input:
            error = "Please provide ingredients to generate recipes."
        else:
            ingredient_list = [i.strip() for i in ingredient_input.split(",") if i.strip()]
            model_name = _get_ai_model()
            generator = get_recipe_generator(model_name)
            recipe_results = await generator.generate_multiple_recipes(
                ingredient_list, count=3, dietary_preferences=dietary_pref
            )

            for result in recipe_results:
                recipe = Recipe(
                    user=user.pk,
                    title=result.title,
                    ingredients=result.ingredients_text(),
                    instructions=result.instructions_text(),
                    servings=result.servings,
                    prep_time=result.prep_time,
                    cook_time=result.cook_time,
                )
                await recipe.save()
                recipes.append(recipe)

    saved = await UserIngredients.objects.filter(user=user.pk).first()
    return HTMLResponse(
        template="ingredients.html",
        context={
            "title": "Generate Recipes",
            "user": user,
            "saved_ingredients": saved.ingredients if saved else "",
            "generated_recipes": recipes,
            "dietary_preferences": dietary_pref,
            "error": error,
            "show_results": bool(recipes),
        },
    )


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------


async def recipes_list(request: Request) -> Response:
    """List all user recipes — session protected."""
    if not _is_authenticated(request):
        return _login_redirect()

    user = request.user
    recipes = await Recipe.objects.filter(user=user.pk).all()
    return HTMLResponse(
        template="recipe_list.html",
        context={"title": "My Recipes", "user": user, "recipes": recipes},
    )


async def recipe_detail(request: Request, recipe_id: int) -> Response:
    """View a single recipe — session protected."""
    if not _is_authenticated(request):
        return _login_redirect()

    user = request.user
    recipe = await Recipe.objects.filter(id=recipe_id, user=user.pk).first()
    if not recipe:
        return HTMLResponse(
            template="recipe_list.html",
            context={
                "title": "My Recipes",
                "user": user,
                "recipes": [],
                "error": "Recipe not found.",
            },
            status_code=404,
        )

    nutrition = await NutritionInfo.objects.filter(recipe=recipe_id, user=user.pk).first()
    return HTMLResponse(
        template="recipe.html",
        context={
            "title": recipe.title,
            "user": user,
            "recipe": recipe,
            "nutrition": nutrition,
        },
    )


async def recipe_nutrition(request: Request, recipe_id: int) -> Response:
    """Analyze nutrition for a recipe — session protected."""
    if not _is_authenticated(request):
        return _login_redirect()

    user = request.user
    recipe = await Recipe.objects.filter(id=recipe_id, user=user.pk).first()
    if not recipe:
        return RedirectResponse("/recipes", status_code=302)

    model_name = _get_ai_model()
    analyzer = get_nutrition_analyzer(model_name)
    ingredient_list = [line.strip() for line in recipe.ingredients.splitlines() if line.strip()]
    result = await analyzer.analyze_recipe(recipe.title, ingredient_list, recipe.servings or "4")

    existing = await NutritionInfo.objects.filter(recipe=recipe_id, user=user.pk).first()
    if existing:
        existing.calories = result.calories
        existing.protein = result.protein
        existing.carbohydrates = result.carbohydrates
        existing.fat = result.fat
        existing.fiber = result.fiber
        existing.notes = result.notes
        await existing.save()
    else:
        info = NutritionInfo(
            recipe=recipe_id,
            user=user.pk,
            calories=result.calories,
            protein=result.protein,
            carbohydrates=result.carbohydrates,
            fat=result.fat,
            fiber=result.fiber,
            notes=result.notes,
        )
        await info.save()

    return RedirectResponse(f"/recipes/{recipe_id}", status_code=302)


# ---------------------------------------------------------------------------
# Meal Plans
# ---------------------------------------------------------------------------


async def mealplan_page(request: Request) -> Response:
    """Generate or view meal plans — session protected."""
    if not _is_authenticated(request):
        return _login_redirect()

    user = request.user
    meal_plans = await MealPlan.objects.filter(user=user.pk).all()
    saved = await UserIngredients.objects.filter(user=user.pk).first()

    if request.method == "POST":
        form = await request.form()
        ingredient_input = str(form.get("ingredients", "")).strip()
        dietary_pref = str(form.get("dietary_preferences", "")).strip()
        days_str = str(form.get("days", "7")).strip()
        days = int(days_str) if days_str.isdigit() and 1 <= int(days_str) <= 7 else 7

        if not ingredient_input and saved:
            ingredient_input = saved.ingredients

        ingredient_list = [i.strip() for i in ingredient_input.split(",") if i.strip()]
        model_name = _get_ai_model()
        generator = get_mealplan_generator(model_name)
        result = await generator.generate_weekly_plan(
            ingredient_list, dietary_preferences=dietary_pref, days=days
        )

        meal_plan = MealPlan(
            user=user.pk,
            title=result.title,
            plan_data=result.to_json(),
        )
        await meal_plan.save()

        if result.shopping_items:
            shopping = ShoppingList(
                user=user.pk,
                meal_plan=meal_plan.pk,
                items=json.dumps(result.shopping_items),
            )
            await shopping.save()

        return RedirectResponse(f"/mealplan/{meal_plan.pk}", status_code=302)

    return HTMLResponse(
        template="mealplan.html",
        context={
            "title": "Meal Plans",
            "user": user,
            "meal_plans": meal_plans,
            "saved_ingredients": saved.ingredients if saved else "",
        },
    )


async def mealplan_detail(request: Request, plan_id: int) -> Response:
    """View a meal plan — session protected."""
    if not _is_authenticated(request):
        return _login_redirect()

    user = request.user
    plan = await MealPlan.objects.filter(id=plan_id, user=user.pk).first()
    if not plan:
        return RedirectResponse("/mealplan", status_code=302)

    try:
        plan_data = json.loads(plan.plan_data)
    except json.JSONDecodeError, TypeError:
        plan_data = {}

    shopping = await ShoppingList.objects.filter(meal_plan=plan_id, user=user.pk).first()
    shopping_items = []
    if shopping:
        try:
            shopping_items = json.loads(shopping.items)
        except json.JSONDecodeError, TypeError:
            shopping_items = []

    return HTMLResponse(
        template="mealplan_detail.html",
        context={
            "title": plan.title,
            "user": user,
            "plan": plan,
            "plan_data": plan_data,
            "days": list(plan_data.keys()),
            "shopping_items": shopping_items,
        },
    )


# ---------------------------------------------------------------------------
# Shopping List
# ---------------------------------------------------------------------------


async def shopping_list(request: Request) -> Response:
    """View all shopping lists — session protected."""
    if not _is_authenticated(request):
        return _login_redirect()

    user = request.user
    lists = await ShoppingList.objects.filter(user=user.pk).all()
    parsed_lists = []
    for sl in lists:
        try:
            items = json.loads(sl.items)
        except json.JSONDecodeError, TypeError:
            items = []
        parsed_lists.append({"id": sl.pk, "item_list": items, "created_at": sl.created_at})

    return HTMLResponse(
        template="shoppinglist.html",
        context={
            "title": "Shopping Lists",
            "user": user,
            "shopping_lists": parsed_lists,
        },
    )


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


async def profile_page(request: Request) -> Response:
    """User profile — session protected."""
    if not _is_authenticated(request):
        return _login_redirect()

    user = request.user
    error = None
    success = None

    if request.method == "POST":
        form = await request.form()
        first_name = str(form.get("first_name", "")).strip()
        last_name = str(form.get("last_name", "")).strip()
        new_password = str(form.get("new_password", ""))
        confirm_password = str(form.get("confirm_password", ""))

        if new_password:
            if new_password != confirm_password:
                error = "Passwords do not match."
            elif len(new_password) < 6:
                error = "Password must be at least 6 characters."
            else:
                await user.set_password(new_password)

        if not error:
            user.first_name = first_name
            user.last_name = last_name
            await user.save()
            success = "Profile updated successfully."

    recipe_count = len(await Recipe.objects.filter(user=user.pk).all())
    meal_plan_count = len(await MealPlan.objects.filter(user=user.pk).all())

    return HTMLResponse(
        template="profile.html",
        context={
            "title": "My Profile",
            "user": user,
            "error": error,
            "success": success,
            "recipe_count": recipe_count,
            "meal_plan_count": meal_plan_count,
        },
    )
