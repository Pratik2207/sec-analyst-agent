"""Parse the Server-Sent Events of POST /ask/stream (wire format in src/api/stream.py)."""

import json
from collections.abc import Iterable, Iterator


def iter_events(lines: Iterable[str]) -> Iterator[dict]:
    """Yield each event's JSON payload. An event is one or more `data:` lines ended by a
    blank line (multi-line data is joined with newlines). Comment lines (`:` keep-alives) and
    other fields (event:, id:, retry:) are ignored; an event whose data is not a JSON object
    is skipped. A last event without the closing blank line is still yielded."""
    buf: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line == "":
            yield from _decode(buf)
            buf = []
        elif line.startswith("data:"):
            value = line[5:]
            buf.append(value[1:] if value.startswith(" ") else value)
    yield from _decode(buf)


def _decode(buf: list[str]) -> Iterator[dict]:
    if not buf:
        return
    try:
        event = json.loads("\n".join(buf))
    except json.JSONDecodeError:
        return
    if isinstance(event, dict):
        yield event
