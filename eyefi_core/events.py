"""Abstract pub/sub interface for eyefi_core's lifecycle events.

Two implementations share this same public shape so switching between
embedded mode and standalone-daemon mode is a config toggle, not a rewrite:

- :class:`InProcessEventBus` (this module) — plain asyncio callbacks, used
  when eyefi_core runs embedded inside HA's event loop.
- A future WebSocket-backed bus (``eyefi_core/service.py``) — same
  :class:`EventBus` protocol, publishing over ``/events`` to remote
  subscribers (a standalone HA client, a future Homebridge/HOOBS plugin).

Subscribers and publishers only ever depend on :class:`EventBus`, never on
which implementation is wired up.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

_LOGGER = logging.getLogger(__name__)


class EventType(str, Enum):
    IMAGE_RECEIVED = "eyefi_image_received"
    IMAGE_GEOTAGGED = "eyefi_image_geotagged"
    IMAGE_STORED = "eyefi_image_stored"


@dataclass(frozen=True, slots=True)
class Event:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)


EventCallback = Callable[[Event], "Awaitable[None] | None"]
Unsubscribe = Callable[[], None]


class EventBus(Protocol):
    async def publish(self, event: Event) -> None: ...

    def subscribe(self, event_type: EventType, callback: EventCallback) -> Unsubscribe: ...


class InProcessEventBus:
    """Direct in-memory dispatch: publish() fires every subscriber for that
    event type as a background task and returns immediately, so a slow or
    failing subscriber never blocks the upload pipeline.
    """

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[EventCallback]] = {}

    def subscribe(self, event_type: EventType, callback: EventCallback) -> Unsubscribe:
        self._subscribers.setdefault(event_type, []).append(callback)

        def unsubscribe() -> None:
            self._subscribers.get(event_type, []).remove(callback)

        return unsubscribe

    async def publish(self, event: Event) -> None:
        for callback in list(self._subscribers.get(event.type, [])):
            result = callback(event)
            if asyncio.iscoroutine(result):
                task = asyncio.create_task(result)
                task.add_done_callback(self._log_if_failed)

    @staticmethod
    def _log_if_failed(task: asyncio.Task) -> None:
        if not task.cancelled() and (exc := task.exception()) is not None:
            _LOGGER.exception("eyefi_core event subscriber raised", exc_info=exc)
