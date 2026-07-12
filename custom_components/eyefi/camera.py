"""Optional camera entity showing the most recently received Eye-Fi photo.

Just another subscriber to eyefi_core's events, same as the ``hass.bus``
firing in ``__init__.py`` — this entity holds no protocol/storage logic of
its own.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from eyefi_core.events import Event, EventType

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    server = hass.data[DOMAIN][entry.entry_id]["server"]
    entity = EyeFiCamera(entry.entry_id, entry.title)
    server.event_bus.subscribe(EventType.IMAGE_RECEIVED, entity.handle_event)
    async_add_entities([entity])


class EyeFiCamera(Camera):
    _attr_should_poll = False

    def __init__(self, entry_id: str, name: str) -> None:
        super().__init__()
        self._attr_unique_id = f"{entry_id}_latest_photo"
        self._attr_name = name
        self._latest_image_path: Path | None = None

    def handle_event(self, event: Event) -> None:
        self._latest_image_path = Path(event.data["image_path"])
        self.async_write_ha_state()

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        if self._latest_image_path is None or not self._latest_image_path.exists():
            return None
        return await self.hass.async_add_executor_job(self._latest_image_path.read_bytes)
