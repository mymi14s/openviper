"""AI-powered recipe generator module."""

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


class RecipeResult:
    """Result from the recipe generator."""

    def __init__(
        self,
        title: str,
        ingredients: list[str],
        instructions: list[str],
        servings: str = "",
        prep_time: str = "",
        cook_time: str = "",
        available: bool = True,
    ) -> None:
        self.title = title
        self.ingredients = ingredients
        self.instructions = instructions
        self.servings = servings
        self.prep_time = prep_time
        self.cook_time = cook_time
        self.available = available

    def ingredients_text(self) -> str:
        return "\n".join(self.ingredients)

    def instructions_text(self) -> str:
        return "\n".join(f"{i + 1}. {step}" for i, step in enumerate(self.instructions))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "title": self.title,
            "ingredients": self.ingredients,
            "instructions": self.instructions,
            "servings": self.servings,
            "prep_time": self.prep_time,
            "cook_time": self.cook_time,
        }


class RecipeGenerator(AIServiceBase):
    """AI-powered recipe generator.

    Uses :class:`~openviper.ai.router.ModelRouter` for provider-agnostic
    AI inference. Generates recipes based on a list of ingredients.

    Example::

        generator = RecipeGenerator(model_name="llama3")
        recipe = await generator.generate_recipe(["chicken", "garlic", "lemon"])
    """

    default_model = "llama3"

    async def generate_recipe(
        self,
        ingredients: list[str],
        dietary_preferences: str = "",
    ) -> RecipeResult:
        """Generate a recipe from the given ingredients.

        Args:
            ingredients: List of available ingredients.
            dietary_preferences: Optional dietary constraints (e.g. "vegan", "gluten-free").

        Returns:
            :class:`RecipeResult` with title, ingredients, and instructions.
        """
        if not self.available:
            return self.fallback_recipe(ingredients)

        ingredient_str, pref_note = format_ingredients(ingredients, dietary_preferences)

        prompt = (
            "You are a professional chef AI. Create a recipe using the following ingredients.\n"
            "Respond ONLY with valid JSON (no markdown, no extra text):\n"
            '{"title": "Recipe Name", "ingredients": ["ingredient 1", "ingredient 2", ...], '
            '"instructions": ["step 1", "step 2", ...], '
            '"servings": "4", "prep_time": "15 minutes", "cook_time": "30 minutes"}\n\n'
            f"Available ingredients: {ingredient_str}.{pref_note}\n\n"
            "Respond with valid JSON only:"
        )

        try:
            raw = await self.router.generate(prompt, temperature=0.7)
            return self.parse_recipe(raw, ingredients)
        except Exception as exc:
            logger.error("RecipeGenerator: generation failed - %s", exc)
            return self.fallback_recipe(ingredients)

    def parse_recipe(self, raw: str, ingredients: list[str]) -> RecipeResult:
        text = strip_ai_json_response(raw)

        try:
            data = json.loads(text)
            return RecipeResult(
                title=str(data.get("title", "Chef's Special")),
                ingredients=list(data.get("ingredients", ingredients)),
                instructions=list(data.get("instructions", ["Combine all ingredients and cook."])),
                servings=str(data.get("servings", "4")),
                prep_time=str(data.get("prep_time", "")),
                cook_time=str(data.get("cook_time", "")),
            )
        except json.JSONDecodeError, KeyError:
            return self.fallback_recipe(ingredients)

    def fallback_recipe(self, ingredients: list[str]) -> RecipeResult:
        return RecipeResult(
            title="Simple Ingredient Mix",
            ingredients=ingredients,
            instructions=[
                "Prepare all ingredients.",
                "Combine ingredients in a pan.",
                "Cook over medium heat until done.",
                "Season to taste and serve.",
            ],
            servings="2",
            prep_time="10 minutes",
            cook_time="20 minutes",
            available=False,
        )

    async def generate_multiple_recipes(
        self,
        ingredients: list[str],
        count: int = 3,
        dietary_preferences: str = "",
    ) -> list[RecipeResult]:
        """Generate multiple recipe suggestions from the given ingredients.

        Args:
            ingredients: List of available ingredients.
            count: Number of recipes to generate.
            dietary_preferences: Optional dietary constraints.

        Returns:
            List of :class:`RecipeResult` objects.
        """
        if not self.available:
            return [self.fallback_recipe(ingredients)]

        ingredient_str, pref_note = format_ingredients(ingredients, dietary_preferences)

        prompt = (
            f"You are a professional chef AI. Create {count} different recipes using some or all "
            "of the following ingredients.\n"
            "Respond ONLY with valid JSON array (no markdown, no extra text):\n"
            '[{"title": "Recipe 1", "ingredients": [...], "instructions": [...], '
            '"servings": "4", "prep_time": "15 minutes", "cook_time": "30 minutes"}, ...]\n\n'
            f"Available ingredients: {ingredient_str}.{pref_note}\n\n"
            "Respond with valid JSON array only:"
        )

        try:
            raw = await self.router.generate(prompt, temperature=0.8)
            text = strip_ai_json_response(raw, is_array=True)

            data_list = json.loads(text)
            return [
                RecipeResult(
                    title=str(d.get("title", f"Recipe {i + 1}")),
                    ingredients=list(d.get("ingredients", ingredients)),
                    instructions=list(d.get("instructions", ["Cook all ingredients."])),
                    servings=str(d.get("servings", "4")),
                    prep_time=str(d.get("prep_time", "")),
                    cook_time=str(d.get("cook_time", "")),
                )
                for i, d in enumerate(data_list[:count])
            ]
        except Exception as exc:
            logger.error("RecipeGenerator: multi-recipe generation failed - %s", exc)
            return [self.fallback_recipe(ingredients)]


generators: dict[str, RecipeGenerator] = {}


def get_recipe_generator(model_name: str = "gemini-2.5-flash") -> RecipeGenerator:
    """Return a cached :class:`RecipeGenerator` for *model_name*."""
    return cached_factory(generators, RecipeGenerator, model_name)
