"""AI-powered meal plan generator module."""

from __future__ import annotations

import json
import logging

from recipe_generator_app.ai.base import (
    AIServiceBase,
    JsonValue,
    cached_factory,
    format_ingredients,
    strip_ai_json_response,
)

logger = logging.getLogger(__name__)

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MEALS = ["breakfast", "lunch", "dinner"]


class MealPlanResult:
    """Result from the meal plan generator."""

    def __init__(
        self,
        title: str,
        plan: dict[str, dict[str, str]],
        shopping_items: list[str] | None = None,
        available: bool = True,
    ) -> None:
        self.title = title
        self.plan = plan
        self.shopping_items = shopping_items or []
        self.available = available

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "title": self.title,
            "plan": self.plan,
            "shopping_items": self.shopping_items,
        }

    def to_json(self) -> str:
        return json.dumps(self.plan)

    def days(self) -> list[str]:
        return list(self.plan.keys())


class MealPlanGenerator(AIServiceBase):
    """AI-powered meal plan generator.

    Organises recipes into daily/weekly meal plans using AI.

    Example::

        generator = MealPlanGenerator(model_name="llama3")
        plan = await generator.generate_weekly_plan(["pasta", "chicken", "vegetables"])
    """

    default_model = "llama3"

    async def generate_weekly_plan(
        self,
        ingredients: list[str],
        dietary_preferences: str = "",
        days: int = 7,
    ) -> MealPlanResult:
        """Generate a weekly meal plan.

        Args:
            ingredients: Available ingredients.
            dietary_preferences: Optional dietary constraints.
            days: Number of days to plan (default 7).

        Returns:
            :class:`MealPlanResult` with day-by-day meal plan and shopping list.
        """
        if not self.available:
            return self.fallback_plan(days)

        ingredient_str, pref_note = format_ingredients(ingredients, dietary_preferences)
        day_list = DAYS_OF_WEEK[:days]

        prompt = (
            "You are a professional nutritionist AI. Create a meal plan for the following days.\n"
            "Respond ONLY with valid JSON (no markdown, no extra text):\n"
            '{"title": "Weekly Meal Plan", '
            '"plan": {"Monday": {"breakfast": "meal name", '
            '"lunch": "meal name", "dinner": "meal name"}, ...}, '
            '"shopping_items": ["item 1", "item 2", ...]}\n\n'
            f"Available ingredients: {ingredient_str}.{pref_note}\n"
            f"Days to plan: {', '.join(day_list)}\n\n"
            "Respond with valid JSON only:"
        )

        try:
            raw = await self.router.generate(prompt, temperature=0.7)
            return self.parse_plan(raw, days)
        except Exception as exc:
            logger.error("MealPlanGenerator: generation failed - %s", exc)
            return self.fallback_plan(days)

    def parse_plan(self, raw: str, days: int) -> MealPlanResult:
        text = strip_ai_json_response(raw)

        try:
            data = json.loads(text)
            plan = data.get("plan", {})
            if not plan:
                return self.fallback_plan(days)
            return MealPlanResult(
                title=str(data.get("title", "Weekly Meal Plan")),
                plan=plan,
                shopping_items=list(data.get("shopping_items", [])),
            )
        except (json.JSONDecodeError, KeyError):
            return self.fallback_plan(days)

    def fallback_plan(self, days: int = 7) -> MealPlanResult:
        plan = {}
        sample_meals = {
            "breakfast": [
                "Oatmeal",
                "Scrambled Eggs",
                "Toast with Avocado",
                "Yogurt Parfait",
                "Pancakes",
                "Smoothie Bowl",
                "Cereal",
            ],
            "lunch": [
                "Caesar Salad",
                "Chicken Sandwich",
                "Vegetable Soup",
                "Pasta Salad",
                "Tuna Wrap",
                "Grain Bowl",
                "BLT",
            ],
            "dinner": [
                "Grilled Chicken",
                "Pasta Primavera",
                "Stir Fry",
                "Salmon with Vegetables",
                "Beef Tacos",
                "Lentil Curry",
                "Pizza",
            ],
        }
        for i, day in enumerate(DAYS_OF_WEEK[:days]):
            plan[day] = {
                "breakfast": sample_meals["breakfast"][i % len(sample_meals["breakfast"])],
                "lunch": sample_meals["lunch"][i % len(sample_meals["lunch"])],
                "dinner": sample_meals["dinner"][i % len(sample_meals["dinner"])],
            }
        return MealPlanResult(
            title="Weekly Meal Plan",
            plan=plan,
            shopping_items=["Assorted vegetables", "Proteins of choice", "Grains", "Dairy"],
            available=False,
        )


generators: dict[str, MealPlanGenerator] = {}


def get_mealplan_generator(model_name: str = "gemini-2.5-flash") -> MealPlanGenerator:
    """Return a cached :class:`MealPlanGenerator` for *model_name*."""
    return cached_factory(generators, MealPlanGenerator, model_name)
