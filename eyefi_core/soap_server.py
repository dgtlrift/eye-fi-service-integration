"""aiohttp-based Eye-Fi SOAP server: StartSession, GetPhotoStatus,
UploadPhoto, MarkLastPhotoInRoll.

Binds its own ``aiohttp.web.Application`` on port 59278 — hardcoded in the
card's firmware, not configurable, and not something HA's built-in HTTP
component (bound to 8123) can serve. Runs standalone in embedded mode
(started/stopped from ``custom_components/eyefi/__init__.py``) or inside
``eyefi_core/service.py`` in standalone-daemon mode — identical code
either way.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from pathlib import Path

from aiohttp import web

from eyefi_core import geotag, protocol, tar_extract
from eyefi_core.events import Event, EventBus, EventType, InProcessEventBus
from eyefi_core.storage import StorageBackend, StorageError

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 59278


class EyeFiSoapServer:
    """One instance serves all cards configured via ``cards`` (mac ->
    upload key), matching the multi-card shape used by prior servers."""

    def __init__(
        self,
        *,
        cards: dict[str, str],
        download_dir: Path,
        storage_backend: StorageBackend,
        event_bus: EventBus | None = None,
        geotag_backend: geotag.GeolocationBackend | None = None,
        geotag_lag: int = geotag.DEFAULT_GEOTAG_LAG_SECONDS,
        host: str = "0.0.0.0",
        port: int = DEFAULT_PORT,
    ) -> None:
        self._cards = cards
        self._download_dir = download_dir
        self._storage_backend = storage_backend
        self._event_bus = event_bus or InProcessEventBus()
        self._geotag_backend = geotag_backend
        self._geotag_lag = geotag_lag
        self._host = host
        self._port = port

        # macaddress -> server nonce issued in that card's last StartSession,
        # needed to verify the credential it presents in GetPhotoStatus.
        self._session_nonces: dict[str, str] = {}
        self._background_tasks: set[asyncio.Task] = set()

        self._app = web.Application(client_max_size=64 * 1024 * 1024)
        self._app.router.add_post(protocol.SOAP_PATH, self._handle_soap)
        self._app.router.add_post(protocol.UPLOAD_PATH, self._handle_upload)
        self._runner: web.AppRunner | None = None

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        _LOGGER.info("Eye-Fi SOAP server listening on %s:%s", self._host, self._port)

    async def stop(self) -> None:
        for task in list(self._background_tasks):
            task.cancel()
        if self._runner is not None:
            await self._runner.cleanup()

    # -- /api/soap/eyefilm/v1 ------------------------------------------------

    async def _handle_soap(self, request: web.Request) -> web.Response:
        soap_action = request.headers.get("SOAPAction", "")
        body = await request.read()

        if soap_action == protocol.SOAP_ACTION_START_SESSION:
            return await self._start_session(body)
        if soap_action == protocol.SOAP_ACTION_GET_PHOTO_STATUS:
            return await self._get_photo_status(body)
        if soap_action == protocol.SOAP_ACTION_MARK_LAST_PHOTO_IN_ROLL:
            _LOGGER.info("MarkLastPhotoInRoll received")
            return web.Response(
                body=protocol.build_mark_last_photo_in_roll_response(),
                content_type="text/xml",
            )

        _LOGGER.warning("Unrecognized SOAPAction: %r", soap_action)
        return web.Response(status=400)

    async def _start_session(self, body: bytes) -> web.Response:
        try:
            req = protocol.parse_start_session_request(body)
        except protocol.ProtocolError:
            _LOGGER.exception("Malformed StartSession request")
            return web.Response(status=400)

        upload_key = self._cards.get(req.macaddress)
        if upload_key is None:
            _LOGGER.warning("StartSession from unknown card mac %s", req.macaddress)
            return web.Response(status=403)

        snonce = secrets.token_hex(16)
        self._session_nonces[req.macaddress] = snonce
        credential = protocol.start_session_credential(req.macaddress, req.cnonce, upload_key)
        _LOGGER.info("StartSession established for card %s", req.macaddress)

        response = protocol.build_start_session_response(
            credential=credential,
            snonce=snonce,
            transfermode=req.transfermode,
            transfermodetimestamp=req.transfermodetimestamp,
        )
        return web.Response(body=response, content_type="text/xml")

    async def _get_photo_status(self, body: bytes) -> web.Response:
        try:
            req = protocol.parse_get_photo_status_request(body)
        except protocol.ProtocolError:
            _LOGGER.exception("Malformed GetPhotoStatus request")
            return web.Response(status=400)

        upload_key = self._cards.get(req.macaddress)
        snonce = self._session_nonces.get(req.macaddress, "")
        if upload_key is not None:
            expected = protocol.photo_status_credential(req.macaddress, upload_key, snonce)
            if not secrets.compare_digest(req.credential, expected):
                _LOGGER.warning("Credential mismatch for card %s", req.macaddress)

        _LOGGER.info("GetPhotoStatus from card %s", req.macaddress)
        return web.Response(
            body=protocol.build_get_photo_status_response(), content_type="text/xml"
        )

    # -- /api/soap/eyefilm/v1/upload -----------------------------------------

    async def _handle_upload(self, request: web.Request) -> web.Response:
        content_type = request.headers.get("Content-Type", "")
        parts = await self._read_multipart(request, content_type)

        try:
            envelope = protocol.parse_upload_soap_envelope(parts["SOAPENVELOPE"])
        except (KeyError, protocol.ProtocolError):
            _LOGGER.exception("Malformed UploadPhoto SOAPENVELOPE")
            return web.Response(
                body=protocol.build_upload_photo_response(success=False),
                content_type="text/xml",
            )

        upload_key = self._cards.get(envelope.macaddress)
        if upload_key is None:
            _LOGGER.warning("UploadPhoto from unknown card mac %s", envelope.macaddress)
            return web.Response(
                body=protocol.build_upload_photo_response(success=False),
                content_type="text/xml",
            )

        try:
            tar_bytes = parts["FILENAME"]
            expected_digest = parts["INTEGRITYDIGEST"].decode().strip()
        except KeyError:
            _LOGGER.exception("UploadPhoto multipart missing FILENAME/INTEGRITYDIGEST part")
            return web.Response(
                body=protocol.build_upload_photo_response(success=False),
                content_type="text/xml",
            )

        try:
            extracted = await tar_extract.extract_upload(
                tar_bytes,
                upload_key=upload_key,
                expected_digest=expected_digest,
                dest_dir=self._download_dir / envelope.macaddress,
            )
        except tar_extract.IntegrityError:
            _LOGGER.exception("Integrity check failed for %s", envelope.filename)
            return web.Response(
                body=protocol.build_upload_photo_response(success=False),
                content_type="text/xml",
            )

        _LOGGER.info(
            "UploadPhoto from card %s: %d file(s) extracted", envelope.macaddress, len(extracted)
        )
        for item in extracted:
            task = asyncio.create_task(self._process_upload(item, envelope.macaddress))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        return web.Response(
            body=protocol.build_upload_photo_response(success=True), content_type="text/xml"
        )

    async def _read_multipart(
        self, request: web.Request, content_type: str
    ) -> dict[str, bytes]:
        try:
            reader = await request.multipart()
            parts: dict[str, bytes] = {}
            async for part in reader:
                if part.name is not None:
                    parts[part.name] = await part.read(decode=False)
            if not parts:
                raise ValueError("aiohttp multipart reader found no parts")
            return parts
        except Exception:
            _LOGGER.debug(
                "aiohttp multipart reader failed, falling back to manual parser",
                exc_info=True,
            )
            body = await request.read()
            return protocol.parse_multipart_manual(content_type, body)

    async def _process_upload(self, item: tar_extract.ExtractedUpload, macaddress: str) -> None:
        await self._event_bus.publish(
            Event(
                EventType.IMAGE_RECEIVED,
                {"image_path": str(item.image_path), "macaddress": macaddress},
            )
        )

        coordinates = None
        if item.log_path is not None and self._geotag_backend is not None:
            try:
                coordinates = await geotag.geotag_image(
                    image_path=item.image_path,
                    log_path=item.log_path,
                    backend=self._geotag_backend,
                    geotag_lag=self._geotag_lag,
                )
            except Exception:
                _LOGGER.exception("Geotagging failed for %s", item.image_path)
            else:
                if coordinates is not None:
                    await self._event_bus.publish(
                        Event(
                            EventType.IMAGE_GEOTAGGED,
                            {
                                "image_path": str(item.image_path),
                                "macaddress": macaddress,
                                "latitude": coordinates.latitude,
                                "longitude": coordinates.longitude,
                            },
                        )
                    )

        metadata = {
            "macaddress": macaddress,
            "filename": item.image_path.name,
            "latitude": coordinates.latitude if coordinates else None,
            "longitude": coordinates.longitude if coordinates else None,
        }
        try:
            await self._storage_backend.store(item.image_path, metadata)
        except StorageError:
            _LOGGER.exception("Storage failed for %s", item.image_path)
            return

        _LOGGER.info("Image stored: %s (card %s)", item.image_path.name, macaddress)
        await self._event_bus.publish(
            Event(
                EventType.IMAGE_STORED,
                {"image_path": str(item.image_path), "macaddress": macaddress},
            )
        )
