from starlette.requests import Request

from core.infrastructure.auth import is_local_registry_route


def _request(method: str, path: str, host: str) -> Request:
    return Request({
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": (host, 12345),
        "server": ("localhost", 8010),
        "scheme": "http",
    })


def test_registry_registration_is_allowed_from_loopback():
    assert is_local_registry_route(_request("POST", "/registry/register", "127.0.0.1"))
    assert is_local_registry_route(_request("POST", "/registry/heartbeat", "::1"))


def test_registry_registration_is_not_open_to_remote_clients():
    assert not is_local_registry_route(_request("POST", "/registry/register", "192.0.2.10"))
    assert not is_local_registry_route(_request("GET", "/registry/services", "127.0.0.1"))
