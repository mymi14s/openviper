"""Event recording helpers for tests."""

import dataclasses


@dataclasses.dataclass(frozen=True, slots=True)
class RecordedEvent:
    """Captured framework event."""

    name: str
    payload: dict[str, object]


class EventRecorder:
    """Collect event names and payloads during a test."""

    def __init__(self) -> None:
        self.events: list[RecordedEvent] = []

    def record(self, name: str, **payload: object) -> None:
        self.events.append(RecordedEvent(name=name, payload=payload))

    def clear(self) -> None:
        self.events.clear()


def assert_event_emitted(recorder: EventRecorder, name: str) -> None:
    found = any(event.name == name for event in recorder.events)
    assert found, f"Expected event {name!r} to be emitted."


def assert_event_count(recorder: EventRecorder, name: str, expected: int) -> None:
    actual = sum(1 for event in recorder.events if event.name == name)
    assert actual == expected, f"Expected {expected} event(s) named {name!r}, got {actual}."


def assert_event_payload(recorder: EventRecorder, name: str, **payload: object) -> None:
    for event in recorder.events:
        matches_name = event.name == name
        matches_payload = all(event.payload.get(key) == value for key, value in payload.items())
        if matches_name and matches_payload:
            return
    raise AssertionError(f"Expected event {name!r} with payload {payload!r}.")
