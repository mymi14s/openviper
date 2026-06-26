"""Unit tests for personality templates."""

from __future__ import annotations

from agents.personalities import PERSONALITY_TEMPLATES


class TestPersonalityTemplates:
    """Test built-in personality templates."""

    def test_has_12_templates(self) -> None:
        assert len(PERSONALITY_TEMPLATES) == 12

    def test_each_template_has_required_fields(self) -> None:
        for template in PERSONALITY_TEMPLATES:
            assert "name" in template
            assert "system_prompt" in template
            assert "temperature" in template
            assert "model_id" in template
            assert "traits" in template
            assert "interests" in template

    def test_names_are_unique(self) -> None:
        names = [t["name"] for t in PERSONALITY_TEMPLATES]
        assert len(names) == len(set(names))

    def test_temperatures_in_valid_range(self) -> None:
        for template in PERSONALITY_TEMPLATES:
            temp = template["temperature"]
            assert 0.0 <= temp <= 1.0

    def test_system_prompts_are_non_empty(self) -> None:
        for template in PERSONALITY_TEMPLATES:
            assert len(template["system_prompt"]) > 20
