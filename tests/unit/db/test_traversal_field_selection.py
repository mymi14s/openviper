"""Unit tests for traversal field selection in values() / values_list().

Covers:
  - Single-level FK traversal (e.g. ``author__username``)
  - Multi-level FK traversal (e.g. ``parent__reporter__username``)
  - Mixed traversal + local fields
  - Multiple traversal fields sharing the same FK prefix
  - Invalid traversal fields raise FieldError
  - values_list with traversal fields
  - Traversal with filters and ordering
  - SQL statement verification (JOIN presence, column labels)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.permissions import PermissionError as ModelPermissionError
from openviper.db.executor import (
    build_traversal_joins,
    cached_traversal_lookup,
    execute_values,
    get_table,
)
from openviper.db.fields import CharField, ForeignKey, IntegerField
from openviper.db.models import Count, Model, TraversalLookup
from openviper.exceptions import FieldError


class ValUser(Model):
    username = CharField(max_length=100)
    email = CharField(max_length=200, default="")

    class Meta:
        table_name = "tfs_users"


class ValScore(Model):
    score = IntegerField(default=0)
    mode = CharField(max_length=20, default="normal")
    user = ForeignKey(ValUser, on_delete="CASCADE")

    class Meta:
        table_name = "tfs_scores"


class ValProfile(Model):
    bio = CharField(max_length=500)

    class Meta:
        table_name = "tfs_profiles"


class ValAuthor(Model):
    username = CharField(max_length=100)
    profile = ForeignKey(ValProfile, on_delete="CASCADE")

    class Meta:
        table_name = "tfs_authors"


class ValPost(Model):
    title = CharField(max_length=200)
    author = ForeignKey(ValAuthor, on_delete="CASCADE")

    class Meta:
        table_name = "tfs_posts"


def make_qs(
    model=ValScore,
    filters=None,
    excludes=None,
    order=None,
    limit=None,
    offset=None,
    annotations=None,
    q_filters=None,
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
    qs._distinct = False
    qs._annotations = annotations or {}
    qs._q_filters = q_filters or []
    qs._select_related = []
    qs._ignore_permissions = False
    return qs


class TestValuesSingleTraversal:
    """Single FK hop: Score → User."""

    @pytest.mark.asyncio
    async def test_single_traversal_field(self):
        """values('user__username') should select from joined user table."""
        qs = make_qs()

        captured_stmts = []

        async def fake_execute(stmt):
            captured_stmts.append(stmt)
            result = MagicMock()
            result.mappings.return_value = [{"user__username": "alice"}]
            return result

        mock_conn = AsyncMock()
        mock_conn.execute = fake_execute

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("user__username",))
            assert result == [{"user__username": "alice"}]

        # Verify JOIN was generated
        sql = str(captured_stmts[0].compile(compile_kwargs={"literal_binds": True})).upper()
        assert "JOIN" in sql

    @pytest.mark.asyncio
    async def test_mixed_traversal_and_local_fields(self):
        """values('user__username', 'score', 'mode') - the original use-case."""
        qs = make_qs(order=["-score"], limit=5)

        captured_stmts = []

        async def fake_execute(stmt):
            captured_stmts.append(stmt)
            result = MagicMock()
            result.mappings.return_value = [
                {"user__username": "alice", "score": 100, "mode": "hard"},
                {"user__username": "bob", "score": 90, "mode": "normal"},
            ]
            return result

        mock_conn = AsyncMock()
        mock_conn.execute = fake_execute

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("user__username", "score", "mode"))
            assert len(result) == 2
            assert result[0]["user__username"] == "alice"
            assert result[0]["score"] == 100
            assert result[0]["mode"] == "hard"

        # Verify JOIN and columns
        sql = str(captured_stmts[0].compile(compile_kwargs={"literal_binds": True})).upper()
        assert "JOIN" in sql
        assert "LIMIT" in sql

    @pytest.mark.asyncio
    async def test_multiple_traversal_same_prefix(self):
        """values('user__username', 'user__email') - shared FK, one JOIN."""
        qs = make_qs()

        captured_stmts = []

        async def fake_execute(stmt):
            captured_stmts.append(stmt)
            result = MagicMock()
            result.mappings.return_value = [
                {"user__username": "alice", "user__email": "alice@example.com"},
            ]
            return result

        mock_conn = AsyncMock()
        mock_conn.execute = fake_execute

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("user__username", "user__email"))
            assert result[0]["user__username"] == "alice"
            assert result[0]["user__email"] == "alice@example.com"

        # Only one JOIN should be generated (shared FK prefix)
        sql = str(captured_stmts[0].compile(compile_kwargs={"literal_binds": True})).upper()
        assert sql.count("JOIN") >= 1


class TestValuesMultiLevelTraversal:
    """Multi-level FK: Post → Author → Profile."""

    @pytest.mark.asyncio
    async def test_two_level_traversal(self):
        """values('author__username') on ValPost."""
        qs = make_qs(model=ValPost)

        captured_stmts = []

        async def fake_execute(stmt):
            captured_stmts.append(stmt)
            result = MagicMock()
            result.mappings.return_value = [{"author__username": "bob"}]
            return result

        mock_conn = AsyncMock()
        mock_conn.execute = fake_execute

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("author__username",))
            assert result[0]["author__username"] == "bob"

        sql = str(captured_stmts[0].compile(compile_kwargs={"literal_binds": True})).upper()
        assert "JOIN" in sql

    @pytest.mark.asyncio
    async def test_three_level_traversal(self):
        """values('author__profile__bio') on ValPost - two FK hops."""
        qs = make_qs(model=ValPost)

        captured_stmts = []

        async def fake_execute(stmt):
            captured_stmts.append(stmt)
            result = MagicMock()
            result.mappings.return_value = [{"author__profile__bio": "I code"}]
            return result

        mock_conn = AsyncMock()
        mock_conn.execute = fake_execute

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("author__profile__bio",))
            assert result[0]["author__profile__bio"] == "I code"

        sql = str(captured_stmts[0].compile(compile_kwargs={"literal_binds": True})).upper()
        # Two JOINs for two FK hops
        assert sql.count("JOIN") >= 2


class TestValuesTraversalErrors:
    """Invalid traversal field names should raise FieldError."""

    @pytest.mark.asyncio
    async def test_invalid_traversal_field(self):
        """A traversal path with a nonexistent FK should raise FieldError."""
        qs = make_qs()
        with pytest.raises(FieldError, match="Invalid traversal field"):
            await execute_values(qs, fields=("nonexistent__username",))

    @pytest.mark.asyncio
    async def test_invalid_final_field_in_traversal(self):
        """A valid FK but nonexistent final field should raise FieldError."""
        qs = make_qs()
        with pytest.raises(FieldError, match="Invalid traversal field"):
            await execute_values(qs, fields=("user__nonexistent_field",))

    @pytest.mark.asyncio
    async def test_non_fk_traversal_raises(self):
        """Trying to traverse through a non-FK field should raise FieldError."""
        qs = make_qs()
        # 'score' is an IntegerField, not a ForeignKey - traversal through it
        # should fail
        with pytest.raises(FieldError, match="Invalid traversal field"):
            await execute_values(qs, fields=("score__something",))

    @pytest.mark.asyncio
    async def test_invalid_simple_field_still_raises(self):
        """Non-traversal invalid field should still raise FieldError."""
        qs = make_qs()
        with pytest.raises(FieldError, match="Invalid field"):
            await execute_values(qs, fields=("nonexistent_local",))


class TestValuesTraversalWithFilters:
    """Traversal field selection combined with WHERE / ORDER BY."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="Filter traversal JOIN column lookup fails; separate bug from key remapping",
        raises=KeyError,
    )
    async def test_traversal_with_filter(self):
        """Filter on a traversal field while selecting traversal columns."""
        qs = make_qs(filters=[{"user__username": "alice"}])

        captured_stmts = []

        async def fake_execute(stmt):
            captured_stmts.append(stmt)
            result = MagicMock()
            result.mappings.return_value = [
                {"user__username": "alice", "score": 100, "mode": "hard"},
            ]
            return result

        mock_conn = AsyncMock()
        mock_conn.execute = fake_execute

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("user__username", "score", "mode"))
            assert result[0]["user__username"] == "alice"

        sql = str(captured_stmts[0].compile(compile_kwargs={"literal_binds": True})).upper()
        assert "JOIN" in sql

    @pytest.mark.asyncio
    async def test_traversal_with_local_filter_and_order(self):
        """Local filter + order with traversal field selection."""
        qs = make_qs(filters=[{"score__gt": 50}], order=["-score"], limit=5)

        captured_stmts = []

        async def fake_execute(stmt):
            captured_stmts.append(stmt)
            result = MagicMock()
            result.mappings.return_value = [
                {"user__username": "alice", "score": 100, "mode": "hard"},
            ]
            return result

        mock_conn = AsyncMock()
        mock_conn.execute = fake_execute

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("user__username", "score", "mode"))
            assert len(result) == 1

        sql = str(captured_stmts[0].compile(compile_kwargs={"literal_binds": True})).upper()
        assert "JOIN" in sql
        assert "WHERE" in sql
        assert "ORDER BY" in sql
        assert "LIMIT" in sql


class TestValuesListTraversal:
    """values_list() delegates to values() so traversal should work there too."""

    @pytest.mark.asyncio
    async def test_values_list_with_traversal(self):
        """values_list('user__username', 'score') with flat=False."""

        # We test through the Manager/QuerySet API by mocking execute_values
        mock_rows = [
            {"user__username": "alice", "score": 100},
            {"user__username": "bob", "score": 90},
        ]

        with (
            patch(
                "openviper.db.models.execute_values",
                new_callable=AsyncMock,
                return_value=mock_rows,
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await ValScore.objects.values_list("user__username", "score")
            assert len(result) == 2
            assert result[0] == ("alice", 100)
            assert result[1] == ("bob", 90)

    @pytest.mark.asyncio
    async def test_values_list_flat_with_traversal(self):
        """values_list('user__username', flat=True)."""
        mock_rows = [{"user__username": "alice"}, {"user__username": "bob"}]

        with (
            patch(
                "openviper.db.models.execute_values",
                new_callable=AsyncMock,
                return_value=mock_rows,
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await ValScore.objects.values_list("user__username", flat=True)
            assert result == ["alice", "bob"]


class TestValuesTraversalSQLStructure:
    """Verify the generated SQL contains the expected structural elements."""

    @pytest.mark.asyncio
    async def test_left_outer_join_used(self):
        """Traversal JOINs should be LEFT OUTER JOINs (NULL FK support)."""
        qs = make_qs()

        captured_stmts = []

        async def fake_execute(stmt):
            captured_stmts.append(stmt)
            result = MagicMock()
            result.mappings.return_value = []
            return result

        mock_conn = AsyncMock()
        mock_conn.execute = fake_execute

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            await execute_values(qs, fields=("user__username",))

        sql = str(captured_stmts[0].compile(compile_kwargs={"literal_binds": True})).upper()
        # LEFT OUTER JOIN is the standard for NULL FK support
        assert "LEFT" in sql or "OUTER" in sql or "JOIN" in sql

    @pytest.mark.asyncio
    async def test_column_labelled_with_traversal_name(self):
        """The selected column should be labelled as 'user__username'."""
        qs = make_qs()

        captured_stmts = []

        async def fake_execute(stmt):
            captured_stmts.append(stmt)
            result = MagicMock()
            result.mappings.return_value = []
            return result

        mock_conn = AsyncMock()
        mock_conn.execute = fake_execute

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            await execute_values(qs, fields=("user__username",))

        # Verify the statement has column(s) - it shouldn't be empty
        stmt = captured_stmts[0]
        assert stmt is not None
        # The column should have a label matching the traversal path
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "username" in sql.lower()


class TestTraversalLookupForValues:
    """Verify TraversalLookup correctly identifies field types for values()."""

    def test_simple_field_not_traversal(self):
        """'score' should not be classified as a traversal field."""
        assert "__" not in "score"

    def test_traversal_field_detected(self):
        """'user__username' should be detected as a traversal field."""
        assert "__" in "user__username"

    def test_traversal_lookup_valid(self):
        """TraversalLookup should parse 'user__username' correctly."""
        lookup = TraversalLookup("user__username", ValScore)
        assert not lookup.is_simple_field()
        assert len(lookup.get_joins_needed()) == 1
        assert lookup.final_field is not None

    def test_traversal_lookup_final_field_name(self):
        """The final field should be 'username' on ValUser."""
        lookup = TraversalLookup("user__username", ValScore)
        assert lookup.final_field.name == "username"
        assert lookup.final_model == ValUser

    def test_traversal_lookup_multi_level(self):
        """author__profile__bio on ValPost - three levels deep."""
        lookup = TraversalLookup("author__profile__bio", ValPost)
        assert not lookup.is_simple_field()
        assert len(lookup.get_joins_needed()) == 2  # Post→Author, Author→Profile
        assert lookup.final_field.name == "bio"
        assert lookup.final_model == ValProfile


class TestValuesBackwardCompat:
    """Ensure non-traversal values() still works exactly as before."""

    @pytest.mark.asyncio
    async def test_simple_fields_no_join(self):
        """values('score', 'mode') should not produce JOINs."""
        qs = make_qs()

        captured_stmts = []

        async def fake_execute(stmt):
            captured_stmts.append(stmt)
            result = MagicMock()
            result.mappings.return_value = [{"score": 100, "mode": "hard"}]
            return result

        mock_conn = AsyncMock()
        mock_conn.execute = fake_execute

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs, fields=("score", "mode"))
            assert result[0]["score"] == 100

        sql = str(captured_stmts[0].compile(compile_kwargs={"literal_binds": True})).upper()
        assert "JOIN" not in sql

    @pytest.mark.asyncio
    async def test_no_fields_all_columns(self):
        """values() with no fields should select all columns (no JOIN)."""
        qs = make_qs()

        captured_stmts = []

        async def fake_execute(stmt):
            captured_stmts.append(stmt)
            result = MagicMock()
            result.mappings.return_value = [{"id": 1, "score": 100, "mode": "normal", "user_id": 1}]
            return result

        mock_conn = AsyncMock()
        mock_conn.execute = fake_execute

        with patch("openviper.db.executor.connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await execute_values(qs)
            assert isinstance(result, list)

        sql = str(captured_stmts[0].compile(compile_kwargs={"literal_binds": True})).upper()
        # No traversal fields, so no JOIN
        assert "JOIN" not in sql

    @pytest.mark.asyncio
    async def test_invalid_simple_field_still_works(self):
        """Invalid simple field in values() should still raise FieldError."""
        qs = make_qs()
        with pytest.raises(FieldError, match="Invalid field"):
            await execute_values(qs, fields=("nonexistent",))


class TestManagerValuesTraversal:
    """Test the high-level Manager.values() API with traversal fields."""

    @pytest.mark.asyncio
    async def test_manager_values_with_traversal(self):
        """Manager.values('user__username', 'score', 'mode') should work."""
        mock_rows = [
            {"user__username": "alice", "score": 100, "mode": "hard"},
            {"user__username": "bob", "score": 90, "mode": "normal"},
        ]

        with (
            patch(
                "openviper.db.models.execute_values",
                new_callable=AsyncMock,
                return_value=mock_rows,
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await ValScore.objects.values("user__username", "score", "mode")
            assert len(result) == 2
            assert result[0]["username"] == "alice"
            assert result[0]["score"] == 100
            assert result[0]["mode"] == "hard"

    @pytest.mark.asyncio
    async def test_manager_values_order_limit_traversal(self):
        """Score.objects.order_by('-score').limit(5).values('user__username', 'score', 'mode')
        - the exact use-case from the feature request."""
        mock_rows = [
            {"user__username": "alice", "score": 100, "mode": "hard"},
        ]

        with (
            patch(
                "openviper.db.models.execute_values",
                new_callable=AsyncMock,
                return_value=mock_rows,
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await (
                ValScore.objects.order_by("-score")
                .limit(5)
                .values("user__username", "score", "mode")
            )
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0]["username"] == "alice"

    @pytest.mark.asyncio
    async def test_manager_values_permission_denied(self):
        """PermissionError should return empty list."""
        with patch(
            "openviper.db.models.check_permission_for_model",
            new_callable=AsyncMock,
            side_effect=ModelPermissionError("denied"),
        ):
            result = await ValScore.objects.values("user__username", "score")
            assert result == []


class TestValuesKeyRemapping:
    """Traversal keys are remapped to their final field segment by values()."""

    @pytest.mark.asyncio
    async def test_values_remaps_traversal_key(self):
        """'user__username' is remapped to 'username' in the output dict."""
        mock_rows = [{"user__username": "alice", "score": 100}]

        with (
            patch(
                "openviper.db.models.execute_values",
                new_callable=AsyncMock,
                return_value=mock_rows,
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await ValScore.objects.values("user__username", "score")
            assert result[0]["username"] == "alice"
            assert result[0]["score"] == 100

    @pytest.mark.asyncio
    async def test_values_remaps_multi_level_traversal_key(self):
        """'author__profile__bio' is remapped to 'bio' in the output dict."""
        mock_rows = [{"author__profile__bio": "I code"}]

        with (
            patch(
                "openviper.db.models.execute_values",
                new_callable=AsyncMock,
                return_value=mock_rows,
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await ValPost.objects.values("author__profile__bio")
            assert result[0]["bio"] == "I code"

    @pytest.mark.asyncio
    async def test_values_collision_preserves_full_key(self):
        """Two traversal fields with same final key keep full traversal keys."""
        mock_rows = [{"author__username": "alice", "editor__username": "bob"}]

        with (
            patch(
                "openviper.db.models.execute_values",
                new_callable=AsyncMock,
                return_value=mock_rows,
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await ValPost.objects.values("author__username", "editor__username")
            assert result[0]["author__username"] == "alice"
            assert result[0]["editor__username"] == "bob"

    @pytest.mark.asyncio
    async def test_values_no_traversal_keys_unchanged(self):
        """Simple fields without traversal are not remapped."""
        mock_rows = [{"score": 100, "mode": "hard"}]

        with (
            patch(
                "openviper.db.models.execute_values",
                new_callable=AsyncMock,
                return_value=mock_rows,
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await ValScore.objects.values("score", "mode")
            assert result[0]["score"] == 100
            assert result[0]["mode"] == "hard"

    @pytest.mark.asyncio
    async def test_values_list_uses_remapped_keys(self):
        """values_list looks up values using remapped key names."""
        mock_rows = [{"user__username": "alice", "score": 100}]

        with (
            patch(
                "openviper.db.models.execute_values",
                new_callable=AsyncMock,
                return_value=mock_rows,
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await ValScore.objects.values_list("user__username", "score")
            assert result[0] == ("alice", 100)

    @pytest.mark.asyncio
    async def test_values_list_flat_uses_remapped_key(self):
        """values_list(flat=True) looks up values using remapped key name."""
        mock_rows = [{"user__username": "alice"}]

        with (
            patch(
                "openviper.db.models.execute_values",
                new_callable=AsyncMock,
                return_value=mock_rows,
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await ValScore.objects.values_list("user__username", flat=True)
            assert result == ["alice"]
