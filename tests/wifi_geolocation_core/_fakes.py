"""Shared fake aiohttp session for backend tests -- no real network calls."""

from __future__ import annotations

import json as json_module
from contextlib import asynccontextmanager


class FakeResponse:
    def __init__(self, status: int, body: dict):
        self.status = status
        self._body = body

    async def json(self):
        return self._body

    async def text(self):
        return json_module.dumps(self._body)


class FakeSession:
    """Records every request made and returns a scripted response for it."""

    def __init__(self, response: FakeResponse):
        self._response = response
        self.requests: list[dict] = []

    @asynccontextmanager
    async def _request(self, method: str, url: str, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        yield self._response

    def post(self, url, **kwargs):
        return self._request("POST", url, **kwargs)

    def get(self, url, **kwargs):
        return self._request("GET", url, **kwargs)


def fake_session(status: int, body: dict) -> FakeSession:
    return FakeSession(FakeResponse(status, body))
