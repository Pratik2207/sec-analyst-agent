from ui.sse import iter_events


def lines(text: str) -> list[str]:
    return text.split("\n")


def test_step_and_final_events_in_order():
    text = ('data: {"type": "step", "data": {"name": "route", "detail": {}}}\n\n'
            'data: {"type": "final", "data": {"answer": "x"}}\n\n')
    events = list(iter_events(lines(text)))
    assert [e["type"] for e in events] == ["step", "final"]
    assert events[1]["data"]["answer"] == "x"


def test_multi_line_data_is_joined():
    text = 'data: {"type": "step",\ndata:  "data": {"name": "plan"}}\n\n'
    assert list(iter_events(lines(text))) == [{"type": "step", "data": {"name": "plan"}}]


def test_comments_keepalives_and_other_fields_ignored():
    text = (": keep-alive\n\n: ping\nevent: message\nid: 3\nretry: 1000\n"
            'data: {"type": "step", "data": {"name": "grade"}}\n\n')
    assert [e["data"]["name"] for e in iter_events(lines(text))] == ["grade"]


def test_broken_json_is_skipped_and_parsing_continues():
    text = ('data: {"type": "step", "data": \n\n'
            'data: [1, 2]\n\n'
            'data: {"type": "final", "data": {"answer": "ok"}}\n\n')
    assert [e["type"] for e in iter_events(lines(text))] == ["final"]


def test_error_event():
    text = 'data: {"type": "error", "data": {"message": "boom"}}\n\n'
    assert list(iter_events(lines(text))) == [{"type": "error", "data": {"message": "boom"}}]


def test_crlf_no_space_after_colon_and_unterminated_last_event():
    raw = ['data:{"type":"step","data":{"name":"a"}}\r\n', "\r\n",
           'data: {"type": "final", "data": {}}']
    assert [e["type"] for e in iter_events(raw)] == ["step", "final"]


def test_empty_stream():
    assert list(iter_events([])) == []
