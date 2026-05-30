"""Shared configuration type aliases."""

from datetime import timedelta

type ConfigValue = (
    str
    | int
    | float
    | bool
    | None
    | timedelta
    | tuple[str, ...]
    | list[str]
    | dict[str, ConfigValue]
)
type ConfigMap = dict[str, ConfigValue]
type EnvValue = bool | int | float | str | tuple[str, ...] | timedelta
