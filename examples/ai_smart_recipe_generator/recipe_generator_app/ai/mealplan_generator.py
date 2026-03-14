"""AI-powered meal plan generator module."""

from __future__ import annotations

import json
import logging
from typing import Any

from openviper.ai.router import ModelRouter

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
        self.plan = plan  # {day: {meal: recipe_name}}
        self.shopping_items = shopping_items or []
        self.available = available

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "plan": self.plan,
            "shopping_items": self.shopping_items,
        }

    def to_json(self) -> str:
        return json.dumps(self.plan)

    def days(self) -> list[str]:
        return list(self.plan.keys())


class MealPlanGenerator:
    """AI-powered meal plan generator.

    Organises recipes into daily/weekly meal plans using AI.

    Example::

        generator = MealPlanGenerator(model_name="llama3")
        plan = await generator.generate_weekly_plan(["pasta", "chicken", "vegetables"])
    """

    def __init__(self, model_name: str = "llama3") -> None:
        self.model_name = model_name
        self._router = ModelRouter()
        self._available = False
        self._init_router()

    def _init_router(self) -> None:
        try:
            self._router.set_model(self.model_name)
            self._router._get_provider()
            self._available = True
            logger.info("MealPlanGenerator: using model '%s'", self.model_name)
        except Exception as exc:
            logger.warning(
                "MealPlanGenerator: model '%s' not available — %s", self.model_name, exc
            )
            self._available = False

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
        if not self._available:
            return self._fallback_plan(days)

        ingredient_str = ", ".join(ingredients)
        pref_note = f" Dietary preference: {dietary_preferences}." if dietary_preferences else ""
        day_list = DAYS_OF_WEEK[:days]

        prompt = (
            "You are a professional nutritionist AI. Create a meal plan for the following days.\n"
            "Respond ONLY with valid JSON (no markdown, no extra text):\n"
            '{"title": "Weekly Meal Plan", '
            '"plan": {"Monday": {"breakfast": "meal name", "lunch": "meal name", "dinner": "meal name"}, ...}, '
            '"shopping_items": ["item 1", "item 2", ...]}\n\n'
            f"Available ingredients: {ingredient_str}.{pref_note}\n"
            f"Days to plan: {', '.join(day_list)}\n\n"
            "Respond with valid JSON only:"
        )

        try:
            raw = await self._router.generate(prompt, temperature=0.7)
            return self._parse_plan(raw, days)
        except Exception as exc:
            logger.error("MealPlanGenerator: generation failed — %s", exc)
            return self._fallback_plan(days)

    def _parse_plan(self, raw: str, days: int) -> MealPlanResult:
        text = raw.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        if "{" in text and "}" in text:
            text = text[text.find("{"):text.rfind("}") + 1]

        try:
            data = json.loads(text)
            plan = data.get("plan", {})
            if not plan:
                return self._fallback_plan(days)
            return MealPlanResult(
                title=str(data.get("title", "Weekly Meal Plan")),
                plan=plan,
                shopping_items=list(data.get("shopping_items", [])),
            )
        except (json.JSONDecodeError, KeyError):
            return self._fallback_plan(days)

    def _fallback_plan(self, days: int = 7) -> MealPlanResult:
        plan = {}
        sample_meals = {
            "breakfast": ["Oatmeal", "Scrambled Eggs", "Toast with Avocado",
                          "Yogurt Parfait", "Pancakes", "Smoothie Bowl", "Cereal"],
            "lunch": ["Caesar Salad", "Chicken Sandwich", "Vegetable Soup",
                      "Pasta Salad", "Tuna Wrap", "Grain Bowl", "BLT"],
            "dinner": ["Grilled Chicken", "Pasta Primavera", "Stir Fry",
                       "Salmon with Vegetables", "Beef Tacos", "Lentil Curry", "Pizza"],
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


# Module-level cache keyed by model name
_generators: dict[str, MealPlanGenerator] = {}


def get_mealplan_generator(model_name: str = "gemini-2.5-flash") -> MealPlanGenerator:
    """Return a cached :class:`MealPlanGenerator` for *model_name*."""
    if model_name not in _generators:
        _generators[model_name] = MealPlanGenerator(model_name=model_name)
    return _generators[model_name]
