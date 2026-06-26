"""Database migrations package.

Retains the Operation classes, ``diff_states``, and
``model_state_snapshot`` which are reused by the schema sync system.
"""

from openviper.db.migrations.executor import (
    AddColumn,
    AddConstraint,
    AlterColumn,
    CreateIndex,
    CreateTable,
    DropTable,
    Operation,
    RemoveColumn,
    RemoveConstraint,
    RenameColumn,
    RestoreColumn,
    RunSQL,
    column_exists,
    should_skip_backward,
    should_skip_forward,
)
from openviper.db.migrations.writer import (
    diff_states,
    model_state_snapshot,
    normalize_state,
)

__all__ = [
    "Operation",
    "CreateTable",
    "DropTable",
    "AddColumn",
    "AlterColumn",
    "RemoveColumn",
    "RenameColumn",
    "RestoreColumn",
    "CreateIndex",
    "AddConstraint",
    "RemoveConstraint",
    "RunSQL",
    "column_exists",
    "should_skip_backward",
    "should_skip_forward",
    "model_state_snapshot",
    "diff_states",
    "normalize_state",
]
