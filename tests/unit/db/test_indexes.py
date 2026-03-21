import tempfile
from pathlib import Path

import pytest

from openviper.db.fields import CharField, IntegerField
from openviper.db.migrations.executor import CreateIndex, RemoveIndex
from openviper.db.migrations.writer import (
    _diff_states,
    model_state_snapshot,
    write_initial_migration,
)
from openviper.db.models import Index, Model


class TestIndexSupport:
    def test_model_meta_parsing(self):
        class IndexModel(Model):
            email = CharField()
            username = CharField()
            age = IntegerField()

            class Meta:
                table_name = "index_test"
                indexes = [
                    Index(fields=["email"], name="idx_email"),
                    Index(fields=["username", "age"]),
                ]
                unique_together = [("username", "email")]

        assert len(IndexModel._meta_indexes) == 2
        assert IndexModel._meta_indexes[0].name == "idx_email"
        assert IndexModel._meta_indexes[0].fields == ["email"]
        assert IndexModel._meta_indexes[1].name is None
        assert IndexModel._meta_indexes[1].fields == ["username", "age"]

        assert len(IndexModel._meta_unique_together) == 1
        assert IndexModel._meta_unique_together[0] == ["username", "email"]

    def test_invalid_field_in_index_raises(self):
        with pytest.raises(Exception, match="Index field 'nonexistent' not found"):

            class InvalidIndexModel(Model):
                name = CharField()

                class Meta:
                    indexes = [Index(fields=["nonexistent"])]

    def test_snapshot_includes_indexes(self):
        class SnapModel(Model):
            name = CharField()

            class Meta:
                table_name = "snap_idx"
                indexes = [Index(fields=["name"], name="idx_name")]
                unique_together = [("name",)]

        state = model_state_snapshot([SnapModel])
        assert "snap_idx" in state
        data = state["snap_idx"]
        assert len(data["indexes"]) == 1
        assert data["indexes"][0]["name"] == "idx_name"
        assert data["indexes"][0]["fields"] == ["name"]
        assert data["unique_together"] == [["name"]]

    def test_diff_states_adds_index(self):
        existing = {
            "t": {
                "columns": [{"name": "id", "type": "INTEGER"}],
                "indexes": [],
                "unique_together": [],
            }
        }
        current = {
            "t": {
                "columns": [{"name": "id", "type": "INTEGER"}],
                "indexes": [{"name": "idx_id", "fields": ["id"]}],
                "unique_together": [["id"]],
            }
        }
        ops = _diff_states(current, existing)
        # Should have 2 CreateIndex operations
        create_indexes = [op for op in ops if isinstance(op, CreateIndex)]
        assert len(create_indexes) == 2
        # One for explicit index, one for unique_together
        names = {op.index_name for op in create_indexes}
        assert "idx_id" in names
        assert "uniq_t_id" in names

    def test_diff_states_removes_index(self):
        existing = {
            "t": {
                "columns": [{"name": "id", "type": "INTEGER"}],
                "indexes": [{"name": "idx_id", "fields": ["id"]}],
                "unique_together": [["id"]],
            }
        }
        current = {
            "t": {
                "columns": [{"name": "id", "type": "INTEGER"}],
                "indexes": [],
                "unique_together": [],
            }
        }
        ops = _diff_states(current, existing)
        remove_indexes = [op for op in ops if isinstance(op, RemoveIndex)]
        assert len(remove_indexes) == 2
        names = {op.index_name for op in remove_indexes}
        assert "idx_id" in names
        assert "uniq_t_id" in names

    def test_write_initial_migration_with_indexes(self):
        class MigModel(Model):
            name = CharField()

            class Meta:
                table_name = "mig_idx"
                indexes = [Index(fields=["name"], name="idx_name")]
                unique_together = [("name",)]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_initial_migration("testapp", [MigModel], tmpdir)
            content = Path(path).read_text()
            assert "migrations.CreateIndex" in content
            assert "idx_name" in content
            assert "uniq_mig_idx_name" in content
            assert "unique=True" in content

    def test_verbose_names_and_ordering(self):
        class VerboseModel(Model):
            title = CharField()
            created_at = IntegerField()

            class Meta:
                verbose_name = "Custom Post"
                verbose_name_plural = "Posts Collection"
                ordering = ["-created_at"]

        assert VerboseModel._verbose_name == "Custom Post"
        assert VerboseModel._verbose_name_plural == "Posts Collection"
        assert VerboseModel._ordering == ["-created_at"]

        # Check QuerySet default ordering
        qs = VerboseModel.objects.all()
        assert qs._order == ["-created_at"]

        # Check ModelAdmin defaults
        from openviper.admin.options import ModelAdmin

        admin = ModelAdmin(VerboseModel)
        assert admin.get_ordering() == ["-created_at"]
        info = admin.get_model_info()
        assert info["verbose_name"] == "Custom Post"
        assert info["verbose_name_plural"] == "Posts Collection"

    def test_default_verbose_names(self):
        class DefaultVerboseModel(Model):
            name = CharField()

        assert DefaultVerboseModel._verbose_name == "DefaultVerboseModel"
        assert DefaultVerboseModel._verbose_name_plural == "DefaultVerboseModels"

    def test_invalid_ordering_field_raises(self):
        with pytest.raises(Exception, match="Ordering field 'nonexistent' not found"):

            class InvalidOrderModel(Model):
                name = CharField()

                class Meta:
                    ordering = ["nonexistent"]
