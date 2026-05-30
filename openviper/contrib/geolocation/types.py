"""Geolocation contrib type aliases and protocols."""

from collections.abc import Callable
from typing import Protocol


class PointOwner(Protocol):
    """Object that can hold descriptor-backed point values."""

    __dict__: dict[str, object]


class ShapelyPoint(Protocol):
    """Structural view of the Shapely point API used here."""

    x: float
    y: float


class ShapelyGeometryModule(Protocol):
    """Structural view of the Shapely geometry module used here."""

    Point: Callable[[float, float], ShapelyPoint]


class ShapelyWKBModule(Protocol):
    """Structural view of the Shapely WKB module used here."""

    def loads(self, value: str, **kwargs: object) -> ShapelyPoint: ...


type GeoJSONValue = str | list[float]
type GeoJSONObject = dict[str, GeoJSONValue]
type PointInput = GeoJSONObject | str | list[float] | tuple[float, float] | None
type DatabasePointValue = str | bytes | None
type GeoJSONOutput = dict[str, str | list[float]]
