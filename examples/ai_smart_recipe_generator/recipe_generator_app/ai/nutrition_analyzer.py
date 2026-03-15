"""AI-powered nutrition analyzer module."""

from __future__ import annotations

import json
import logging
from typing import Any

from openviper.ai.router import ModelRouter

logger = logging.getLogger(__name__)


class NutritionResult:
    """Result from the nutrition analyzer."""

    def __init__(
        self,
        calories: str = "",
        protein: str = "",
        carbohydrates: str = "",
        fat: str = "",
        fiber: str = "",
        vitamins: list[str] | None = None,
        minerals: list[str] | None = None,
        dietary_tags: list[str] | None = None,
        notes: str = "",
        available: bool = True,
    ) -> None:
        self.calories = calories
        self.protein = protein
        self.carbohydrates = carbohydrates
        self.fat = fat
        self.fiber = fiber
        self.vitamins = vitamins or []
        self.minerals = minerals or []
        self.dietary_tags = dietary_tags or []
        self.notes = notes
        self.available = available

    def to_dict(self) -> dict[str, Any]:
        return {
            "calories": self.calories,
            "protein": self.protein,
            "carbohydrates": self.carbohydrates,
            "fat": self.fat,
            "fiber": self.fiber,
            "vitamins": self.vitamins,
            "minerals": self.minerals,
            "dietary_tags": self.dietary_tags,
            "notes": self.notes,
        }


class NutritionAnalyzer:
    """AI-powered nutrition analyzer.

    Analyzes recipes or ingredient lists to estimate nutritional content
    and check dietary compliance.

    Example::

        analyzer = NutritionAnalyzer(model_name="llama3")
        info = await analyzer.analyze_recipe("Grilled Chicken Salad", ingredients)
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
            logger.info("NutritionAnalyzer: using model '%s'", self.model_name)
        except Exception as exc:
            logger.warning("NutritionAnalyzer: model '%s' not available — %s", self.model_name, exc)
            self._available = False

    async def analyze_recipe(
        self,
        recipe_title: str,
        ingredients: list[str],
        servings: str = "4",
    ) -> NutritionResult:
        """Analyze the nutritional content of a recipe.

        Args:
            recipe_title: The name of the recipe.
            ingredients: List of ingredients used.
            servings: Number of servings the recipe makes.

        Returns:
            :class:`NutritionResult` with estimated nutritional information.
        """
        if not self._available:
            return self._fallback_nutrition()

        ingredient_str = "\n".join(f"- {ing}" for ing in ingredients)

        prompt = (
            "You are a registered dietitian AI. Analyze the nutritional content of the recipe provided.\n"  # noqa: E501
            "Respond ONLY with valid JSON (no markdown, no extra text).\n\n"
            "The JSON should follow this structure:\n"
            "{\n"
            '  "calories": "string, e.g., 320 kcal per serving",\n'
            '  "protein": "string, e.g., 25g",\n'
            '  "carbohydrates": "string, e.g., 40g",\n'
            '  "fat": "string, e.g., 8g",\n'
            '  "fiber": "string, e.g., 5g",\n'
            '  "vitamins": ["list of vitamins"],\n'
            '  "minerals": ["list of minerals"],\n'
            '  "dietary_tags": ["list of relevant dietary tags"],\n'
            '  "notes": "brief health or recipe note"\n'
            "}\n\n"
            f"Recipe: {recipe_title}\n"
            f"Ingredients ({servings} servings):\n{ingredient_str}\n\n"
            "Respond with valid JSON only, filling in the values based on the recipe above."
        )

        try:
            raw = await self._router.generate(prompt, temperature=0.3)
            return self._parse_nutrition(raw)
        except Exception as exc:
            logger.error("NutritionAnalyzer: analysis failed — %s", exc)
            return self._fallback_nutrition()

    def _parse_nutrition(self, raw: str) -> NutritionResult:
        text = raw.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        if "{" in text and "}" in text:
            text = text[text.find("{") : text.rfind("}") + 1]

        try:
            data = json.loads(text)
            return NutritionResult(
                calories=str(data.get("calories", "")),
                protein=str(data.get("protein", "")),
                carbohydrates=str(data.get("carbohydrates", "")),
                fat=str(data.get("fat", "")),
                fiber=str(data.get("fiber", "")),
                vitamins=list(data.get("vitamins", [])),
                minerals=list(data.get("minerals", [])),
                dietary_tags=list(data.get("dietary_tags", [])),
                notes=str(data.get("notes", "")),
            )
        except json.JSONDecodeError, KeyError:
            return self._fallback_nutrition()

    def _fallback_nutrition(self) -> NutritionResult:
        return NutritionResult(
            calories="Estimated 350 kcal per serving",
            protein="20g",
            carbohydrates="35g",
            fat="10g",
            fiber="4g",
            vitamins=["Vitamin C", "Vitamin A", "B12"],
            minerals=["Iron", "Calcium"],
            dietary_tags=["balanced"],
            notes="Nutrition analysis unavailable. Estimates shown.",
            available=False,
        )

    async def check_dietary_compliance(
        self,
        ingredients: list[str],
        diet_type: str,
    ) -> dict[str, Any]:
        """Check whether ingredients comply with a dietary pattern.

        Args:
            ingredients: List of ingredients to check.
            diet_type: Dietary pattern (e.g. "vegan", "keto", "gluten-free").

        Returns:
            Dict with ``compliant`` (bool), ``violations`` (list), ``suggestions`` (list).
        """
        if not self._available:
            return {"compliant": True, "violations": [], "suggestions": [], "available": False}

        ingredient_str = ", ".join(ingredients)
        prompt = (
            f"You are a nutrition AI. Check if these ingredients comply with a {diet_type} diet.\n"
            "Respond ONLY with valid JSON:\n"
            '{"compliant": true, "violations": ["non-compliant ingredient 1"], '
            '"suggestions": ["alternative suggestion 1"]}\n\n'
            f"Ingredients: {ingredient_str}\n"
            f"Diet type: {diet_type}\n\n"
            "Respond with valid JSON only:"
        )

        try:
            raw = await self._router.generate(prompt, temperature=0.2)
            text = raw.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            if "{" in text and "}" in text:
                text = text[text.find("{") : text.rfind("}") + 1]
            data = json.loads(text)
            return {
                "compliant": bool(data.get("compliant", True)),
                "violations": list(data.get("violations", [])),
                "suggestions": list(data.get("suggestions", [])),
                "available": True,
            }
        except Exception as exc:
            logger.error("NutritionAnalyzer: compliance check failed — %s", exc)
            return {"compliant": True, "violations": [], "suggestions": [], "available": False}


# Module-level cache keyed by model name
_analyzers: dict[str, NutritionAnalyzer] = {}


def get_nutrition_analyzer(model_name: str = "gemini-2.5-flash") -> NutritionAnalyzer:
    """Return a cached :class:`NutritionAnalyzer` for *model_name*."""
    if model_name not in _analyzers:
        _analyzers[model_name] = NutritionAnalyzer(model_name=model_name)
    return _analyzers[model_name]
