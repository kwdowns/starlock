"""Blocking HTTP client for the Starlock Cloud device API (stdlib only).

Every call runs on a cloud worker thread, never the solver or web-server
threads. Errors come back as ``CloudError`` with the HTTP status (0 for a
network error or timeout); 401 is ``Unauthorized``: the link was revoked.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

DEFAULT_TIMEOUT_S = 10.0  # the service may be cold-starting (scale to zero)
USER_AGENT = "starlock-pi"


class CloudError(Exception):
    def __init__(self, status: int, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        """Network errors, timeouts, 429 and 5xx are worth retrying."""
        return self.status == 0 or self.status == 429 or self.status >= 500


class Unauthorized(CloudError):
    """401: the device credential was revoked."""


class CloudClient:
    def __init__(self, base_url: str, credential: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT_S) -> None:
        self.base_url = base_url.rstrip("/")
        self._credential = credential
        self._timeout = timeout

    def _request(self, method: str, path: str, body: Any = None,
                 headers: dict[str, str] | None = None, auth: bool = True) -> Any:
        url = f"{self.base_url}/v1{path}"
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("User-Agent", USER_AGENT)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if auth and self._credential:
            req.add_header("Authorization", f"Device {self._credential}")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = _problem_detail(exc)
            retry_after = None
            if exc.headers and exc.headers.get("Retry-After"):
                try:
                    retry_after = float(exc.headers["Retry-After"])
                except ValueError:
                    pass
            cls = Unauthorized if exc.code == 401 else CloudError
            raise cls(exc.code, detail, retry_after) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise CloudError(0, f"network error: {reason}") from None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    # -- calls (docs/pi-integration.md) -------------------------------------

    def claim(self, code: str, name: str, *, model: str | None, software_version: str | None,
              local_id: str | None) -> dict:
        body = {"code": code, "name": name[:60]}
        if model:
            body["model"] = model
        if software_version:
            body["softwareVersion"] = software_version
        if local_id:
            body["localId"] = local_id
        return self._request("POST", "/pairing/claim", body, auth=False)

    def get_device(self) -> dict:
        return self._request("GET", "/device")

    def delete_device(self) -> None:
        self._request("DELETE", "/device")

    def post_pointing(self, body: dict, session: str) -> dict | None:
        return self._request("POST", "/device/pointing", body,
                             headers={"X-Starlock-Session": session})

    def post_observations(self, entries: list[dict]) -> dict:
        return self._request("POST", "/device/observations", {"entries": entries})


def _problem_detail(exc: urllib.error.HTTPError) -> str:
    try:
        data = json.loads(exc.read() or b"{}")
        text = data.get("detail") or data.get("title")
        if text:
            return f"HTTP {exc.code}: {text}"
    except (ValueError, AttributeError, OSError):
        pass
    return f"HTTP {exc.code}"
