"""Tests for features added during the model parity audit.

Covers: SmallIntegerField, BigAutoField, NullBooleanField, DurationField,
GenericIPAddressField, CheckConstraint, UniqueConstraint, Meta.constraints,
Meta.managed, Meta.proxy, conditional Index, Manager.update_or_create,
Manager.in_bulk, Manager.from_queryset, QuerySet.select_for_update,
Model.full_clean, Model.clean, Model.get_deferred_fields, Model.__str__,
AddConstraint and RemoveConstraint migration operations.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.db.fields import (
    BigAutoField,
    BooleanField,
    CharField,
    CheckConstraint,
    Constraint,
    DurationField,
    GenericIPAddressField,
    IntegerField,
    NullBooleanField,
    SmallIntegerField,
    UniqueConstraint,
)
from openviper.db.migrations.executor import AddConstraint, RemoveConstraint, _get_dialect
from openviper.db.models import Index, Manager, Model, ModelMeta, QuerySet
from openviper.exceptions import DoesNotExist

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_model_registry():
    old_reg = ModelMeta.registry.copy()
    old_idx = ModelMeta._name_index.copy()
    ModelMeta.registry.clear()
    ModelMeta._name_index.clear()
    yield
    ModelMeta.registry = old_reg
    ModelMeta._name_index = old_idx


# ── SmallIntegerField ─────────────────────────────────────────────────────────


class TestSmallIntegerField:
    def test_column_type_is_smallint(self) -> None:
        f = SmallIntegerField()
        assert f._column_type == "SMALLINT"

    def test_to_python_rejects_upper_bound(self) -> None:
        f = SmallIntegerField()
        f.name = "rank"
        with pytest.raises(ValueError, match="bounds"):
            f.to_python(32768)

    def test_to_python_rejects_lower_bound(self) -> None:
        f = SmallIntegerField()
        f.name = "rank"
        with pytest.raises(ValueError, match="bounds"):
            f.to_python(-32769)

    def test_to_python_accepts_boundary_values(self) -> None:
        f = SmallIntegerField()
        f.name = "rank"
        assert f.to_python(32767) == 32767
        assert f.to_python(-32768) == -32768

    def test_inherits_integer_field(self) -> None:
        from openviper.db.fields import IntegerField

        assert issubclass(SmallIntegerField, IntegerField)


# ── BigAutoField ──────────────────────────────────────────────────────────────


class TestBigAutoField:
    def test_is_primary_key_with_auto_increment(self) -> None:
        f = BigAutoField()
        assert f.primary_key is True
        assert f.auto_increment is True

    def test_column_type_is_bigint(self) -> None:
        f = BigAutoField()
        assert f._column_type == "BIGINT"

    def test_to_python_converts_int(self) -> None:
        f = BigAutoField()
        f.name = "id"
        assert f.to_python("42") == 42

    def test_to_python_none_returns_none(self) -> None:
        f = BigAutoField()
        f.name = "id"
        assert f.to_python(None) is None

    def test_to_python_rejects_overflow(self) -> None:
        f = BigAutoField()
        f.name = "id"
        with pytest.raises(ValueError, match="bounds"):
            f.to_python(9223372036854775808)


# ── NullBooleanField ──────────────────────────────────────────────────────────


class TestNullBooleanField:
    def test_null_is_true_by_default(self) -> None:
        f = NullBooleanField()
        assert f.null is True

    def test_accepts_none_value(self) -> None:
        f = NullBooleanField()
        f.name = "active"
        f.validate(None)

    def test_accepts_true_and_false(self) -> None:
        f = NullBooleanField()
        f.name = "active"
        f.validate(True)
        f.validate(False)

    def test_inherits_boolean_field(self) -> None:
        assert issubclass(NullBooleanField, BooleanField)


# ── DurationField ─────────────────────────────────────────────────────────────


class TestDurationField:
    def test_column_type_is_bigint(self) -> None:
        f = DurationField()
        assert f._column_type == "BIGINT"

    def test_to_python_timedelta_passthrough(self) -> None:
        f = DurationField()
        delta = datetime.timedelta(seconds=90)
        assert f.to_python(delta) == delta

    def test_to_python_microseconds_int(self) -> None:
        f = DurationField()
        result = f.to_python(1_000_000)
        assert result == datetime.timedelta(seconds=1)

    def test_to_python_none_returns_none(self) -> None:
        f = DurationField()
        assert f.to_python(None) is None

    def test_to_db_timedelta_to_microseconds(self) -> None:
        f = DurationField()
        delta = datetime.timedelta(seconds=2)
        assert f.to_db(delta) == 2_000_000

    def test_to_db_none_returns_none(self) -> None:
        f = DurationField()
        assert f.to_db(None) is None

    def test_to_db_int_passthrough(self) -> None:
        f = DurationField()
        assert f.to_db(500) == 500


# ── GenericIPAddressField ─────────────────────────────────────────────────────


class TestGenericIPAddressField:
    def test_default_max_length_is_39(self) -> None:
        f = GenericIPAddressField()
        assert f.max_length == 39

    def test_invalid_protocol_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid protocol"):
            GenericIPAddressField(protocol="UDP")

    def test_valid_ipv4_passes_both_protocol(self) -> None:
        f = GenericIPAddressField(protocol="both")
        f.name = "ip"
        f.validate("192.168.1.1")

    def test_valid_ipv6_passes_both_protocol(self) -> None:
        f = GenericIPAddressField(protocol="both")
        f.name = "ip"
        f.validate("::1")

    def test_invalid_ip_raises_on_validate(self) -> None:
        f = GenericIPAddressField()
        f.name = "ip"
        with pytest.raises(ValueError, match="not a valid IP"):
            f.validate("999.999.999.999")

    def test_ipv6_raises_for_ipv4_only_protocol(self) -> None:
        f = GenericIPAddressField(protocol="IPv4")
        f.name = "ip"
        with pytest.raises(ValueError, match="IPv4"):
            f.validate("::1")

    def test_ipv4_raises_for_ipv6_only_protocol(self) -> None:
        f = GenericIPAddressField(protocol="IPv6")
        f.name = "ip"
        with pytest.raises(ValueError, match="IPv6"):
            f.validate("192.168.1.1")

    def test_to_python_normalizes_ip(self) -> None:
        f = GenericIPAddressField()
        assert f.to_python("::0001") == "::1"

    def test_to_python_none_returns_none(self) -> None:
        f = GenericIPAddressField()
        assert f.to_python(None) is None

    def test_unpack_ipv4_mapped(self) -> None:
        f = GenericIPAddressField(protocol="both", unpack_ipv4=True)
        result = f.to_python("::ffff:192.0.2.1")
        assert result == "192.0.2.1"

    def test_to_python_skips_unpack_when_not_mapped(self) -> None:
        f = GenericIPAddressField(protocol="both", unpack_ipv4=True)
        result = f.to_python("::1")
        assert result == "::1"


# ── Constraint classes ────────────────────────────────────────────────────────


class TestConstraint:
    def test_base_constraint_stores_name(self) -> None:
        c = Constraint(name="my_constraint")
        assert c.name == "my_constraint"

    def test_repr_contains_name(self) -> None:
        c = Constraint(name="x")
        assert "x" in repr(c)


class TestCheckConstraint:
    def test_stores_name_and_check(self) -> None:
        c = CheckConstraint(name="price_positive", check="price > 0")
        assert c.name == "price_positive"
        assert c.check == "price > 0"

    def test_repr(self) -> None:
        c = CheckConstraint(name="cn", check="val > 0")
        r = repr(c)
        assert "CheckConstraint" in r
        assert "cn" in r
        assert "val > 0" in r

    def test_is_subclass_of_constraint(self) -> None:
        assert issubclass(CheckConstraint, Constraint)


class TestUniqueConstraint:
    def test_stores_fields_name_condition(self) -> None:
        c = UniqueConstraint(fields=["slug"], name="uq_slug", condition="published=1")
        assert c.fields == ["slug"]
        assert c.name == "uq_slug"
        assert c.condition == "published=1"

    def test_condition_defaults_to_none(self) -> None:
        c = UniqueConstraint(fields=["email"], name="uq_email")
        assert c.condition is None

    def test_repr(self) -> None:
        c = UniqueConstraint(fields=["a", "b"], name="uq_ab")
        r = repr(c)
        assert "UniqueConstraint" in r
        assert "uq_ab" in r

    def test_is_subclass_of_constraint(self) -> None:
        assert issubclass(UniqueConstraint, Constraint)


# ── Meta.constraints / Meta.managed / Meta.proxy ──────────────────────────────


class TestMetaConstraints:
    def test_constraints_stored_on_model(self) -> None:
        cc = CheckConstraint(name="pos", check="amount > 0")

        class Product(Model):
            amount = IntegerField(default=0)

            class Meta:
                table_name = "products_test"
                constraints = [cc]

        assert Product._meta_constraints == [cc]

    def test_no_constraints_defaults_to_empty(self) -> None:
        class Widget(Model):
            name = CharField(max_length=50)

            class Meta:
                table_name = "widgets_test"

        assert Widget._meta_constraints == []


class TestMetaManaged:
    def test_managed_true_by_default(self) -> None:
        class ManagedModel(Model):
            class Meta:
                table_name = "managed_test"

        assert ManagedModel._is_managed is True

    def test_managed_false_stored(self) -> None:
        class UnmanagedModel(Model):
            class Meta:
                table_name = "unmanaged_test"
                managed = False

        assert UnmanagedModel._is_managed is False


class TestMetaProxy:
    def test_proxy_false_by_default(self) -> None:
        class BaseModel(Model):
            name = CharField(max_length=50)

            class Meta:
                table_name = "base_proxy_test"

        assert BaseModel._is_proxy is False

    def test_proxy_inherits_parent_table(self) -> None:
        class ParentModel(Model):
            name = CharField(max_length=50)

            class Meta:
                table_name = "parent_proxy_test"

        class ChildProxy(ParentModel):
            class Meta:
                proxy = True

        assert ChildProxy._is_proxy is True
        assert ChildProxy._table_name == "parent_proxy_test"


# ── Conditional Index ─────────────────────────────────────────────────────────


class TestConditionalIndex:
    def test_index_stores_condition(self) -> None:
        idx = Index(fields=["slug"], condition="published = 1")
        assert idx.condition == "published = 1"

    def test_index_condition_defaults_to_none(self) -> None:
        idx = Index(fields=["slug"])
        assert idx.condition is None

    def test_index_with_name_and_condition(self) -> None:
        idx = Index(fields=["slug"], name="idx_pub_slug", condition="published = 1")
        assert idx.name == "idx_pub_slug"
        assert idx.condition == "published = 1"


# ── Manager.update_or_create ──────────────────────────────────────────────────


class TestManagerUpdateOrCreate:
    class Post(Model):
        title = CharField(max_length=200)
        slug = CharField(max_length=200)

        class Meta:
            table_name = "posts_uoc_test"

    @pytest.mark.asyncio
    async def test_creates_when_not_found(self) -> None:
        created_obj = self.Post(title="Hello", slug="hello")
        created_obj.id = 1

        with (
            patch.object(Manager, "get", new_callable=AsyncMock, side_effect=DoesNotExist("Post")),
            patch.object(Manager, "create", new_callable=AsyncMock, return_value=created_obj),
        ):
            obj, created = await Manager(self.Post).update_or_create(
                slug="hello", defaults={"title": "Hello"}
            )
        assert created is True
        assert obj is created_obj

    @pytest.mark.asyncio
    async def test_updates_when_found(self) -> None:
        existing = self.Post(title="Old Title", slug="hello")
        existing.id = 1

        with (
            patch.object(Manager, "get", new_callable=AsyncMock, return_value=existing),
            patch.object(existing, "save", new_callable=AsyncMock),
        ):
            obj, created = await Manager(self.Post).update_or_create(
                slug="hello", defaults={"title": "New Title"}
            )
        assert created is False
        assert obj.title == "New Title"


# ── Manager.in_bulk ───────────────────────────────────────────────────────────


class TestManagerInBulk:
    class Article(Model):
        title = CharField(max_length=200)

        class Meta:
            table_name = "articles_bulk_test"

    @pytest.mark.asyncio
    async def test_returns_dict_keyed_by_id(self) -> None:
        a1 = self.Article(title="A1")
        a1.id = 1
        a2 = self.Article(title="A2")
        a2.id = 2

        mock_qs = MagicMock()
        mock_qs.filter.return_value = mock_qs
        mock_qs.all = AsyncMock(return_value=[a1, a2])

        with patch("openviper.db.models.QuerySet", return_value=mock_qs):
            result = await Manager(self.Article).in_bulk([1, 2])

        assert result[1] is a1
        assert result[2] is a2

    @pytest.mark.asyncio
    async def test_in_bulk_no_id_list_fetches_all(self) -> None:
        a1 = self.Article(title="All")
        a1.id = 10

        mock_qs = MagicMock()
        mock_qs.all = AsyncMock(return_value=[a1])

        with patch("openviper.db.models.QuerySet", return_value=mock_qs):
            result = await Manager(self.Article).in_bulk()

        assert result[10] is a1


# ── Manager.from_queryset ─────────────────────────────────────────────────────


class TestManagerFromQueryset:
    class BlogPost(Model):
        published = IntegerField(default=0)

        class Meta:
            table_name = "blog_qs_test"

    def test_returns_manager_subclass(self) -> None:
        class CustomQS(QuerySet):
            def published_only(self) -> QuerySet:
                return self.filter(published=1)

        CustomManager = Manager.from_queryset(CustomQS)
        assert issubclass(CustomManager, Manager)

    def test_all_returns_custom_queryset_type(self) -> None:
        class CustomQS(QuerySet):
            pass

        CustomManager = Manager.from_queryset(CustomQS)
        mgr = CustomManager(self.BlogPost)
        result = mgr.all()
        assert isinstance(result, CustomQS)

    def test_filter_returns_custom_queryset_type(self) -> None:
        class CustomQS(QuerySet):
            pass

        CustomManager = Manager.from_queryset(CustomQS)
        mgr = CustomManager(self.BlogPost)
        result = mgr.filter(published=1)
        assert isinstance(result, CustomQS)

    def test_manager_name_reflects_queryset_class(self) -> None:
        class SpecialQS(QuerySet):
            pass

        CustomManager = Manager.from_queryset(SpecialQS)
        assert "SpecialQS" in CustomManager.__name__


# ── QuerySet.select_for_update ────────────────────────────────────────────────


class TestQuerySetSelectForUpdate:
    class Item(Model):
        name = CharField(max_length=100)

        class Meta:
            table_name = "items_sfu_test"

    def test_returns_queryset(self) -> None:
        qs = QuerySet(self.Item)
        result = qs.select_for_update()
        assert isinstance(result, QuerySet)

    def test_sets_for_update_flag(self) -> None:
        qs = QuerySet(self.Item).select_for_update()
        assert qs._for_update is True

    def test_nowait_flag_propagated(self) -> None:
        qs = QuerySet(self.Item).select_for_update(nowait=True)
        assert qs._for_update_nowait is True
        assert qs._for_update_skip_locked is False

    def test_skip_locked_flag_propagated(self) -> None:
        qs = QuerySet(self.Item).select_for_update(skip_locked=True)
        assert qs._for_update_skip_locked is True
        assert qs._for_update_nowait is False

    def test_clone_preserves_flags(self) -> None:
        qs = QuerySet(self.Item).select_for_update(nowait=True)
        cloned = qs._clone()
        assert cloned._for_update is True
        assert cloned._for_update_nowait is True


# ── Model.full_clean ──────────────────────────────────────────────────────────


class TestModelFullClean:
    class Event(Model):
        name = CharField(max_length=100)

        class Meta:
            table_name = "events_fc_test"

    @pytest.mark.asyncio
    async def test_full_clean_calls_validate_and_clean(self) -> None:
        event = self.Event(name="Launch")
        with (
            patch.object(event, "validate", new_callable=AsyncMock) as mock_validate,
            patch.object(event, "clean", new_callable=AsyncMock) as mock_clean,
            patch.object(event, "before_validate", new_callable=AsyncMock),
        ):
            await event.full_clean()
        mock_validate.assert_called_once()
        mock_clean.assert_called_once()

    @pytest.mark.asyncio
    async def test_full_clean_propagates_clean_error(self) -> None:
        class StrictEvent(Model):
            start = IntegerField(default=0)
            end = IntegerField(default=0)

            async def clean(self) -> None:
                if self.start >= self.end:
                    raise ValueError("start must be before end")

            class Meta:
                table_name = "strict_events_test"

        ev = StrictEvent(start=10, end=5)
        with pytest.raises(ValueError, match="start must be before end"):
            await ev.full_clean()


# ── Model.clean ───────────────────────────────────────────────────────────────


class TestModelClean:
    @pytest.mark.asyncio
    async def test_default_clean_is_noop(self) -> None:
        class SimpleModel(Model):
            name = CharField(max_length=50)

            class Meta:
                table_name = "simple_clean_test"

        obj = SimpleModel(name="test")
        await obj.clean()


# ── Model.get_deferred_fields ─────────────────────────────────────────────────


class TestModelGetDeferredFields:
    class Profile(Model):
        first_name = CharField(max_length=50)
        last_name = CharField(max_length=50)
        bio = CharField(max_length=500)

        class Meta:
            table_name = "profiles_deferred_test"

    def test_no_deferred_fields_when_all_loaded(self) -> None:
        p = self.Profile(first_name="Alice", last_name="Smith", bio="...")
        deferred = p.get_deferred_fields()
        assert "first_name" not in deferred
        assert "last_name" not in deferred

    def test_missing_fields_reported_as_deferred(self) -> None:
        p = object.__new__(self.Profile)
        object.__setattr__(p, "_previous_state", {})
        p.__dict__["first_name"] = "Alice"
        deferred = p.get_deferred_fields()
        assert "bio" in deferred


# ── Model.__str__ ─────────────────────────────────────────────────────────────


class TestModelStr:
    class Tag(Model):
        label = CharField(max_length=50)

        class Meta:
            table_name = "tags_str_test"

    def test_str_contains_class_name(self) -> None:
        t = self.Tag(label="python")
        assert "Tag" in str(t)

    def test_str_contains_pk(self) -> None:
        t = self.Tag(label="openviper")
        t.id = 42
        assert "42" in str(t)

    def test_str_pk_none_before_save(self) -> None:
        t = self.Tag(label="none-pk")
        assert "None" in str(t)


# ── AddConstraint migration operation ────────────────────────────────────────


class TestAddConstraint:
    def test_check_constraint_postgresql(self) -> None:
        _get_dialect.cache_clear()
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            op = AddConstraint(
                table_name="products",
                constraint_name="price_positive",
                constraint_type="CHECK",
                check="price > 0",
            )
            sql = op.forward_sql()
        assert len(sql) == 1
        assert "CHECK" in sql[0]
        assert "price > 0" in sql[0]

    def test_check_constraint_sqlite_returns_empty(self) -> None:
        with patch("openviper.db.migrations.executor._get_dialect", return_value="sqlite"):
            op = AddConstraint(
                table_name="products",
                constraint_name="price_positive",
                constraint_type="CHECK",
                check="price > 0",
            )
            assert op.forward_sql() == []

    def test_unique_constraint_creates_index(self) -> None:
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            op = AddConstraint(
                table_name="articles",
                constraint_name="uq_slug",
                constraint_type="UNIQUE",
                columns=["slug"],
            )
            sql = op.forward_sql()
        assert len(sql) == 1
        assert "CREATE UNIQUE INDEX" in sql[0]
        assert "slug" in sql[0]

    def test_unique_constraint_with_condition_postgresql(self) -> None:
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            op = AddConstraint(
                table_name="articles",
                constraint_name="uq_pub_slug",
                constraint_type="UNIQUE",
                columns=["slug"],
                condition="published = 1",
            )
            sql = op.forward_sql()
        assert "WHERE published = 1" in sql[0]

    def test_unique_constraint_condition_ignored_on_mysql(self) -> None:
        with patch("openviper.db.migrations.executor._get_dialect", return_value="mysql"):
            op = AddConstraint(
                table_name="articles",
                constraint_name="uq_slug",
                constraint_type="UNIQUE",
                columns=["slug"],
                condition="published = 1",
            )
            sql = op.forward_sql()
        assert "WHERE" not in sql[0]

    def test_backward_sql_unique_drops_index(self) -> None:
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            op = AddConstraint(
                table_name="articles",
                constraint_name="uq_slug",
                constraint_type="UNIQUE",
                columns=["slug"],
            )
            sql = op.backward_sql()
        assert "DROP INDEX" in sql[0]

    def test_backward_sql_check_postgresql_drops_constraint(self) -> None:
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            op = AddConstraint(
                table_name="products",
                constraint_name="price_positive",
                constraint_type="CHECK",
                check="price > 0",
            )
            sql = op.backward_sql()
        assert "DROP CONSTRAINT" in sql[0]

    def test_backward_sql_check_sqlite_returns_empty(self) -> None:
        with patch("openviper.db.migrations.executor._get_dialect", return_value="sqlite"):
            op = AddConstraint(
                table_name="products",
                constraint_name="price_positive",
                constraint_type="CHECK",
                check="price > 0",
            )
            assert op.backward_sql() == []

    def test_backward_sql_mysql_check_uses_drop_check(self) -> None:
        with patch("openviper.db.migrations.executor._get_dialect", return_value="mysql"):
            op = AddConstraint(
                table_name="products",
                constraint_name="price_positive",
                constraint_type="CHECK",
                check="price > 0",
            )
            sql = op.backward_sql()
        assert "DROP CHECK" in sql[0]

    def test_unknown_constraint_type_returns_empty(self) -> None:
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            op = AddConstraint(
                table_name="t",
                constraint_name="c",
                constraint_type="FOREIGN",
            )
            assert op.forward_sql() == []
            assert op.backward_sql() == []

    def test_mssql_unique_backward_uses_drop_index_on_table(self) -> None:
        with patch("openviper.db.migrations.executor._get_dialect", return_value="mssql"):
            op = AddConstraint(
                table_name="articles",
                constraint_name="uq_slug",
                constraint_type="UNIQUE",
                columns=["slug"],
            )
            sql = op.backward_sql()
        assert "DROP INDEX" in sql[0]
        assert "articles" in sql[0]


# ── RemoveConstraint migration operation ─────────────────────────────────────


class TestRemoveConstraint:
    def test_forward_unique_drops_index_postgresql(self) -> None:
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            op = RemoveConstraint(
                table_name="articles",
                constraint_name="uq_slug",
                constraint_type="UNIQUE",
            )
            sql = op.forward_sql()
        assert "DROP INDEX" in sql[0]

    def test_forward_check_postgresql(self) -> None:
        with patch("openviper.db.migrations.executor._get_dialect", return_value="postgresql"):
            op = RemoveConstraint(
                table_name="products",
                constraint_name="price_positive",
                constraint_type="CHECK",
            )
            sql = op.forward_sql()
        assert "DROP CONSTRAINT" in sql[0]

    def test_forward_check_sqlite_returns_empty(self) -> None:
        with patch("openviper.db.migrations.executor._get_dialect", return_value="sqlite"):
            op = RemoveConstraint(
                table_name="products",
                constraint_name="price_positive",
                constraint_type="CHECK",
            )
            assert op.forward_sql() == []

    def test_backward_returns_empty(self) -> None:
        op = RemoveConstraint(
            table_name="articles",
            constraint_name="uq_slug",
        )
        assert op.backward_sql() == []


# ── db/__init__.py exports ────────────────────────────────────────────────────


class TestDbPackageExports:
    def test_new_field_types_importable(self) -> None:
        import openviper.db as db

        assert hasattr(db, "SmallIntegerField")
        assert hasattr(db, "BigAutoField")
        assert hasattr(db, "NullBooleanField")
        assert hasattr(db, "DurationField")
        assert hasattr(db, "GenericIPAddressField")

    def test_constraint_classes_importable(self) -> None:
        import openviper.db as db

        assert hasattr(db, "Constraint")
        assert hasattr(db, "CheckConstraint")
        assert hasattr(db, "UniqueConstraint")

    def test_index_importable(self) -> None:
        import openviper.db as db

        assert hasattr(db, "Index")
