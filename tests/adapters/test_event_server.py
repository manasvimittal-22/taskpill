import http.client
import json
import threading

import pytest

from taskpill.adapters.event_server import MAX_BODY, TOKEN_HEADER, EventServer
from taskpill.domain.events import EventType

TOKEN = "test-token-0123456789abcdef"  # publish-scan: ok (a fake test token)


@pytest.fixture
def received():
    return []


@pytest.fixture
def server(received):
    srv = EventServer(sink=received.append, token=TOKEN, keepalive_seconds=0.2)
    srv.start()
    yield srv
    srv.stop()


def request(server, method, path, body=None, headers=None, token=TOKEN, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    hdrs = {"Host": host or f"127.0.0.1:{server.port}"}
    if token is not None:
        hdrs[TOKEN_HEADER] = token
    hdrs.update(headers or {})
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    conn.putrequest(method, path, skip_host=True)
    for k, v in hdrs.items():
        conn.putheader(k, v)
    if data is not None:
        conn.putheader("Content-Length", str(len(data)))
    conn.endheaders(data)
    response = conn.getresponse()
    payload = response.read()
    conn.close()
    return response.status, payload


EVENT = {"session_id": "a", "hook_event_name": "Stop"}


def test_accepts_a_valid_event(server, received):
    status, _ = request(server, "POST", "/event", EVENT)
    assert status == 204
    assert len(received) == 1
    assert received[0].type is EventType.STOP


def test_listens_on_localhost_only(server):
    assert server._httpd.server_address[0] == "127.0.0.1"


@pytest.mark.parametrize("token", [None, "", "wrong-token-0123456789abcdef", TOKEN + "x"])
def test_rejects_missing_or_wrong_token(server, received, token):
    status, _ = request(server, "POST", "/event", EVENT, token=token)
    assert status == 401
    assert received == []


def test_rejects_browser_requests(server, received):
    status, _ = request(server, "POST", "/event", EVENT, headers={"Origin": "https://evil.example"})
    assert status == 403
    assert received == []


def test_rejects_foreign_host_header(server, received):
    status, _ = request(server, "POST", "/event", EVENT, host="evil.example:80")
    assert status == 403
    assert received == []


def test_localhost_host_header_is_fine(server):
    status, _ = request(server, "POST", "/event", EVENT, host=f"localhost:{server.port}")
    assert status == 204


@pytest.mark.parametrize(
    "body",
    [b"not json", b"[]", json.dumps({"session_id": "a"}).encode(), b"{\"hook_event_name\": 1}"],
)
def test_rejects_bad_events(server, received, body):
    status, _ = request(server, "POST", "/event", body)
    assert status == 400
    assert received == []


def test_rejects_huge_bodies_without_reading_them(server, received):
    # Only the header is sent: the server must refuse before reading any body.
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.putrequest("POST", "/event", skip_host=True)
    conn.putheader("Host", f"127.0.0.1:{server.port}")
    conn.putheader(TOKEN_HEADER, TOKEN)
    conn.putheader("Content-Length", str(MAX_BODY + 1))
    conn.endheaders()
    assert conn.getresponse().status == 413
    conn.close()
    assert received == []


def test_requires_content_length(server):
    status, _ = request(server, "POST", "/event", None)
    assert status == 411


def test_unknown_paths(server):
    assert request(server, "POST", "/nope", EVENT)[0] == 404
    assert request(server, "GET", "/nope")[0] == 404


def test_health(server):
    status, body = request(server, "GET", "/health")
    assert status == 200
    assert json.loads(body)["app"] == "taskpill"


def test_a_failing_sink_returns_500_and_the_server_keeps_working():
    calls = []

    def sink(event):
        calls.append(event)
        if len(calls) == 1:
            raise RuntimeError("bug")

    srv = EventServer(sink=sink, token=TOKEN)
    srv.start()
    try:
        assert request(srv, "POST", "/event", EVENT)[0] == 500
        assert request(srv, "POST", "/event", EVENT)[0] == 204
    finally:
        srv.stop()


def test_short_tokens_are_refused():
    with pytest.raises(ValueError):
        EventServer(sink=lambda e: None, token="short")


def test_stream_sends_current_snapshot_then_updates(server):
    server.publish({"sessions": [1]})
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request(
        "GET", "/stream", headers={TOKEN_HEADER: TOKEN, "Host": f"127.0.0.1:{server.port}"}
    )
    response = conn.getresponse()
    assert response.status == 200
    assert response.getheader("Content-Type") == "text/event-stream"

    def read_event():
        line = response.fp.readline()
        while line.startswith(b":") or line == b"\n":  # skip keepalives
            line = response.fp.readline()
        response.fp.readline()  # blank line after the event
        return json.loads(line.removeprefix(b"data: "))

    assert read_event() == {"sessions": [1]}
    threading.Timer(0.3, server.publish, args=({"sessions": [2]},)).start()
    assert read_event() == {"sessions": [2]}
    conn.close()


def test_stop_ends_open_streams(received):
    srv = EventServer(sink=received.append, token=TOKEN, keepalive_seconds=0.1)
    srv.start()
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("GET", "/stream", headers={TOKEN_HEADER: TOKEN, "Host": f"127.0.0.1:{srv.port}"})
    response = conn.getresponse()
    response.fp.readline()
    srv.stop()  # must not hang
    conn.close()


# ---- /click (the VS Code status bar) ---------------------------------------------------
@pytest.fixture
def clicks():
    return []


@pytest.fixture
def click_server(received, clicks):
    srv = EventServer(sink=received.append, token=TOKEN, on_click=clicks.append)
    srv.start()
    yield srv
    srv.stop()


def test_click_passes_the_session_id(click_server, clicks):
    status, _ = request(click_server, "POST", "/click", {"session_id": "abc"})
    assert status == 204
    assert clicks == ["abc"]


@pytest.mark.parametrize(
    "body",
    [
        b"nope",
        b"[]",
        b"{}",
        json.dumps({"session_id": 5}).encode(),
        json.dumps({"session_id": ""}).encode(),
        json.dumps({"session_id": "x" * 201}).encode(),
    ],
)
def test_click_rejects_bad_bodies(click_server, clicks, body):
    assert request(click_server, "POST", "/click", body)[0] == 400
    assert clicks == []


def test_click_needs_the_token(click_server, clicks):
    assert request(click_server, "POST", "/click", {"session_id": "a"}, token="wrong")[0] == 401
    assert clicks == []


def test_click_is_not_found_when_not_offered(server):
    assert request(server, "POST", "/click", {"session_id": "a"})[0] == 404
