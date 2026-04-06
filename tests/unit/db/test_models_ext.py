from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.db import fields
from openviper.db.models import (
    F,
    Index,
    Model,
    ModelMeta,
    Page,
    QuerySet,
    TraversalLookup,
)
from openviper.exceptions import FieldError

# --- Metadata Parsing Tests ---


def test_model_meta_validation():
    with patch("openviper.db.executor.get_table"):
        # Test Index field validation
        with pytest.raises(FieldError, match="Index field 'missing' not found"):

            class BadIndex(Model):
                name = fields.CharField(max_length=100)

                class Meta:
                    indexes = [Index(fields=["missing"])]

        # Test unique_together field validation
        with pytest.raises(FieldError, match="unique_together field 'missing' not found"):

            class BadUnique(Model):
                name = fields.CharField(max_length=100)

                class Meta:
                    unique_together = ["missing"]

        # Test ordering field validation
        with pytest.raises(FieldError, match="Ordering field 'missing' not found"):

            class BadOrdering(Model):
                name = fields.CharField(max_length=100)

                class Meta:
                    ordering = ["missing"]


def test_extract_app_name_edge_cases():
    assert ModelMeta._extract_app_name("", "Test") == "default"
    assert ModelMeta._extract_app_name("testmod", "Test") == "default"
    assert ModelMeta._extract_app_name("project.apps.blog.models", "Post") == "blog"
    assert ModelMeta._extract_app_name("openviper.auth.models", "User") == "auth"


# --- F Expression Tests ---


def test_f_expression_arithmetic():
    f = F("views")
    assert repr(f - 10) == "_FExpr(F('views') - 10)"
    assert repr(100 - f) == "_FExpr(100 - F('views'))"
    assert repr(f * 2) == "_FExpr(F('views') * 2)"
    assert repr(3 * f) == "_FExpr(3 * F('views'))"
    assert repr(f / 2) == "_FExpr(F('views') / 2)"


# --- QuerySet Pagination Tests ---


@pytest.mark.asyncio
async def test_queryset_pagination():
    with patch("openviper.db.executor.get_table"):

        class PagingModel(Model):
            name = fields.CharField(max_length=100)

    qs = PagingModel.objects.all()
    # Test error
    with pytest.raises(ValueError, match="Page number must be >= 1"):
        await qs.paginate(0)

    # Test success path with mocking
    with patch.object(QuerySet, "count", new_callable=AsyncMock) as mock_count:
        mock_count.return_value = 50
        with patch.object(QuerySet, "all", new_callable=AsyncMock) as mock_all:
            mock_all.return_value = []
            page = await qs.paginate(2, 20)
            assert isinstance(page, Page)
            assert page.number == 2
            assert page.num_pages == 3
            assert page.has_next is True
            assert page.has_previous is True


# --- Permission & Bulk Operations Tests ---


@pytest.mark.asyncio
async def test_permission_overrides():
    with patch("openviper.db.executor.get_table"):

        class PermModel(Model):
            name = fields.CharField(max_length=100)

    with patch("openviper.db.models.check_permission_for_model") as mock_check:
        with patch("openviper.db.models.execute_count", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = 10
            await PermModel.objects.filter(ignore_permissions=True).count()
            mock_check.assert_called_with(PermModel, "read", ignore_permissions=True)


@pytest.mark.asyncio
async def test_bulk_operations():
    with patch("openviper.db.executor.get_table"):

        class BulkModel(Model):
            name = fields.CharField(max_length=100)

    objs = [BulkModel(name="A"), BulkModel(name="B")]
    with patch("openviper.db.models.check_permission_for_model"):
        with patch("sqlalchemy.insert"):
            with patch("openviper.db.models._begin"):
                await BulkModel.objects.bulk_create(objs, ignore_permissions=True)

        with patch("openviper.db.models.execute_bulk_update", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = 2
            await BulkModel.objects.bulk_update(objs, fields=["name"])


# --- Traversal Lookup Tests ---


def test_traversal_errors():
    with patch("openviper.db.executor.get_table"):

        class TargetModel(Model):
            name = fields.CharField(max_length=100)

        class SourceModel(Model):
            target = fields.ForeignKey(TargetModel)
            other = fields.CharField(max_length=100)

    with pytest.raises(FieldError, match=r"Traversal depth 6 exceeds maximum of 5"):
        TraversalLookup("a__b__c__d__e__f__g", SourceModel)

    with pytest.raises(FieldError, match=r"Cannot traverse through non-relationship field 'other'"):
        TraversalLookup("other__name", SourceModel)

    with pytest.raises(FieldError, match=r"Field 'missing' not found on TargetModel"):
        TraversalLookup("target__missing", SourceModel)


# --- Iterator & Batching Tests ---


@pytest.mark.asyncio
async def test_iterators():
    with patch("openviper.db.executor.get_table"), patch("openviper.db.executor.get_engine"):

        class IterModel(Model):
            name = fields.CharField(max_length=100)

    results = [{"id": i, "name": f"N{i}"} for i in range(10)]

    with patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock):
        with patch("openviper.db.models.execute_select", new_callable=AsyncMock) as mock_select:
            with patch("openviper.db.executor.get_engine"):
                # iterator test
                mock_select.side_effect = [results[:5], results[5:], []]
                count = 0
                async for _obj in IterModel.objects.filter().iterator(chunk_size=5):
                    count += 1
                assert count == 10

                # batch test
                mock_select.side_effect = [results[:3], results[3:6], results[6:9], results[9:], []]
                batch_count = 0
                async for _b in IterModel.objects.filter().batch(size=3):
                    batch_count += 1
                assert batch_count == 4

                # id_batch test (also calls execute_select)
                mock_select.side_effect = [results[:4], results[4:8], results[8:10], []]
                id_batch_count = 0
                async for _b in IterModel.objects.filter().id_batch(size=4):
                    id_batch_count += 1
                assert id_batch_count == 3


@pytest.mark.asyncio
async def test_select_related_hydration():
    with patch("openviper.db.executor.get_table"):

        class Author(Model):
            name = fields.CharField(max_length=100)

        class Book(Model):
            title = fields.CharField(max_length=100)
            author = fields.ForeignKey(Author)

    # Mock DB row with prefixed keys for select_related
    row = {
        "id": 1,
        "title": "Viper Guide",
        "author_id": 10,
        "author__id": 10,
        "author__name": "Anthony",
    }

    with patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock):
        with patch("openviper.db.models.execute_select", new_callable=AsyncMock) as mock_select:
            mock_select.return_value = [row]

            qs = Book.objects.select_related("author")
            books = await qs.all()

            assert len(books) == 1
            book = books[0]
            assert book.title == "Viper Guide"
            assert isinstance(book.author, Author)
            assert book.author.id == 10
            assert book.author.name == "Anthony"


# --- New Extended Tests for Full Branch Coverage ---


def test_model_meta_parsing_extended():
    with patch("openviper.db.executor.get_table"), patch("openviper.db.executor.get_engine"):
        # Test table_name override
        class CustomTable(Model):
            name = fields.CharField(max_length=10)

            class Meta:
                table_name = "overridden_table"

        assert CustomTable._table_name == "overridden_table"

        # Test abstract model
        class AbstractModel(Model):
            class Meta:
                abstract = True

        assert AbstractModel._is_abstract is True

        # Test auto-generated table name (camel to snake)
        class MyTestModel(Model):
            name = fields.CharField(max_length=10)

        # MyTestModel -> db_my_test_model (tests are in 'db' app)
        assert MyTestModel._table_name == "db_my_test_model"

        # Test unique_together: single list
        class UniqueSingle(Model):
            f1 = fields.CharField(max_length=10)
            f2 = fields.CharField(max_length=10)

            class Meta:
                unique_together = ("f1", "f2")

        assert UniqueSingle._meta_unique_together == [["f1", "f2"]]

        # Test unique_together: list of lists
        class UniqueMulti(Model):
            f1 = fields.CharField(max_length=10)
            f2 = fields.CharField(max_length=10)

            class Meta:
                unique_together = [["f1"], ["f2"]]

        assert UniqueMulti._meta_unique_together == [["f1"], ["f2"]]

        # Test ordering: string
        class OrderString(Model):
            f1 = fields.CharField(max_length=10)

            class Meta:
                ordering = "f1"

        assert OrderString._ordering == ["f1"]

        # Test ordering: list
        class OrderList(Model):
            f1 = fields.CharField(max_length=10)

            class Meta:
                ordering = ["-f1"]

        assert OrderList._ordering == ["-f1"]


def test_page_methods():
    items = [MagicMock(spec=Model)]
    page = Page(items, number=2, page_size=10, total_count=25)
    assert page.has_next is True
    assert page.has_previous is True
    assert page.next_page_number == 3
    assert page.previous_page_number == 1
    assert page.num_pages == 3
    assert "Page 2 of 3" in repr(page)


@pytest.mark.asyncio
async def test_manager_first_last():
    with patch("openviper.db.executor.get_table"):

        class ManagerModel(Model):
            name = fields.CharField(max_length=100)

    with patch("openviper.db.models._check_perm_cached", new_callable=AsyncMock):
        with patch("openviper.db.models.execute_select", new_callable=AsyncMock) as mock_select:
            # Test first()
            mock_select.return_value = [{"id": 1, "name": "First"}]
            obj = await ManagerModel.objects.first()
            assert obj.id == 1

            # Test last() with ordering
            mock_select.return_value = [{"id": 99, "name": "Last"}]
            obj = await ManagerModel.objects.order_by("name").last()
            assert obj.id == 99

            # Test last() without ordering
            obj = await ManagerModel.objects.last()
            assert obj.id == 99


@pytest.mark.asyncio
async def test_unique_together_validate_blocks_duplicate() -> None:
    with patch("openviper.db.executor.get_table"):

        class Contact(Model):
            class Meta:
                table_name = "test_contact_utv"
                unique_together = ("username", "phone")

            username = fields.CharField(max_length=100)
            phone = fields.CharField(max_length=50)

    contact = Contact(username="alice", phone="123")

    mock_qs = MagicMock()
    mock_qs.exists = AsyncMock(return_value=True)

    with patch.object(Contact.objects, "filter", return_value=mock_qs):
        with pytest.raises(ValueError, match="Duplicate entry"):
            await contact.validate()


@pytest.mark.asyncio
async def test_unique_together_validate_allows_non_duplicate() -> None:
    with patch("openviper.db.executor.get_table"):

        class Contact2(Model):
            class Meta:
                table_name = "test_contact_utv2"
                unique_together = ("username", "phone")

            username = fields.CharField(max_length=100)
            phone = fields.CharField(max_length=50)

    contact = Contact2(username="bob", phone="456")

    mock_qs = MagicMock()
    mock_qs.exists = AsyncMock(return_value=False)

    with patch.object(Contact2.objects, "filter", return_value=mock_qs):
        await contact.validate()


@pytest.mark.asyncio
async def test_unique_together_validate_skips_null_fields() -> None:
    with patch("openviper.db.executor.get_table"):

        class Contact3(Model):
            class Meta:
                table_name = "test_contact_utv3"
                unique_together = ("username", "phone")

            username = fields.CharField(max_length=100)
            phone = fields.CharField(max_length=50, null=True)

    contact = Contact3(username="carol", phone=None)

    mock_qs = MagicMock()
    mock_qs.exists = AsyncMock(return_value=True)

    with patch.object(Contact3.objects, "filter", return_value=mock_qs):
        await contact.validate()
        mock_qs.exists.assert_not_called()
