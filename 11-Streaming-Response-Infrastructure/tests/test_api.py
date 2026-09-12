from fastapi.testclient import TestClient

from stream.api import app


def _parse_event(block: bytes) -> tuple[int, str, str] | None:
    """A dispatched SSE event has both `id:` and `event:`; retry/comment-only
    blocks don't, and are ignored here the same way a real client would."""
    kv: dict[str, str] = {}
    data_lines: list[str] = []
    for line in block.decode("utf-8").split("\n"):
        if line.startswith("event: "):
            kv["type"] = line.removeprefix("event: ")
        elif line.startswith("id: "):
            kv["id"] = line.removeprefix("id: ")
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").removeprefix(" "))
    if "id" not in kv or "type" not in kv:
        return None
    return int(kv["id"]), kv["type"], "\n".join(data_lines)


def _events(raw: bytes) -> list[tuple[int, str, str]]:
    return [e for b in raw.split(b"\n\n") if (e := _parse_event(b)) is not None]


def test_reconnect_after_partial_read_has_no_duplicates_or_gaps() -> None:
    with TestClient(app) as client:
        start = client.post("/v1/stream/start")
        assert start.status_code == 200
        sse_url = start.json()["sse_url"]

        first_events: list[tuple[int, str, str]] = []
        buf = b""
        with client.stream("GET", sse_url) as resp:
            assert resp.status_code == 200
            for chunk in resp.iter_bytes():
                buf += chunk
                while b"\n\n" in buf and len(first_events) < 3:
                    block, buf = buf.split(b"\n\n", 1)
                    parsed = _parse_event(block)
                    if parsed is not None:
                        first_events.append(parsed)
                if len(first_events) == 3:
                    break  # simulates the client dropping mid-stream

        assert len(first_events) == 3
        last_id = first_events[-1][0]

        resume = client.get(sse_url, headers={"Last-Event-ID": str(last_id)})
        assert resume.status_code == 200
        second_events = _events(resume.content)

    all_ids = [e[0] for e in first_events] + [e[0] for e in second_events]
    assert len(all_ids) == len(set(all_ids)), "duplicate event ids across reconnect"
    assert all_ids == list(range(all_ids[0], all_ids[-1] + 1)), "gap in event ids across reconnect"
    assert second_events[-1][1] == "done"


def test_query_param_last_event_id_resumes_like_the_header() -> None:
    with TestClient(app) as client:
        start = client.post("/v1/stream/start")
        sse_url = start.json()["sse_url"]

        full = client.get(sse_url)  # run to completion
        events = _events(full.content)
        assert events[-1][1] == "done"
        midpoint_id = events[1][0]

        resumed = client.get(sse_url, params={"last_event_id": midpoint_id})
        resumed_events = _events(resumed.content)

    assert [e[0] for e in resumed_events] == [e[0] for e in events if e[0] > midpoint_id]


def test_unknown_session_id_returns_410_with_error_event() -> None:
    with TestClient(app) as client:
        resp = client.get("/v1/stream/does-not-exist")

    assert resp.status_code == 410
    events = _events(resp.content)
    assert len(events) == 1
    _id, event_type, data = events[0]
    assert event_type == "error"
    assert data == "session_expired"
