import openviper.tasks.admin as tasks_admin_mod


def test_task_result_admin_defined():
    """TaskResultAdmin class is defined in the tasks admin module."""
    assert hasattr(tasks_admin_mod, "TaskResultAdmin")
