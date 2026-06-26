"""Unit tests for traversal field selection in values() / values_list().

Tests cover:
  - Single-level FK traversal (e.g. "author__username")
  - Multi-level FK traversal (e.g. "parent__reporter__username")
  - Mixed traversal + local fields in a single call
  - Invalid traversal field validation
  - SQL JOIN generation verification
  - values_list() with traversal fields
  - Traversal with filters and ordering
  - Annotation fields coexisting with traversal fields
  - Duplicate FK path deduplication (e.g. "user__username" + "user__email")
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.db.executor import (
    build_traversal_joins,
    cached_traversal_lookup,
    execute_values,
    get_table,
)
from openviper.db.fields import CharField, ForeignKey, IntegerField
from openviper.db.models import Count, Manager, Model, QuerySet, TraversalLookup
from openviper.exceptions import FieldError


class TVUser(Model):
    """Target model for FK traversal - represents a User with a username."""

    username = CharField(max_length=100)
    email = CharField(max_length=200, default="")

    class Meta:
        table_name = "tv_users"


class TVProfile(Model):
    """Deep target for multi-level traversal."""

    bio = CharField(max_length=500)

    class Meta:
        table_name = "tv_profiles"


class TVScore(Model):
    """Root model - represents a Score belonging to a User.

    This matches the use case from the issue:
        result = await Score.objects.order_by("-score").limit(5).values(
            "user__username", "score", "mode"
        )
    """

    user = ForeignKey(TVUser, on_delete="CASCADE")
    score = IntegerField(default=0)
    mode = CharField(max_length=20, default="normal")

    class Meta:
        table_name = "tv_scores"


class TVComment(Model):
    """Model with a FK to Score, enabling two-level traversal."""

    score = ForeignKey(TVScore, on_delete="CASCADE")
    text = CharField(max_length=1000)

    class Meta:
        table_name = "tv_comments"


class TVDeepUser(Model):
    """User with a profile FK for three-level traversal tests."""

    username = CharField(max_length=100)
    profile = ForeignKey(TVProfile, on_delete="CASCADE")

    class Meta:
        table_name = "tv_deep_users"


class TVDeepScore(Model):
    """Score with a FK to DeepUser, enabling three-level traversal:
    score -> user -> profile -> bio
    """

    user = ForeignKey(TVDeepUser, on_delete="CASCADE")
    score = IntegerField(default=0)

    class Meta:
        table_name = "tv_deep_scores"


def make_qs(
    model,
    filters=None,
    excludes=None,
    order=None,
    limit=None,
    offset=None,
    distinct=False,
    annotations=None,
    q_filters=None,
    select_related=None,
    ignore_permissions=False,
):
    qs = MagicMock()
    qs._model = model
    qs._filters = filters or []
    qs._excludes = excludes or []
    qs._order = order or []
    qs._limit = limit
    qs._offset = offset
    qs._only_fields = []
    qs._defer_fields = []
    qs._distinct = distinct
    qs._annotations = annotations or {}
    qs._q_filters = q_filters or []
    qs._select_related = select_related or []
    qs._ignore_permissions = ignore_permissions
    return qs


class TestTraversalLookupForValues:
    """Validate that TraversalLookup correctly parses field names used in values()."""

    def test_single_level_traversal(self):
        lookup = TraversalLookup("user__username", TVScore)
        assert not lookup.is_simple_field()
        assert len(lookup.get_joins_needed()) == 1
        assert lookup.final_field is not None
        assert lookup.final_model == TVUser

    def test_two_level_traversal(self):
        lookup = TraversalLookup("score__user__username", TVComment)
        assert not lookup.is_simple_field()
        assert len(lookup.get_joins_needed()) == 2
        assert lookup.final_model == TVUser
        assert lookup.final_field.name == "username"

    def test_three_level_traversal(self):
        lookup = TraversalLookup("user__profile__bio", TVDeepScore)
        assert not lookup.is_simple_field()
        assert len(lookup.get_joins_needed()) == 2
        assert lookup.final_model == TVProfile
        assert lookup.final_field.name == "bio"

    def test_simple_field_not_traversal(self):
        lookup = TraversalLookup("score", TVScore)
        assert lookup.is_simple_field()
        assert lookup.get_joins_needed() == []

    def test_invalid_traversal_raises(self):
        with pytest.raises(FieldError):
            TraversalLookup("user__nonexistent", TVScore)

    def test_non_fk_traversal_raises(self):
        """Trying to traverse through a non-FK field should fail."""
        with pytest.raises(FieldError, match="Cannot traverse"):
            TraversalLookup("text__mode", TVComment)

    def test_invalid_first_field_raises(self):
        with pytest.raises(FieldError, match="not found"):
            TraversalLookup("nonexistent__username", TVScore)


class TestTraversalJoinsForValues:
    """Test that build_traversal_joins builds correct JOINs for values() fields."""

    def test_single_fk_join(self):
        lookup = TraversalLookup("user__username", TVScore)
        score_table = get_table(TVScore)
        from_clause, final_table = build_traversal_joins(lookup, score_table)
        assert from_clause is not None
        assert final_table is not None
        # Final table should be the users table
        assert final_table.name == "tv_users"

    def test_two_level_fk_join(self):
        lookup = TraversalLookup("score__user__username", TVComment)
        comment_table = get_table(TVComment)
        from_clause, final_table = build_traversal_joins(lookup, comment_table)
        assert from_clause is not None
        assert final_table.name == "tv_users"

    def test_three_level_fk_join(self):
        lookup = TraversalLookup("user__profile__bio", TVDeepScore)
        score_table = get_table(TVDeepScore)
        from_clause, final_table = build_traversal_joins(lookup, score_table)
        assert from_clause is not None
        assert final_table.name == "tv_profiles"


class TestExecuteValuesTraversal:
    """Integration tests for execute_values with traversal fields."""

    @pytest.mark.asyncio
    async def test_traversal_single_field(self):
        """values("user__username") should select username from joined user table."""
        qs = make_qs(TVScore)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = [{"user__username": "alice"}]
        mock_conn.execute = AsyncMock(return_value=mock_result)

        captured_stmts = []

        async def _capture_execute(stmt):
            captured_stmts.append(stmt)
            return mock_result

        mock_conn.execute = _capture_execute

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("user__username",))

        assert result == [{"user__username": "alice"}]
        # Verify the SQL statement includes a JOIN
        assert len(captured_stmts) == 1
        sql_str = str(captured_stmts[0].compile(compile_kwargs={"literal_binds": True}))
        assert "JOIN" in sql_str.upper() or "tv_users" in sql_str

    @pytest.mark.asyncio
    async def test_mixed_traversal_and_local_fields(self):
        """values("user__username", "score", "mode") - the exact use case from the issue."""
        qs = make_qs(TVScore, order=["-score"], limit=5)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = [
            {"user__username": "alice", "score": 100, "mode": "hard"},
            {"user__username": "bob", "score": 90, "mode": "easy"},
        ]
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("user__username", "score", "mode"))

        assert len(result) == 2
        assert result[0]["user__username"] == "alice"
        assert result[0]["score"] == 100
        assert result[0]["mode"] == "hard"
        assert result[1]["user__username"] == "bob"

    @pytest.mark.asyncio
    async def test_multi_level_traversal(self):
        """Two-level: values("score__user__username", "text") on Comment."""
        qs = make_qs(TVComment)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = [
            {"score__user__username": "alice", "text": "Great!"},
        ]
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("score__user__username", "text"))

        assert result[0]["score__user__username"] == "alice"
        assert result[0]["text"] == "Great!"

    @pytest.mark.asyncio
    async def test_three_level_traversal(self):
        """Three-level: values("user__profile__bio") on TVDeepScore."""
        qs = make_qs(TVDeepScore)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = [
            {"user__profile__bio": "Loves coding"},
        ]
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("user__profile__bio",))

        assert result[0]["user__profile__bio"] == "Loves coding"

    @pytest.mark.asyncio
    async def test_duplicate_fk_path_deduplication(self):
        """Multiple fields sharing the same FK prefix should only JOIN once.

        values("user__username", "user__email") should produce one JOIN
        to the users table, not two.
        """
        qs = make_qs(TVScore)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = [
            {"user__username": "alice", "user__email": "alice@example.com"},
        ]

        captured_stmts = []

        async def _capture_execute(stmt):
            captured_stmts.append(stmt)
            return mock_result

        mock_conn.execute = _capture_execute

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("user__username", "user__email"))

        assert result[0]["user__username"] == "alice"
        assert result[0]["user__email"] == "alice@example.com"
        # Verify only one statement was executed (one JOIN, not two)
        assert len(captured_stmts) == 1

    @pytest.mark.asyncio
    async def test_invalid_traversal_field_raises(self):
        """Invalid traversal field should raise FieldError."""
        qs = make_qs(TVScore)

        with pytest.raises(FieldError, match="Invalid traversal field"):
            await execute_values(qs, fields=("user__nonexistent",))

    @pytest.mark.asyncio
    async def test_traversal_with_annotation(self):
        """Traversal field + annotation field should coexist."""
        qs = make_qs(TVScore, annotations={"cnt": Count("id")})

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = [
            {"user__username": "alice", "cnt": 10},
        ]
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("user__username", "cnt"))

        assert result[0]["user__username"] == "alice"
        assert result[0]["cnt"] == 10

    @pytest.mark.asyncio
    async def test_traversal_with_filter(self):
        """Traversal fields should work alongside WHERE filters."""
        qs = make_qs(TVScore, filters=[{"mode": "hard"}])

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = [
            {"user__username": "alice", "score": 100},
        ]

        captured_stmts = []

        async def _capture_execute(stmt):
            captured_stmts.append(stmt)
            return mock_result

        mock_conn.execute = _capture_execute

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("user__username", "score"))

        assert result[0]["user__username"] == "alice"
        # Verify WHERE clause was applied
        sql_str = str(captured_stmts[0].compile(compile_kwargs={"literal_binds": True}))
        assert "WHERE" in sql_str.upper()

    @pytest.mark.asyncio
    async def test_traversal_with_order_and_limit(self):
        """Full use case: order_by("-score").limit(5).values("user__username", "score", "mode")."""
        qs = make_qs(TVScore, order=["-score"], limit=5)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = [
            {"user__username": f"user{i}", "score": 100 - i * 10, "mode": "hard"} for i in range(5)
        ]

        captured_stmts = []

        async def _capture_execute(stmt):
            captured_stmts.append(stmt)
            return mock_result

        mock_conn.execute = _capture_execute

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("user__username", "score", "mode"))

        assert len(result) == 5
        assert result[0]["user__username"] == "user0"
        # Verify ORDER BY and LIMIT
        sql_str = str(captured_stmts[0].compile(compile_kwargs={"literal_binds": True}))
        assert "ORDER" in sql_str.upper() or "LIMIT" in sql_str.upper()

    @pytest.mark.asyncio
    async def test_no_fields_returns_all_columns(self):
        """Calling execute_values without fields should still work (backward compat)."""
        qs = make_qs(TVScore)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = [
            {"id": 1, "user_id": 1, "score": 100, "mode": "hard"},
        ]
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs)

        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_simple_fields_only_no_join(self):
        """values("score", "mode") without traversal should NOT produce JOINs."""
        qs = make_qs(TVScore)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = [{"score": 50, "mode": "easy"}]

        captured_stmts = []

        async def _capture_execute(stmt):
            captured_stmts.append(stmt)
            return mock_result

        mock_conn.execute = _capture_execute

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("score", "mode"))

        assert result[0]["score"] == 50
        sql_str = str(captured_stmts[0].compile(compile_kwargs={"literal_binds": True}))
        # No JOIN should be present for simple fields
        assert "JOIN" not in sql_str.upper()

    @pytest.mark.asyncio
    async def test_empty_result_set(self):
        """Traversal with zero matching rows returns empty list."""
        qs = make_qs(TVScore)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = []
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("user__username", "score"))

        assert result == []


class TestValuesListTraversal:
    """Test that values_list works with traversal fields via the QuerySet layer."""

    @pytest.mark.asyncio
    async def test_values_list_traversal(self):
        """values_list("user__username", flat=True) with traversal should work."""
        with (
            patch(
                "openviper.db.models.execute_values",
                new_callable=AsyncMock,
                return_value=[{"user__username": "alice"}, {"user__username": "bob"}],
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await QuerySet(TVScore).values_list("user__username", flat=True)
            assert result == ["alice", "bob"]

    @pytest.mark.asyncio
    async def test_values_list_traversal_tuples(self):
        """values_list("user__username", "score") returns list of tuples."""
        with (
            patch(
                "openviper.db.models.execute_values",
                new_callable=AsyncMock,
                return_value=[
                    {"user__username": "alice", "score": 100},
                    {"user__username": "bob", "score": 90},
                ],
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await QuerySet(TVScore).values_list("user__username", "score")
            assert result == [("alice", 100), ("bob", 90)]


class TestManagerValuesTraversal:
    """Test that Manager.values() correctly passes traversal fields to execute_values."""

    @pytest.mark.asyncio
    async def test_manager_values_traversal(self):
        """Manager.values("user__username", "score") should work end-to-end."""
        with (
            patch(
                "openviper.db.models.execute_values",
                new_callable=AsyncMock,
                return_value=[
                    {"user__username": "alice", "score": 100},
                ],
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await Manager(TVScore).values("user__username", "score")
            assert result[0]["username"] == "alice"
            assert result[0]["score"] == 100

    @pytest.mark.asyncio
    async def test_manager_values_with_order_limit(self):
        """Full use case from the issue via Manager."""
        with (
            patch(
                "openviper.db.models.execute_values",
                new_callable=AsyncMock,
                return_value=[
                    {"user__username": f"top{i}", "score": 100 - i * 10, "mode": "hard"}
                    for i in range(5)
                ],
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await Manager(TVScore).values("user__username", "score", "mode")
            assert len(result) == 5
            assert result[0]["username"] == "top0"


class TestTraversalEdgeCases:
    """Edge-case tests for traversal field selection."""

    def test_traversal_lookup_caching(self):
        """Repeated lookups for the same field should use the cache."""
        lookup1 = cached_traversal_lookup("user__username", TVScore)
        lookup2 = cached_traversal_lookup("user__username", TVScore)
        # Both should resolve to the same result (cached)
        assert lookup1.final_field.name == lookup2.final_field.name
        assert lookup1.final_model == lookup2.final_model

    def test_different_models_same_field_name(self):
        """Same field name on different models should produce different lookups."""
        lookup1 = cached_traversal_lookup("user__username", TVScore)
        lookup2 = cached_traversal_lookup("user__username", TVDeepScore)
        # Both should have same final_field name but may differ in model
        assert lookup1.final_field.name == "username"
        assert lookup2.final_field.name == "username"

    @pytest.mark.asyncio
    async def test_traversal_with_distinct(self):
        """Traversal fields should work with distinct=True."""
        qs = make_qs(TVScore, distinct=True)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = [{"user__username": "alice"}]
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("user__username",))

        assert result[0]["user__username"] == "alice"

    @pytest.mark.asyncio
    async def test_traversal_with_offset(self):
        """Traversal fields should work with offset."""
        qs = make_qs(TVScore, offset=10)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value = [{"user__username": "alice"}]
        mock_conn.execute = AsyncMock(return_value=mock_result)

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("user__username",))

        assert result[0]["user__username"] == "alice"
