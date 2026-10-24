from app.tinyfish.sse import SSEDecoder, parse_lines


def test_basic_stream():
    lines = ['data: {"type":"STARTED","run_id":"r1"}', "", ": comment", 'data: {"type":"PROGRESS","purpose":"x"}', ""]
    evts = list(parse_lines(lines))
    assert [e["type"] for e in evts] == ["STARTED", "PROGRESS"]


def test_multiline_data_is_joined():
    lines = ['data: {"type":"PROGRESS",', 'data: "purpose":"split"}', ""]
    assert list(parse_lines(lines)) == [{"type": "PROGRESS", "purpose": "split"}]


def test_event_field_supplies_type():
    assert list(parse_lines(["event: HEARTBEAT", "data: {}", ""])) == [{"type": "HEARTBEAT"}]


def test_no_blank_separators():
    lines = ['data: {"type":"A"}', 'data: {"type":"B"}']
    assert [e["type"] for e in parse_lines(lines)] == ["A", "B"]


def test_garbage_is_skipped():
    assert list(parse_lines(["data: not json", "", 'data: {"type":"COMPLETE"}', ""])) == [{"type": "COMPLETE"}]


def test_unknown_types_pass_through():
    d = SSEDecoder()
    assert d.feed('data: {"type":"NEW_THING","x":1}') == []
    assert d.feed("") == [{"type": "NEW_THING", "x": 1}]
