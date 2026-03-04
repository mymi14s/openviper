"""Coverage for openviper/tasks/admin.py."""

import openviper.tasks.admin  # noqa: F401 — triggers @register(TaskResult)


def test_task_result_admin_defined():
    """TaskResultAdmin class is defined in the tasks admin module."""
    import openviper.tasks.admin as tasks_admin_mod

    assert hasattr(tasks_admin_mod, "TaskResultAdmin")
