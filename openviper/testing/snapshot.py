"""Optional snapshot assertion helpers."""

import json
from pathlib import Path


class Snapshot:
    """Filesystem-backed snapshot helper."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def assert_matches(self, name: str, value: object) -> None:
        assert_matches_snapshot(value, self.root / name)


def assert_matches_snapshot(value: object, path: Path) -> None:
    serialized = serialize_snapshot(value)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")
        return
    expected = path.read_text(encoding="utf-8")
    assert serialized == expected, f"Snapshot {path} did not match."


def serialize_snapshot(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"
