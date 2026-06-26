"""Task subsystem configuration validation and defaults."""

from __future__ import annotations

import typing as t

from openviper.conf.task_defaults import DEFAULT_TASKS
from openviper.tasks.exceptions import OpenViperTasksConfigurationError


def validate_tasks_config(cfg: dict[str, t.Any]) -> None:
    """Fail-fast structural validation of ``settings.TASKS``.

    Raises :class:`OpenViperTasksConfigurationError` with a list of
    human-readable violations when the configuration is invalid.
    """
    errors: list[str] = []

    if not isinstance(cfg, dict):
        errors.append("TASKS must be a dict")
        raise OpenViperTasksConfigurationError(errors)

    enabled = cfg.get("enabled", 1)
    if enabled not in (0, 1):
        errors.append("TASKS['enabled'] must be 0 or 1")

    broker = cfg.get("broker", "redis")
    if broker not in ("redis", "rabbitmq", "sqs", "stub"):
        errors.append("TASKS['broker'] must be 'redis', 'rabbitmq', 'sqs', or 'stub'")

    if enabled == 1 and not cfg.get("broker_url") and broker != "stub":
        errors.append("TASKS['broker_url'] is required when enabled == 1")

    log_cfg = cfg.get("logging")
    if isinstance(log_cfg, dict):
        file_cfg = log_cfg.get("file")
        if isinstance(file_cfg, dict):
            log_format = file_cfg.get("log_format", "json")
            if log_format not in ("json", "text"):
                errors.append("TASKS['logging']['file']['log_format'] must be 'json' or 'text'")
            max_size = file_cfg.get("max_size", 10)
            if not isinstance(max_size, (int, float)) or max_size <= 0:
                errors.append("TASKS['logging']['file']['max_size'] must be a positive number")
        elif file_cfg not in (0, 1, None):
            errors.append("TASKS['logging']['file'] must be 0, 1, None, or a dict")
        db_cfg = log_cfg.get("database")
        if isinstance(db_cfg, dict):
            for key in ("task", "periodic"):
                val = db_cfg.get(key, 0)
                if val not in (0, 1):
                    errors.append(f"TASKS['logging']['database']['{key}'] must be 0 or 1")
        elif db_cfg not in (0, 1, None):
            errors.append("TASKS['logging']['database'] must be 0, 1, None, or a dict")

    if errors:
        raise OpenViperTasksConfigurationError(errors)


def resolve_tasks_config(cfg: dict[str, t.Any] | None) -> dict[str, t.Any]:
    """Merge *cfg* over the default TASKS dictionary and validate."""
    merged = {**DEFAULT_TASKS}
    if cfg:
        merged.update(cfg)
        if isinstance(cfg.get("logging"), dict):
            merged_logging = {**DEFAULT_TASKS["logging"], **cfg["logging"]}
            for subkey in ("file", "database"):
                user_sub = cfg["logging"].get(subkey)
                if isinstance(user_sub, dict) or subkey in cfg["logging"]:
                    merged_logging[subkey] = user_sub
            merged["logging"] = merged_logging
    validate_tasks_config(merged)
    return merged
