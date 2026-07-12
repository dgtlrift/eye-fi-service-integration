"""Eye-Fi SOAP protocol: XML envelopes and credential/digest cryptography.

Wire format and credential math verified against the reference
implementations (read-only reference material, no code copied verbatim):
tachang/EyeFiServer (``Documentation/EyeFi Protocol.txt``,
``Release 2.0/EyeFiServer.py``, ``Release 2.0/EyeFiCrypto.py``) and
dgrant/eyefiserver2 (``usr/local/bin/eyefiserver.py``).

Credential math (both directions operate on the *raw bytes* the hex
strings represent, not on their ASCII form)::

    StartSession:    credential = md5(unhexlify(mac + cnonce + upload_key))
    GetPhotoStatus:  credential = md5(unhexlify(mac + upload_key + snonce))
"""

from __future__ import annotations

import array
import binascii
import hashlib
import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass

SOAP_PATH = "/api/soap/eyefilm/v1"
UPLOAD_PATH = "/api/soap/eyefilm/v1/upload"

SOAP_ACTION_START_SESSION = '"urn:StartSession"'
SOAP_ACTION_GET_PHOTO_STATUS = '"urn:GetPhotoStatus"'
SOAP_ACTION_MARK_LAST_PHOTO_IN_ROLL = '"urn:MarkLastPhotoInRoll"'

SOAP_ENVELOPE_NS = "http://schemas.xmlsoap.org/soap/envelope/"
EYEFILM_RESPONSE_NS = "http://localhost/api/soap/eyefilm"


class ProtocolError(ValueError):
    """The card sent a request that doesn't match the expected wire format."""


# --------------------------------------------------------------------------
# Credential math
# --------------------------------------------------------------------------


def _hex_concat_md5(*hex_parts: str) -> str:
    """MD5 the raw bytes represented by the concatenation of hex strings."""
    raw = binascii.unhexlify("".join(hex_parts))
    return hashlib.md5(raw).hexdigest()


def start_session_credential(macaddress: str, cnonce: str, upload_key: str) -> str:
    """Credential the server returns in StartSessionResponse."""
    return _hex_concat_md5(macaddress, cnonce, upload_key)


def photo_status_credential(macaddress: str, upload_key: str, snonce: str) -> str:
    """Credential the card is expected to present in GetPhotoStatus."""
    return _hex_concat_md5(macaddress, upload_key, snonce)


# --------------------------------------------------------------------------
# Upload integrity digest (trailing INTEGRITYDIGEST multipart field)
# --------------------------------------------------------------------------


def _tcp_checksum(chunk: bytes) -> int:
    """One's-complement TCP-style checksum over a (possibly padded) chunk."""
    if len(chunk) % 2 != 0:
        chunk += b"\x00"
    total = 0
    for offset in range(0, len(chunk), 2):
        total += struct.unpack_from("<H", chunk, offset)[0]
    while total >> 16:
        total = (total >> 16) + (total & 0xFFFF)
    return (total ^ 0xFFFFFFFF) & 0xFFFF


def calculate_integrity_digest(data: bytes, upload_key: str) -> str:
    """Reference digest algorithm: checksum every 512-byte block of the tar
    payload, append the upload key's raw bytes, and MD5 the result.

    CPU-bound and synchronous by design — call via
    ``loop.run_in_executor`` for large payloads to avoid blocking the event
    loop.
    """
    if len(data) % 512 != 0:
        data = data + b"\x00" * (512 - len(data) % 512)

    checksums = array.array("H")
    for offset in range(0, len(data), 512):
        checksums.append(_tcp_checksum(data[offset : offset + 512]))
    checksums.frombytes(binascii.unhexlify(upload_key))

    return hashlib.md5(checksums.tobytes()).hexdigest()


# --------------------------------------------------------------------------
# Request parsing
# --------------------------------------------------------------------------

_KNOWN_FIELDS = frozenset(
    {
        "macaddress",
        "cnonce",
        "snonce",
        "transfermode",
        "transfermodetimestamp",
        "fileid",
        "filename",
        "filesize",
        "filesignature",
        "credential",
    }
)


def _extract_fields(xml_bytes: bytes) -> dict[str, str]:
    """Flat whitelist extraction of known field names, regardless of nesting
    or namespace — mirrors the reference SAX handlers' behavior, which pick
    matching element names out of the tree without caring where they sit.
    """
    root = ET.fromstring(xml_bytes)
    found: dict[str, str] = {}
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in _KNOWN_FIELDS and el.text is not None:
            found[tag] = el.text.strip()
    return found


@dataclass(frozen=True, slots=True)
class StartSessionRequest:
    macaddress: str
    cnonce: str
    transfermode: str
    transfermodetimestamp: str


@dataclass(frozen=True, slots=True)
class GetPhotoStatusRequest:
    macaddress: str
    credential: str
    filename: str
    filesize: int
    filesignature: str


def parse_start_session_request(body: bytes) -> StartSessionRequest:
    fields = _extract_fields(body)
    try:
        return StartSessionRequest(
            macaddress=fields["macaddress"],
            cnonce=fields["cnonce"],
            transfermode=fields["transfermode"],
            transfermodetimestamp=fields["transfermodetimestamp"],
        )
    except KeyError as exc:
        raise ProtocolError(f"StartSession request missing field {exc}") from exc


def parse_get_photo_status_request(body: bytes) -> GetPhotoStatusRequest:
    fields = _extract_fields(body)
    try:
        return GetPhotoStatusRequest(
            macaddress=fields["macaddress"],
            credential=fields["credential"],
            filename=fields["filename"],
            filesize=int(fields["filesize"]),
            filesignature=fields["filesignature"],
        )
    except KeyError as exc:
        raise ProtocolError(f"GetPhotoStatus request missing field {exc}") from exc


@dataclass(frozen=True, slots=True)
class UploadSoapEnvelope:
    macaddress: str
    filename: str


def parse_upload_soap_envelope(xml_bytes: bytes) -> UploadSoapEnvelope:
    """Parse the ``SOAPENVELOPE`` multipart field of an UploadPhoto
    request."""
    fields = _extract_fields(xml_bytes)
    try:
        return UploadSoapEnvelope(macaddress=fields["macaddress"], filename=fields["filename"])
    except KeyError as exc:
        raise ProtocolError(f"UploadPhoto SOAPENVELOPE missing field {exc}") from exc


# --------------------------------------------------------------------------
# Multipart fallback parser
# --------------------------------------------------------------------------
#
# Eye-Fi cards' multipart/form-data encoder is not fully RFC-compliant (this
# is the most common bug point in prior server implementations, per the
# project brief). aiohttp's stricter reader is used as the primary parser;
# this manual fallback only runs if that raises outright.


def parse_multipart_manual(content_type: str, body: bytes) -> dict[str, bytes]:
    boundary_match = re.search(r'boundary="?([^";]+)"?', content_type)
    if not boundary_match:
        raise ProtocolError("multipart Content-Type has no boundary parameter")
    boundary = b"--" + boundary_match.group(1).encode()

    parts: dict[str, bytes] = {}
    for raw_part in body.split(boundary):
        raw_part = raw_part.strip(b"\r\n")
        if not raw_part or raw_part == b"--":
            continue
        header_blob, sep, part_body = raw_part.partition(b"\r\n\r\n")
        if not sep:
            continue
        name_match = re.search(rb'name="([^"]+)"', header_blob)
        if not name_match:
            continue
        parts[name_match.group(1).decode()] = part_body.rstrip(b"\r\n")
    return parts


# --------------------------------------------------------------------------
# Response envelopes
# --------------------------------------------------------------------------

_XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>'


def build_start_session_response(
    *,
    credential: str,
    snonce: str,
    transfermode: str,
    transfermodetimestamp: str,
    upsyncallowed: bool = False,
) -> bytes:
    xml = (
        f"{_XML_DECL}"
        f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_ENVELOPE_NS}">'
        "<SOAP-ENV:Body>"
        f'<StartSessionResponse xmlns="{EYEFILM_RESPONSE_NS}">'
        f"<credential>{credential}</credential>"
        f"<snonce>{snonce}</snonce>"
        f"<transfermode>{transfermode}</transfermode>"
        f"<transfermodetimestamp>{transfermodetimestamp}</transfermodetimestamp>"
        f"<upsyncallowed>{'true' if upsyncallowed else 'false'}</upsyncallowed>"
        "</StartSessionResponse>"
        "</SOAP-ENV:Body>"
        "</SOAP-ENV:Envelope>"
    )
    return xml.encode("utf-8")


def build_get_photo_status_response(*, fileid: str = "1", offset: str = "0") -> bytes:
    xml = (
        f"{_XML_DECL}"
        f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_ENVELOPE_NS}">'
        "<SOAP-ENV:Body>"
        f'<GetPhotoStatusResponse xmlns="{EYEFILM_RESPONSE_NS}">'
        f"<fileid>{fileid}</fileid>"
        f"<offset>{offset}</offset>"
        "</GetPhotoStatusResponse>"
        "</SOAP-ENV:Body>"
        "</SOAP-ENV:Envelope>"
    )
    return xml.encode("utf-8")


def build_upload_photo_response(*, success: bool) -> bytes:
    xml = (
        f"{_XML_DECL}"
        f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_ENVELOPE_NS}">'
        "<SOAP-ENV:Body>"
        "<UploadPhotoResponse>"
        f"<success>{'true' if success else 'false'}</success>"
        "</UploadPhotoResponse>"
        "</SOAP-ENV:Body>"
        "</SOAP-ENV:Envelope>"
    )
    return xml.encode("utf-8")


def build_mark_last_photo_in_roll_response() -> bytes:
    xml = (
        f"{_XML_DECL}"
        f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_ENVELOPE_NS}">'
        "<SOAP-ENV:Body>"
        "<MarkLastPhotoInRollResponse></MarkLastPhotoInRollResponse>"
        "</SOAP-ENV:Body>"
        "</SOAP-ENV:Envelope>"
    )
    return xml.encode("utf-8")
