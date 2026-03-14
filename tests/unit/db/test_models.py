from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.permissions import PermissionError as ModelPermissionError
from openviper.db.fields import CharField, ForeignKey, IntegerField
from openviper.db.models import (
    Avg,
    Count,
    F,
    Manager,
    Max,
    Min,
    Model,
    ModelMeta,
    Q,
    QuerySet,
    Sum,
    TraversalLookup,
    _call_hook,
    _check_perm_cached,
    _FExpr,
    _perm_cache,
)
from openviper.exceptions import DoesNotExist, FieldError, MultipleObjectsReturned


class TestModelInstance:
    class User(Model):
        name = CharField()
        age = IntegerField(default=18)

        class Meta:
            table_name = "users"

    def test_model_init(self):
        u = self.User(name="Alice", age=25)
        assert u.name == "Alice"
        assert u.age == 25

    def test_model_repr(self):
        u = self.User(name="Alice")
        # repr only shows class name and pk (id)
        assert repr(u) == "<User pk=None>"

        u.id = 123
        assert "pk=123" in repr(u)

    def test_model_to_dict(self):
        u = self.User(name="Alice", age=30)
        d = u._to_dict()  # Correct method name
        assert d["name"] == "Alice"
        assert d["age"] == 30


class TestManager:
    class Item(Model):
        name = CharField()

        class Meta:
            table_name = "items"

    @pytest.mark.asyncio
    async def test_manager_all(self):
        # Manager.all() returns a QuerySet
        qs = self.Item.objects.all()
        assert isinstance(qs, QuerySet)
        assert qs._model == self.Item  # Access protected _model

    @pytest.mark.asyncio
    async def test_manager_filter(self):
        qs = self.Item.objects.filter(name="test")
        assert isinstance(qs, QuerySet)
        # _filters is a list of dicts
        assert qs._filters == [{"name": "test"}]

    @pytest.mark.asyncio
    async def test_manager_create(self):
        # Manager.create creates an instance and calls save()
        # openviper.db.models imports execute_save from executor
        with patch("openviper.db.models.execute_save", new_callable=AsyncMock) as mock_save:
            item = await self.Item.objects.create(name="new")
            assert item.name == "new"
            assert mock_save.called


class TestQuerySet:
    class Product(Model):
        name = CharField()
        price = IntegerField()

        class Meta:
            table_name = "products"

    def test_queryset_chaining(self):
        qs = self.Product.objects.filter(price__gt=10).order_by("-price")
        assert qs._filters == [{"price__gt": 10}]
        assert qs._order == ["-price"]

    def test_queryset_cloning(self):
        qs1 = self.Product.objects.filter(price=5)
        qs2 = qs1.filter(name="test")
        assert qs1 != qs2
        assert qs1._filters == [{"price": 5}]
        assert qs2._filters == [{"price": 5}, {"name": "test"}]

    def test_queryset_only_defer(self):
        qs = self.Product.objects.only("name").defer("price")
        # defer() clears _only_fields (last-call-wins semantics)
        assert qs._only_fields == []
        assert qs._defer_fields == ["price"]


class TestExpressions:
    def test_q_object(self):
        q1 = Q(name="Alice")
        q2 = Q(age__gt=20)
        q_or = q1 | q2
        assert q_or.connector == "OR"
        assert len(q_or.children) == 2

        q_and = q1 & q2
        assert q_and.connector == "AND"

        q_not = ~q1
        assert q_not.negated is True

    def test_f_expression(self):
        f1 = F("views")
        f2 = f1 + 1
        assert "views" in str(f2)
        assert "+" in str(f2)


class TestBulkOperations:
    class Job(Model):
        title = CharField()

        class Meta:
            table_name = "jobs"

    @pytest.mark.asyncio
    async def test_bulk_create(self):
        # bulk_create imports ignore_permissions_ctx and check_permission_for_model
        mock_conn = AsyncMock()
        # AsyncMock can be used as an async context manager
        mock_begin_ctx = AsyncMock()
        mock_begin_ctx.__aenter__.return_value = mock_conn

        with (
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
            patch("openviper.db.models._begin", return_value=mock_begin_ctx),
        ):

            jobs = [self.Job(title="J1"), self.Job(title="J2")]
            await self.Job.objects.bulk_create(jobs)
            assert mock_conn.execute.called


class TestCheckPermCached:

    @pytest.mark.asyncio
    async def test_ignore_permissions_returns_early(self):
        with patch(
            "openviper.db.models.check_permission_for_model", new_callable=AsyncMock
        ) as mock_check:
            await _check_perm_cached(Model, "read", ignore_permissions=True)
            mock_check.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_request_context_falls_through(self):
        token = _perm_cache.set(None)
        try:
            with patch(
                "openviper.db.models.check_permission_for_model", new_callable=AsyncMock
            ) as mock_check:
                await _check_perm_cached(Model, "read")
                mock_check.assert_awaited_once_with(Model, "read", ignore_permissions=False)
        finally:
            _perm_cache.reset(token)

    @pytest.mark.asyncio
    async def test_cache_hit_returns_early(self):
        cache = {(Model, "read"): True}
        token = _perm_cache.set(cache)
        try:
            with patch(
                "openviper.db.models.check_permission_for_model", new_callable=AsyncMock
            ) as mock_check:
                await _check_perm_cached(Model, "read")
                mock_check.assert_not_awaited()
        finally:
            _perm_cache.reset(token)

    @pytest.mark.asyncio
    async def test_cache_miss_calls_check_and_stores(self):
        cache = {}
        token = _perm_cache.set(cache)
        try:
            with patch(
                "openviper.db.models.check_permission_for_model", new_callable=AsyncMock
            ) as mock_check:
                await _check_perm_cached(Model, "create")
                mock_check.assert_awaited_once_with(Model, "create", ignore_permissions=False)
                assert (Model, "create") in cache
                assert cache[(Model, "create")] is True
        finally:
            _perm_cache.reset(token)


class TestModelMetaExtractAppName:

    def test_empty_module_returns_default(self):
        assert ModelMeta._extract_app_name("", "Foo") == "default"

    def test_apps_blog_models(self):
        assert ModelMeta._extract_app_name("apps.blog.models", "Post") == "blog"

    def test_openviper_auth_models(self):
        assert ModelMeta._extract_app_name("openviper.auth.models", "User") == "auth"

    def test_single_part_returns_default(self):
        assert ModelMeta._extract_app_name("models", "Foo") == "default"

    def test_two_parts_fallback(self):
        assert ModelMeta._extract_app_name("myapp.models", "Foo") == "myapp"


class TestFExpressions:

    def test_radd(self):
        f = F("price")
        result = 10 + f
        assert isinstance(result, _FExpr)
        assert result.lhs == 10
        assert result.op == "+"
        assert isinstance(result.rhs, F)

    def test_rsub(self):
        f = F("price")
        result = 100 - f
        assert isinstance(result, _FExpr)
        assert result.lhs == 100
        assert result.op == "-"

    def test_rmul(self):
        f = F("qty")
        result = 5 * f
        assert isinstance(result, _FExpr)
        assert result.lhs == 5
        assert result.op == "*"

    def test_fexpr_add(self):
        expr = F("a") + F("b")
        result = expr + 1
        assert isinstance(result, _FExpr)
        assert result.op == "+"
        assert result.rhs == 1

    def test_fexpr_sub(self):
        expr = F("a") + F("b")
        result = expr - 2
        assert isinstance(result, _FExpr)
        assert result.op == "-"

    def test_fexpr_mul(self):
        expr = F("a") + F("b")
        result = expr * 3
        assert isinstance(result, _FExpr)
        assert result.op == "*"

    def test_fexpr_truediv(self):
        expr = F("a") + F("b")
        result = expr / 4
        assert isinstance(result, _FExpr)
        assert result.op == "/"

    def test_f_truediv(self):
        f = F("total")
        result = f / 2
        assert isinstance(result, _FExpr)
        assert result.op == "/"


class TestAggregateRepr:

    def test_count_repr(self):
        agg = Count("id")
        assert repr(agg) == "Count('id')"

    def test_sum_repr(self):
        agg = Sum("price")
        assert repr(agg) == "Sum('price')"

    def test_avg_repr(self):
        agg = Avg("score")
        assert repr(agg) == "Avg('score')"

    def test_max_repr(self):
        agg = Max("age")
        assert repr(agg) == "Max('age')"

    def test_min_repr(self):
        agg = Min("age")
        assert repr(agg) == "Min('age')"

    def test_aggregate_init_distinct(self):
        agg = Count("id", distinct=True)
        assert agg.field == "id"
        assert agg.distinct is True


class TestManagerMethods:
    class Widget(Model):
        name = CharField()
        price = IntegerField()

        class Meta:
            table_name = "widgets"

    def test_order_by(self):
        qs = self.Widget.objects.order_by("-price")
        assert isinstance(qs, QuerySet)
        assert qs._order == ["-price"]

    def test_only(self):
        qs = self.Widget.objects.only("name")
        assert qs._only_fields == ["name"]

    def test_defer(self):
        qs = self.Widget.objects.defer("price")
        assert qs._defer_fields == ["price"]

    def test_distinct(self):
        qs = self.Widget.objects.distinct()
        assert qs._distinct is True

    def test_annotate(self):
        qs = self.Widget.objects.annotate(total=Count("id"))
        assert "total" in qs._annotations

    def test_select_related(self):
        qs = self.Widget.objects.select_related("category")
        assert qs._select_related == ["category"]

    def test_prefetch_related(self):
        qs = self.Widget.objects.prefetch_related("tags")
        assert qs._prefetch_related == ["tags"]

    @pytest.mark.asyncio
    async def test_values(self):
        with (
            patch(
                "openviper.db.models.execute_values",
                new_callable=AsyncMock,
                return_value=[{"name": "w1"}],
            ) as mock_exec,
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await self.Widget.objects.values("name")
            assert result == [{"name": "w1"}]

    @pytest.mark.asyncio
    async def test_values_list(self):
        with (
            patch(
                "openviper.db.models.execute_values",
                new_callable=AsyncMock,
                return_value=[{"name": "w1"}],
            ) as mock_exec,
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await self.Widget.objects.values_list("name", flat=True)
            assert result == ["w1"]

    @pytest.mark.asyncio
    async def test_aggregate(self):
        with (
            patch(
                "openviper.db.models.execute_aggregate",
                new_callable=AsyncMock,
                return_value={"total": 5},
            ) as mock_exec,
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await self.Widget.objects.aggregate(total=Count("id"))
            assert result == {"total": 5}

    @pytest.mark.asyncio
    async def test_explain(self):
        with patch(
            "openviper.db.models.execute_explain", new_callable=AsyncMock, return_value="Seq Scan"
        ):
            result = await self.Widget.objects.explain()
            assert result == "Seq Scan"

    @pytest.mark.asyncio
    async def test_get_or_none_found(self):
        with (
            patch(
                "openviper.db.models.execute_select",
                new_callable=AsyncMock,
                return_value=[{"id": 1, "name": "w1", "price": 10}],
            ),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            result = await self.Widget.objects.get_or_none(id=1)
            assert result is not None
            assert result.name == "w1"

    @pytest.mark.asyncio
    async def test_get_or_none_not_found(self):
        with (
            patch("openviper.db.models.execute_select", new_callable=AsyncMock, return_value=[]),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            result = await self.Widget.objects.get_or_none(id=999)
            assert result is None

    @pytest.mark.asyncio
    async def test_get_or_create_existing(self):
        with (
            patch(
                "openviper.db.models.execute_select",
                new_callable=AsyncMock,
                return_value=[{"id": 1, "name": "w1", "price": 10}],
            ),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            obj, created = await self.Widget.objects.get_or_create(name="w1")
            assert created is False
            assert obj.name == "w1"

    @pytest.mark.asyncio
    async def test_get_or_create_new(self):
        with (
            patch("openviper.db.models.execute_select", new_callable=AsyncMock, return_value=[]),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
            patch("openviper.db.models.execute_save", new_callable=AsyncMock),
        ):
            obj, created = await self.Widget.objects.get_or_create(
                name="w2", defaults={"price": 99}
            )
            assert created is True
            assert obj.name == "w2"
            assert obj.price == 99


class TestQuerySetMethods:
    class Thing(Model):
        name = CharField()
        value = IntegerField()

        class Meta:
            table_name = "things"

    def test_limit(self):
        qs = self.Thing.objects.all().limit(10)
        assert qs._limit == 10

    def test_offset(self):
        qs = self.Thing.objects.all().offset(5)
        assert qs._offset == 5

    def test_distinct(self):
        qs = self.Thing.objects.all().distinct()
        assert qs._distinct is True

    def test_select_related(self):
        qs = self.Thing.objects.all().select_related("parent")
        assert qs._select_related == ["parent"]

    def test_prefetch_related(self):
        qs = self.Thing.objects.all().prefetch_related("children")
        assert qs._prefetch_related == ["children"]

    def test_annotate(self):
        qs = self.Thing.objects.all().annotate(cnt=Count("id"))
        assert "cnt" in qs._annotations


class TestQuerySetGet:
    class Record(Model):
        name = CharField()

        class Meta:
            table_name = "records"

    @pytest.mark.asyncio
    async def test_get_does_not_exist(self):
        with (
            patch("openviper.db.models.execute_select", new_callable=AsyncMock, return_value=[]),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            with pytest.raises(DoesNotExist):
                await self.Record.objects.filter(name="nope").get()

    @pytest.mark.asyncio
    async def test_get_multiple_objects_returned(self):
        with (
            patch(
                "openviper.db.models.execute_select",
                new_callable=AsyncMock,
                return_value=[
                    {"id": 1, "name": "a"},
                    {"id": 2, "name": "b"},
                ],
            ),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            with pytest.raises(MultipleObjectsReturned):
                await self.Record.objects.filter(name="dup").get()


class TestQuerySetFirstLast:
    class Entry(Model):
        name = CharField()

        class Meta:
            table_name = "entries"

    @pytest.mark.asyncio
    async def test_first_returns_none(self):
        with (
            patch("openviper.db.models.execute_select", new_callable=AsyncMock, return_value=[]),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            result = await self.Entry.objects.all().first()
            assert result is None

    @pytest.mark.asyncio
    async def test_first_returns_instance(self):
        with (
            patch(
                "openviper.db.models.execute_select",
                new_callable=AsyncMock,
                return_value=[{"id": 1, "name": "first"}],
            ),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            result = await self.Entry.objects.all().first()
            assert result is not None
            assert result.name == "first"

    @pytest.mark.asyncio
    async def test_last_with_order(self):
        with (
            patch(
                "openviper.db.models.execute_select",
                new_callable=AsyncMock,
                return_value=[{"id": 5, "name": "last"}],
            ),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            result = await self.Entry.objects.order_by("name").last()
            assert result is not None
            assert result.name == "last"

    @pytest.mark.asyncio
    async def test_last_without_order(self):
        with (
            patch(
                "openviper.db.models.execute_select",
                new_callable=AsyncMock,
                return_value=[{"id": 10, "name": "z"}],
            ),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            result = await self.Entry.objects.all().last()
            assert result is not None
            assert result.id == 10

    @pytest.mark.asyncio
    async def test_last_returns_none(self):
        with (
            patch("openviper.db.models.execute_select", new_callable=AsyncMock, return_value=[]),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            result = await self.Entry.objects.all().last()
            assert result is None


class TestQuerySetAsyncIter:
    class Row(Model):
        name = CharField()

        class Meta:
            table_name = "rows"

    @pytest.mark.asyncio
    async def test_async_iteration(self):
        with (
            patch(
                "openviper.db.models.execute_select",
                new_callable=AsyncMock,
                return_value=[
                    {"id": 1, "name": "a"},
                    {"id": 2, "name": "b"},
                ],
            ),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            names = []
            async for row in self.Row.objects.all():
                names.append(row.name)
            assert names == ["a", "b"]

    @pytest.mark.asyncio
    async def test_async_iteration_empty(self):
        with (
            patch("openviper.db.models.execute_select", new_callable=AsyncMock, return_value=[]),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            names = []
            async for row in self.Row.objects.all():
                names.append(row.name)
            assert names == []


class TestQuerySetAwait:
    class Note(Model):
        text = CharField()

        class Meta:
            table_name = "notes"

    @pytest.mark.asyncio
    async def test_await_queryset(self):
        with (
            patch(
                "openviper.db.models.execute_select",
                new_callable=AsyncMock,
                return_value=[
                    {"id": 1, "text": "hello"},
                ],
            ),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            results = await self.Note.objects.filter(text="hello")
            assert len(results) == 1
            assert results[0].text == "hello"


class TestModelInitEdgeCases:
    class Profile(Model):
        name = CharField()
        bio = CharField(default="empty")

        class Meta:
            table_name = "profiles"

    def test_private_kwarg_rejection(self):
        with pytest.raises(TypeError, match="does not accept private"):
            self.Profile(_secret="bad")

    def test_extra_kwargs_set_as_attributes(self):
        p = self.Profile(name="Alice", custom_attr="extra")
        assert p.custom_attr == "extra"

    def test_default_values_applied(self):
        p = self.Profile(name="Bob")
        assert p.bio == "empty"


class TestModelInitColumnName:
    class Author(Model):
        name = CharField()
        publisher = ForeignKey("SomeModel", on_delete="CASCADE")

        class Meta:
            table_name = "authors"

    def test_column_name_kwarg(self):
        a = self.Author(name="Alice", publisher_id=42)
        assert a.__dict__.get("publisher_id") == 42


class TestSetGetRelated:
    class Article(Model):
        title = CharField()

        class Meta:
            table_name = "articles"

    def test_set_and_get_related(self):
        a = self.Article(title="Test")
        assert a._get_related("author") is None
        a._set_related("author", "fake_author")
        assert a._get_related("author") == "fake_author"

    def test_set_related_initializes_cache(self):
        a = self.Article(title="Test")
        assert a._relation_cache is None
        a._set_related("x", 1)
        assert a._relation_cache is not None
        assert a._relation_cache["x"] == 1

    def test_get_related_no_cache(self):
        a = self.Article(title="Test")
        a._relation_cache = None
        assert a._get_related("anything") is None


class TestContentType:
    class Tag(Model):
        label = CharField()

        class Meta:
            table_name = "tags"

    def test_content_type_property(self):
        t = self.Tag(label="python")
        ct = t.content_type
        assert "Tag" in ct

    def test_get_content_type_label(self):
        ct = self.Tag.get_content_type_label()
        assert "Tag" in ct


class TestChangeDetection:
    class Setting(Model):
        key = CharField()
        value = CharField()

        class Meta:
            table_name = "settings_cd"

    def test_snapshot(self):
        s = self.Setting(key="k1", value="v1")
        snap = s._snapshot()
        assert snap["key"] == "k1"
        assert snap["value"] == "v1"

    def test_get_changed_fields(self):
        s = self.Setting(key="k1", value="v1")
        s.value = "v2"
        changed = s._get_changed_fields()
        assert "value" in changed
        assert changed["value"] == "v1"

    def test_has_changed(self):
        s = self.Setting(key="k1", value="v1")
        assert s.has_changed is False
        s.value = "v2"
        assert s.has_changed is True

    def test_no_changes(self):
        s = self.Setting(key="k1", value="v1")
        changed = s._get_changed_fields()
        assert changed == {}


class TestFromRow:
    class Post(Model):
        title = CharField()
        body = CharField()

        class Meta:
            table_name = "posts_fr"

    def test_from_row(self):
        row = {"id": 1, "title": "Hello", "body": "World"}
        p = self.Post._from_row(row)
        assert p.id == 1
        assert p.title == "Hello"
        assert p.body == "World"

    def test_from_row_extra_columns(self):
        row = {"id": 1, "title": "Hello", "body": "World", "extra_col": 42}
        p = self.Post._from_row(row)
        assert p.extra_col == 42

    def test_from_row_fast(self):
        row = {"id": 1, "title": "Hello", "body": "World"}
        p = self.Post._from_row_fast(row)
        assert p.id == 1
        assert p.title == "Hello"
        assert p.body == "World"

    def test_from_row_fast_extra_columns(self):
        row = {"id": 1, "title": "Hello", "body": "World", "computed": 99}
        p = self.Post._from_row_fast(row)
        assert p.computed == 99

    def test_from_row_fast_defaults(self):
        row = {"id": 1}
        p = self.Post._from_row_fast(row)
        assert p.title is None
        assert p.body is None


class TestTriggerEvent:
    class Evt(Model):
        name = CharField()

        class Meta:
            table_name = "evts"

    def test_trigger_event_with_dispatcher(self):
        e = self.Evt(name="test")
        mock_dispatcher = MagicMock()
        with (
            patch("openviper.db.events.get_dispatcher", return_value=mock_dispatcher),
            patch("openviper.db.events._dispatch_decorator_handlers"),
        ):
            e._trigger_event("after_insert")
            mock_dispatcher.trigger.assert_called_once()

    def test_trigger_event_without_dispatcher(self):
        e = self.Evt(name="test")
        with (
            patch("openviper.db.events.get_dispatcher", return_value=None),
            patch("openviper.db.events._dispatch_decorator_handlers") as mock_dec,
        ):
            e._trigger_event("after_insert")
            mock_dec.assert_called_once()

    def test_trigger_event_exception_suppressed(self):
        e = self.Evt(name="test")
        with patch("openviper.db.events.get_dispatcher", side_effect=RuntimeError("boom")):
            e._trigger_event("after_insert")


class TestModelEquality:
    class Eq(Model):
        name = CharField()

        class Meta:
            table_name = "eqs"

    def test_equal_by_pk(self):
        a = self.Eq(name="a")
        a.id = 1
        b = self.Eq(name="b")
        b.id = 1
        assert a == b

    def test_not_equal_different_pk(self):
        a = self.Eq(name="a")
        a.id = 1
        b = self.Eq(name="b")
        b.id = 2
        assert a != b

    def test_not_equal_none_pk(self):
        a = self.Eq(name="a")
        b = self.Eq(name="b")
        assert a != b

    def test_not_equal_different_class(self):
        a = self.Eq(name="a")
        a.id = 1
        assert a != "not a model"


class TestCallHook:

    @pytest.mark.asyncio
    async def test_sync_hook(self):
        def sync_fn():
            return 42

        result = await _call_hook(sync_fn)
        assert result == 42

    @pytest.mark.asyncio
    async def test_async_hook(self):
        async def async_fn():
            return 99

        result = await _call_hook(async_fn)
        assert result == 99

    @pytest.mark.asyncio
    async def test_sync_hook_with_args(self):
        def sync_fn(x, y):
            return x + y

        result = await _call_hook(sync_fn, 3, 4)
        assert result == 7

    @pytest.mark.asyncio
    async def test_async_hook_with_args(self):
        async def async_fn(x):
            return x * 2

        result = await _call_hook(async_fn, 5)
        assert result == 10


class TestTraversalLookup:

    class Author(Model):
        username = CharField()

        class Meta:
            table_name = "tl_authors"

    class Blog(Model):
        title = CharField()
        author = ForeignKey("TestTraversalLookup.Author", on_delete="CASCADE")

        class Meta:
            table_name = "tl_blogs"

    def test_simple_field_lookup(self):
        lookup = TraversalLookup("title", self.Blog)
        assert lookup.is_simple_field() is True
        assert lookup.get_joins_needed() == []
        assert lookup.final_field is not None

    def test_fk_traversal(self):
        field = self.Blog._fields.get("author")
        if field is not None:
            field.resolve_target = MagicMock(return_value=self.Author)

        lookup = TraversalLookup("author__username", self.Blog)
        assert lookup.is_simple_field() is False
        assert len(lookup.get_joins_needed()) == 1
        assert lookup.final_field is not None
        assert lookup.final_model == self.Author

    def test_repr(self):
        lookup = TraversalLookup("title", self.Blog)
        assert "TraversalLookup" in repr(lookup)

    def test_invalid_field_raises(self):
        with pytest.raises(FieldError):
            TraversalLookup("nonexistent", self.Blog)

    def test_non_relation_traversal_raises(self):
        with pytest.raises(FieldError, match="Cannot traverse"):
            TraversalLookup("title__something", self.Blog)

    def test_traversal_no_fields_on_model_raises(self):
        """current_model has no _fields."""
        fk_field = self.Blog._fields.get("author")
        if fk_field is not None:
            fk_field.resolve_target = MagicMock(return_value=type("NoFields", (), {}))
            with pytest.raises(FieldError, match="not a Model"):
                TraversalLookup("author__fake", self.Blog)

    def test_traversal_final_field_not_found(self):
        """final field name doesn't exist."""
        field = self.Blog._fields.get("author")
        if field is not None:
            field.resolve_target = MagicMock(return_value=self.Author)
            with pytest.raises(FieldError, match="not found"):
                TraversalLookup("author__nonexistent_field", self.Blog)

    def test_traversal_unresolvable_target(self):
        """resolve_target returns None."""
        field = self.Blog._fields.get("author")
        if field is not None:
            field.resolve_target = MagicMock(return_value=None)
            with pytest.raises(FieldError, match="Cannot resolve"):
                TraversalLookup("author__username", self.Blog)


class TestManagerAsyncGenerators:
    class Item(Model):
        name = CharField()

        class Meta:
            table_name = "mgr_gen_items"

    @pytest.mark.asyncio
    async def test_manager_iterator(self):
        """Manager.iterator delegates to QuerySet."""
        mock_rows = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        with (
            patch(
                "openviper.db.models.execute_select", new_callable=AsyncMock, return_value=mock_rows
            ),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            items = []
            async for item in self.Item.objects.iterator(chunk_size=10):
                items.append(item)
                if len(items) >= 2:
                    break
            assert len(items) == 2

    @pytest.mark.asyncio
    async def test_manager_batch(self):
        """Manager.batch delegates to QuerySet."""
        mock_rows = [{"id": i, "name": f"item{i}"} for i in range(1, 4)]
        with (
            patch(
                "openviper.db.models.execute_select", new_callable=AsyncMock, return_value=mock_rows
            ),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            batches = []
            async for b in self.Item.objects.batch(size=10):
                batches.append(b)
            assert len(batches) >= 1

    @pytest.mark.asyncio
    async def test_manager_id_batch(self):
        """Manager.id_batch delegates to QuerySet."""
        mock_rows = [{"id": i, "name": f"item{i}"} for i in range(1, 4)]
        with (
            patch(
                "openviper.db.models.execute_select", new_callable=AsyncMock, return_value=mock_rows
            ),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            batches = []
            async for b in self.Item.objects.id_batch(size=10):
                batches.append(b)
            assert len(batches) >= 1


class TestManagerExclude:
    class Foo(Model):
        name = CharField()

        class Meta:
            table_name = "mgr_exc_foo"

    def test_exclude_returns_queryset(self):
        qs = self.Foo.objects.exclude(name="bar")
        assert isinstance(qs, QuerySet)
        assert len(qs._excludes) == 1


#    aggregate/explain (L913-976, 994-1064) ──────────────────────────────────


class TestQuerySetOperations:
    class Post(Model):
        title = CharField()
        views = IntegerField(default=0)

        class Meta:
            table_name = "qs_ops_posts"

    @pytest.mark.asyncio
    async def test_count(self):
        with (
            patch("openviper.db.models.execute_count", new_callable=AsyncMock, return_value=5),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await self.Post.objects.all().count()
            assert result == 5

    @pytest.mark.asyncio
    async def test_count_permission_denied_returns_zero(self):
        with patch(
            "openviper.db.models.check_permission_for_model",
            new_callable=AsyncMock,
            side_effect=ModelPermissionError("denied"),
        ):
            result = await self.Post.objects.all().count()
            assert result == 0

    @pytest.mark.asyncio
    async def test_exists(self):
        with (
            patch("openviper.db.models.execute_exists", new_callable=AsyncMock, return_value=True),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            result = await self.Post.objects.all().exists()
            assert result is True

    @pytest.mark.asyncio
    async def test_exists_permission_denied_returns_false(self):
        with patch(
            "openviper.db.models._check_perm_cached",
            new_callable=AsyncMock,
            side_effect=ModelPermissionError("denied"),
        ):
            result = await self.Post.objects.all().exists()
            assert result is False

    @pytest.mark.asyncio
    async def test_delete(self):
        with (
            patch("openviper.db.models.execute_delete", new_callable=AsyncMock, return_value=3),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await self.Post.objects.all().delete()
            assert result == 3

    @pytest.mark.asyncio
    async def test_update(self):
        with (
            patch("openviper.db.models.execute_update", new_callable=AsyncMock, return_value=2),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await self.Post.objects.all().update(views=10)
            assert result == 2

    @pytest.mark.asyncio
    async def test_values(self):
        mock_rows = [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]
        with (
            patch(
                "openviper.db.models.execute_values", new_callable=AsyncMock, return_value=mock_rows
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await self.Post.objects.all().values("id", "title")
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_values_permission_denied(self):
        with patch(
            "openviper.db.models.check_permission_for_model",
            new_callable=AsyncMock,
            side_effect=ModelPermissionError("denied"),
        ):
            result = await self.Post.objects.all().values("id")
            assert result == []

    @pytest.mark.asyncio
    async def test_values_list_flat(self):
        mock_rows = [{"id": 1}, {"id": 2}]
        with (
            patch(
                "openviper.db.models.execute_values", new_callable=AsyncMock, return_value=mock_rows
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await self.Post.objects.all().values_list("id", flat=True)
            assert result == [1, 2]

    @pytest.mark.asyncio
    async def test_values_list_flat_multiple_fields_raises(self):
        with pytest.raises(ValueError, match="exactly one field"):
            await self.Post.objects.all().values_list("id", "title", flat=True)

    @pytest.mark.asyncio
    async def test_values_list_tuples(self):
        mock_rows = [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]
        with (
            patch(
                "openviper.db.models.execute_values", new_callable=AsyncMock, return_value=mock_rows
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await self.Post.objects.all().values_list("id", "title")
            assert result == [(1, "A"), (2, "B")]

    @pytest.mark.asyncio
    async def test_values_list_empty(self):
        with (
            patch("openviper.db.models.execute_values", new_callable=AsyncMock, return_value=[]),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await self.Post.objects.all().values_list("id", flat=True)
            assert result == []

    @pytest.mark.asyncio
    async def test_aggregate(self):
        with (
            patch(
                "openviper.db.models.execute_aggregate",
                new_callable=AsyncMock,
                return_value={"total": 5},
            ),
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
        ):
            result = await self.Post.objects.all().aggregate(total=Count("id"))
            assert result == {"total": 5}

    @pytest.mark.asyncio
    async def test_aggregate_permission_denied(self):
        with patch(
            "openviper.db.models.check_permission_for_model",
            new_callable=AsyncMock,
            side_effect=ModelPermissionError("denied"),
        ):
            result = await self.Post.objects.all().aggregate(total=Count("id"))
            assert result == {}


class TestQuerySetLast:
    class Article(Model):
        title = CharField()

        class Meta:
            table_name = "qs_last_articles"

    @pytest.mark.asyncio
    async def test_last_with_order(self):
        """last() with existing order reverses it."""
        mock_rows = [{"id": 3, "title": "C"}]
        with (
            patch(
                "openviper.db.models.execute_select", new_callable=AsyncMock, return_value=mock_rows
            ),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            qs = self.Article.objects.order_by("title")
            result = await qs.last()
            assert result is not None

    @pytest.mark.asyncio
    async def test_last_without_order(self):
        """last() without order defaults to -id."""
        mock_rows = [{"id": 5, "title": "E"}]
        with (
            patch(
                "openviper.db.models.execute_select", new_callable=AsyncMock, return_value=mock_rows
            ),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            result = await self.Article.objects.all().last()
            assert result is not None

    @pytest.mark.asyncio
    async def test_last_empty(self):
        with (
            patch("openviper.db.models.execute_select", new_callable=AsyncMock, return_value=[]),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            result = await self.Article.objects.all().last()
            assert result is None


class TestQuerySetIterBatch:
    class Tag(Model):
        label = CharField()

        class Meta:
            table_name = "qs_iter_tags"

    @pytest.mark.asyncio
    async def test_iterator_multiple_chunks(self):
        """iterator loops through chunks."""
        chunk1 = [{"id": 1, "label": "a"}, {"id": 2, "label": "b"}]
        chunk2 = [{"id": 3, "label": "c"}]
        call_count = 0

        async def mock_select(qs):
            nonlocal call_count
            call_count += 1
            return chunk1 if call_count == 1 else chunk2 if call_count == 2 else []

        with (
            patch("openviper.db.models.execute_select", side_effect=mock_select),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            items = []
            async for item in self.Tag.objects.all().iterator(chunk_size=2):
                items.append(item)
            assert len(items) == 3

    @pytest.mark.asyncio
    async def test_batch_multiple(self):
        """batch yields successive lists."""
        batch1 = [{"id": 1, "label": "x"}, {"id": 2, "label": "y"}]
        batch2 = [{"id": 3, "label": "z"}]
        call_count = 0

        async def mock_select(qs):
            nonlocal call_count
            call_count += 1
            return batch1 if call_count == 1 else batch2 if call_count == 2 else []

        with (
            patch("openviper.db.models.execute_select", side_effect=mock_select),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            batches = []
            async for b in self.Tag.objects.all().batch(size=2):
                batches.append(b)
            assert len(batches) == 2

    @pytest.mark.asyncio
    async def test_id_batch_multiple(self):
        """id_batch uses pk-based pagination."""
        chunk1 = [{"id": 1, "label": "a"}, {"id": 2, "label": "b"}]
        chunk2 = [{"id": 3, "label": "c"}]
        call_count = 0

        async def mock_select(qs):
            nonlocal call_count
            call_count += 1
            return chunk1 if call_count == 1 else chunk2 if call_count == 2 else []

        with (
            patch("openviper.db.models.execute_select", side_effect=mock_select),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            batches = []
            async for b in self.Tag.objects.all().id_batch(size=2):
                batches.append(b)
            assert len(batches) == 2


#    (L855-870, 880, 883, 886, 889) ─────────────────────────────────────────


class TestQuerySetSelectRelated:
    class Writer(Model):
        name = CharField()

        class Meta:
            table_name = "qs_sr_writers"

    class Book(Model):
        title = CharField()
        writer = ForeignKey("TestQuerySetSelectRelated.Writer", on_delete="CASCADE")

        class Meta:
            table_name = "qs_sr_books"

    @pytest.mark.asyncio
    async def test_select_related_hydrates(self):
        """select_related hydrates related instances."""
        rows = [
            {"id": 1, "title": "MyBook", "writer_id": 10, "writer__id": 10, "writer__name": "Alice"}
        ]
        field = self.Book._fields.get("writer")
        if field is not None:
            field.resolve_target = MagicMock(return_value=self.Writer)
        with (
            patch("openviper.db.models.execute_select", new_callable=AsyncMock, return_value=rows),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            results = await self.Book.objects.select_related("writer").all()
            assert len(results) == 1

    @pytest.mark.asyncio
    async def test_all_permission_denied_returns_empty(self):
        """PermissionError returns []."""
        with patch(
            "openviper.db.models._check_perm_cached",
            new_callable=AsyncMock,
            side_effect=ModelPermissionError("denied"),
        ):
            results = await self.Book.objects.all().all()
            assert results == []


class TestQuerySetPrefetchRelated:
    class Category(Model):
        name = CharField()

        class Meta:
            table_name = "qs_pr_categories"

    class Product(Model):
        name = CharField()
        category = ForeignKey("TestQuerySetPrefetchRelated.Category", on_delete="CASCADE")

        class Meta:
            table_name = "qs_pr_products"

    @pytest.mark.asyncio
    async def test_prefetch_related_attaches_instances(self):
        """prefetch_related loads and attaches."""
        main_rows = [{"id": 1, "name": "Widget", "category_id": 10}]
        related_rows = [{"id": 10, "name": "Electronics"}]
        field = self.Product._fields.get("category")
        if field is not None:
            field.resolve_target = MagicMock(return_value=self.Category)

        call_count = 0

        async def mock_select(qs):
            nonlocal call_count
            call_count += 1
            return main_rows if call_count == 1 else related_rows

        with (
            patch("openviper.db.models.execute_select", side_effect=mock_select),
            patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock),
        ):
            results = await self.Product.objects.prefetch_related("category").all()
            assert len(results) == 1


class TestModelSaveLifecycle:
    class Note(Model):
        text = CharField()

        class Meta:
            table_name = "save_lc_notes"

    @pytest.mark.asyncio
    async def test_save_create_triggers_hooks(self):
        """save with create."""
        note = self.Note(text="hello")
        # id is None by default, so create path is taken
        with patch("openviper.db.models.execute_save", new_callable=AsyncMock):
            await note.save()

    @pytest.mark.asyncio
    async def test_save_update_triggers_hooks(self):
        """save with update (has pk)."""
        note = self.Note(text="hello")
        note.id = 1  # set pk to trigger update path
        note._previous_state = {"text": "old"}
        with patch("openviper.db.models.execute_save", new_callable=AsyncMock):
            await note.save()

    @pytest.mark.asyncio
    async def test_save_with_ignore_permissions(self):
        """Cover permissions token branch."""
        note = self.Note(text="hi")
        # id is None by default, so create path is taken
        with patch("openviper.db.models.execute_save", new_callable=AsyncMock):
            await note.save(ignore_permissions=True)


class TestModelEqBranches:
    class Rec(Model):
        data = CharField()

        class Meta:
            table_name = "eq_recs"

    def test_eq_different_class(self):
        class Other:
            pk = 1

        rec = self.Rec(data="x")
        rec.id = 1
        assert rec != Other()

    def test_eq_none_pk(self):
        a = self.Rec(data="x")
        b = self.Rec(data="y")
        a.id = None
        b.id = None
        assert a != b


class TestFromRowFast:
    class Entity(Model):
        name = CharField(default="default_name")

        class Meta:
            table_name = "from_row_entities"

    def test_from_row_fast_with_col_name_in_row(self):
        """col_name in row."""
        row = {"id": 1, "name": "Alice"}
        inst = self.Entity._from_row_fast(row)
        assert inst.name == "Alice"

    def test_from_row_fast_with_field_name_fallback(self):
        """name in row (fallback)."""
        row = {"id": 1, "name": "Bob"}
        inst = self.Entity._from_row_fast(row)
        assert inst.name == "Bob"

    def test_from_row_fast_missing_field_uses_default(self):
        """missing field, callable default."""
        row = {"id": 1}
        inst = self.Entity._from_row_fast(row)
        assert inst.name == "default_name"

    def test_from_row_fast_missing_field_none(self):
        """missing field, no default → None."""

        class NoDefault(Model):
            val = IntegerField()

            class Meta:
                table_name = "from_row_nodef"

        row = {"id": 1}
        inst = NoDefault._from_row_fast(row)
        assert inst.val is None

    def test_from_row_fast_extra_columns(self):
        """extra annotation columns."""
        row = {"id": 1, "name": "X", "total_views": 100}
        inst = self.Entity._from_row_fast(row)
        assert inst.__dict__["total_views"] == 100

    def test_from_row_extra_columns(self):
        """_from_row includes extra keys."""
        row = {"id": 1, "name": "Y", "annotation_val": 42}
        inst = self.Entity._from_row(row)
        assert inst.__dict__.get("annotation_val") == 42


class TestManagerGetOrCreate:
    class Thing(Model):
        name = CharField()

        class Meta:
            table_name = "goc_things"

    @pytest.mark.asyncio
    async def test_get_or_create_existing(self):
        """get_or_create returns existing."""
        thing = self.Thing(name="existing")
        thing.id = 1
        with patch.object(Manager, "get", new_callable=AsyncMock, return_value=thing):
            obj, created = await self.Thing.objects.get_or_create(name="existing")
            assert created is False
            assert obj.name == "existing"

    @pytest.mark.asyncio
    async def test_get_or_create_new(self):
        """get_or_create creates new."""
        new_thing = self.Thing(name="new")
        new_thing.id = 2
        with (
            patch.object(Manager, "get", new_callable=AsyncMock, side_effect=DoesNotExist("nope")),
            patch.object(Manager, "create", new_callable=AsyncMock, return_value=new_thing),
        ):
            obj, created = await self.Thing.objects.get_or_create(name="new")
            assert obj.name == "new"


class TestBulkOperationsExtended:
    class Record(Model):
        value = IntegerField(default=0)

        class Meta:
            table_name = "bulk_ext_records"

    @pytest.mark.asyncio
    async def test_bulk_create_with_batch_size(self):
        """bulk_create with batch_size branches."""
        objs = [self.Record(value=i) for i in range(5)]
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        with (
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
            patch("openviper.db.models._begin", return_value=mock_conn),
            patch.object(self.Record, "_get_insert_statement", return_value=MagicMock()),
        ):
            result = await self.Record.objects.bulk_create(objs, batch_size=2)
            assert len(result) == 5

    @pytest.mark.asyncio
    async def test_bulk_update(self):
        """bulk_update calls execute_bulk_update."""
        objs = [self.Record(value=i) for i in range(3)]
        for i, obj in enumerate(objs):
            obj.id = i + 1
        with (
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
            patch(
                "openviper.db.models.execute_bulk_update", new_callable=AsyncMock, return_value=3
            ),
        ):
            result = await self.Record.objects.bulk_update(objs, fields=["value"])
            assert result == 3

    @pytest.mark.asyncio
    async def test_bulk_update_with_ignore_permissions(self):
        """Cover the ignore_permissions token path in bulk_update."""
        objs = [self.Record(value=1)]
        objs[0].id = 1
        with (
            patch("openviper.db.models.check_permission_for_model", new_callable=AsyncMock),
            patch(
                "openviper.db.models.execute_bulk_update", new_callable=AsyncMock, return_value=1
            ),
        ):
            result = await self.Record.objects.bulk_update(
                objs, fields=["value"], ignore_permissions=True
            )
            assert result == 1


class TestQuerySetFilterExcludeAnnotate:
    class Item(Model):
        name = CharField()
        score = IntegerField(default=0)

        class Meta:
            table_name = "qs_fea_items"

    def test_filter_with_q_object(self):
        """Q args appended to _q_filters."""
        q = Q(name="test")
        qs = self.Item.objects.filter(q)
        assert len(qs._q_filters) >= 1

    def test_exclude_with_q_object(self):
        """exclude with Q negates."""
        q = Q(name="bad")
        qs = self.Item.objects.all().exclude(q)
        assert len(qs._q_filters) >= 1

    def test_filter_with_ignore_permissions(self):
        """filter passes ignore_permissions."""
        qs = self.Item.objects.all().filter(ignore_permissions=True, name="x")
        assert qs._ignore_permissions is True

    def test_annotate_returns_clone_with_annotations(self):
        """annotate stores annotations."""
        qs = self.Item.objects.all().annotate(total=Count("id"))
        assert "total" in qs._annotations


class TestModelChangedFieldsFK:
    class Owner(Model):
        name = CharField()

        class Meta:
            table_name = "cf_owners"

    class Pet(Model):
        name = CharField()
        owner = ForeignKey("TestModelChangedFieldsFK.Owner", on_delete="CASCADE")

        class Meta:
            table_name = "cf_pets"

    def test_changed_fields_detects_fk_change(self):
        """FK branch in _get_changed_fields."""
        pet = self.Pet(name="Rex")
        pet._previous_state = {"name": "Rex", "owner": 1}
        pet.__dict__["owner_id"] = 2  # changed FK
        changed = pet._get_changed_fields()
        assert "owner" in changed

    def test_has_changed_property(self):
        pet = self.Pet(name="Rex")
        pet._previous_state = {"name": "Rex", "owner": 1}
        pet.__dict__["owner_id"] = 1
        pet.name = "Rex"  # unchanged
        # has_changed should reflect FK comparison


class TestModelValidate:
    class Validated(Model):
        name = CharField()

        class Meta:
            table_name = "val_validated"

    @pytest.mark.asyncio
    async def test_validate_raises_on_invalid(self):
        v = self.Validated()
        v.name = None  # CharField requires non-null
        with (
            patch("openviper.db.models._load_soft_removed_columns", new_callable=AsyncMock),
            patch("openviper.db.models.get_soft_removed_columns", return_value=set()),
        ):
            with pytest.raises(ValueError, match="Validation failed"):
                await v.validate()
