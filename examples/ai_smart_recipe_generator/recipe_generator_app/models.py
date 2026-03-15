"""recipe_generator_app models."""

from __future__ import annotations

from openviper.db import fields
from openviper.db.models import Model


class UserIngredients(Model):
    """Stores the ingredients a user has on hand."""

    _app_name = "recipe_generator_app"

    user = fields.IntegerField()
    ingredients = fields.TextField()  # comma-separated ingredient list
    created_at = fields.DateTimeField(auto_now_add=True)
    updated_at = fields.DateTimeField(auto_now=True)

    class Meta:
        table_name = "recipe_user_ingredients"

    def __str__(self) -> str:
        return f"Ingredients for user {self.user}"

    def ingredient_list(self) -> list[str]:
        return [i.strip() for i in self.ingredients.split(",") if i.strip()]


class Recipe(Model):
    """An AI-generated recipe."""

    _app_name = "recipe_generator_app"

    user = fields.IntegerField()
    title = fields.CharField(max_length=255)
    ingredients = fields.TextField()
    instructions = fields.TextField()
    servings = fields.CharField(max_length=50, null=True, blank=True)
    prep_time = fields.CharField(max_length=50, null=True, blank=True)
    cook_time = fields.CharField(max_length=50, null=True, blank=True)
    created_at = fields.DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "recipe_recipe"

    def __str__(self) -> str:
        return self.title or ""


class MealPlan(Model):
    """A weekly meal plan generated from recipes."""

    _app_name = "recipe_generator_app"

    user = fields.IntegerField()
    title = fields.CharField(max_length=255)
    plan_data = fields.TextField()  # JSON: day -> meal list
    week_start = fields.CharField(max_length=20, null=True, blank=True)
    created_at = fields.DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "recipe_mealplan"

    def __str__(self) -> str:
        return self.title or ""


class ShoppingList(Model):
    """A shopping list derived from a meal plan."""

    _app_name = "recipe_generator_app"

    user = fields.IntegerField()
    meal_plan = fields.IntegerField(null=True)
    items = fields.TextField()  # JSON list of shopping items
    created_at = fields.DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "recipe_shoppinglist"

    def __str__(self) -> str:
        return f"Shopping list for user {self.user}"


class NutritionInfo(Model):
    """Nutrition information for a recipe."""

    _app_name = "recipe_generator_app"

    recipe = fields.IntegerField()
    user = fields.IntegerField()
    calories = fields.CharField(max_length=50, null=True, blank=True)
    protein = fields.CharField(max_length=50, null=True, blank=True)
    carbohydrates = fields.CharField(max_length=50, null=True, blank=True)
    fat = fields.CharField(max_length=50, null=True, blank=True)
    fiber = fields.CharField(max_length=50, null=True, blank=True)
    notes = fields.TextField(null=True, blank=True)
    created_at = fields.DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "recipe_nutritioninfo"

    def __str__(self) -> str:
        return f"Nutrition for recipe {self.recipe}"
