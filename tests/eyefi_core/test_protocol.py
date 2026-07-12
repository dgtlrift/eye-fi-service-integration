import binascii
import hashlib

from eyefi_core import protocol


def test_start_session_credential_matches_hand_computed_md5():
    mac = "0018560304f8"
    cnonce = "9219c72db0ecbd7e585bb10551f6bc38"
    upload_key = "c686e547e3728c63a8f78729c1592757"[:32]  # 32 hex chars = 16 bytes

    expected = hashlib.md5(binascii.unhexlify(mac + cnonce + upload_key)).hexdigest()
    assert protocol.start_session_credential(mac, cnonce, upload_key) == expected


def test_photo_status_credential_uses_mac_uploadkey_snonce_order():
    mac = "0018560304f8"
    upload_key = "c686e547e3728c63a8f78729c1592757"[:32]
    snonce = "99208c155fc1883579cf0812ec0fe6d2"

    expected = hashlib.md5(binascii.unhexlify(mac + upload_key + snonce)).hexdigest()
    assert protocol.photo_status_credential(mac, upload_key, snonce) == expected

    # Direction matters: swapping upload_key/snonce order must NOT match.
    wrong_order = hashlib.md5(binascii.unhexlify(mac + snonce + upload_key)).hexdigest()
    assert protocol.photo_status_credential(mac, upload_key, snonce) != wrong_order


def test_parse_start_session_request_from_reference_transcript():
    # Verbatim transcript from tachang/EyeFiServer's EyeFi Protocol.txt.
    body = b"""<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="EyeFi/SOAP/EyeFilm">
      <SOAP-ENV:Body>
            <ns1:StartSession>
                  <macaddress>0018560304f8</macaddress>
                  <cnonce>9219c72db0ecbd7e585bb10551f6bc38</cnonce>
                  <transfermode>2</transfermode>
                  <transfermodetimestamp>315532800</transfermodetimestamp>
            </ns1:StartSession>
      </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""

    req = protocol.parse_start_session_request(body)
    assert req.macaddress == "0018560304f8"
    assert req.cnonce == "9219c72db0ecbd7e585bb10551f6bc38"
    assert req.transfermode == "2"
    assert req.transfermodetimestamp == "315532800"


def test_parse_get_photo_status_request_from_reference_transcript():
    body = b"""<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="EyeFi/SOAP/EyeFilm">
      <SOAP-ENV:Body>
            <ns1:GetPhotoStatus>
                  <credential>10ff036d3861ed3d1c47eb52d14841d2</credential>
                  <macaddress>0018560304f8</macaddress>
                  <filename>CIMG1738.JPG.tar</filename>
                  <filesize>4518912</filesize>
                  <filesignature>1077ffb9ac2718b116a33475ad809bf7</filesignature>
            </ns1:GetPhotoStatus>
      </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""

    req = protocol.parse_get_photo_status_request(body)
    assert req.macaddress == "0018560304f8"
    assert req.credential == "10ff036d3861ed3d1c47eb52d14841d2"
    assert req.filename == "CIMG1738.JPG.tar"
    assert req.filesize == 4518912
    assert req.filesignature == "1077ffb9ac2718b116a33475ad809bf7"


def test_build_start_session_response_round_trips_credential_and_snonce():
    response = protocol.build_start_session_response(
        credential="f138ce5977a8962a089b87e17155e53",
        snonce="99208c155fc1883579cf0812ec0fe6d2",
        transfermode="2",
        transfermodetimestamp="1230268824",
    )
    fields = protocol._extract_fields(response)
    assert fields["credential"] == "f138ce5977a8962a089b87e17155e53"
    assert fields["snonce"] == "99208c155fc1883579cf0812ec0fe6d2"
    assert b"<upsyncallowed>false</upsyncallowed>" in response


def test_calculate_integrity_digest_is_deterministic_and_key_sensitive():
    data = b"x" * 1000
    upload_key = "00112233445566778899aabbccddeeff"[:32]
    other_key = "ffeeddccbbaa99887766554433221100"[:32]

    digest_a = protocol.calculate_integrity_digest(data, upload_key)
    digest_b = protocol.calculate_integrity_digest(data, upload_key)
    digest_c = protocol.calculate_integrity_digest(data, other_key)

    assert digest_a == digest_b
    assert digest_a != digest_c
    assert len(digest_a) == 32  # hex-encoded MD5


def test_parse_multipart_manual_extracts_named_parts():
    # Per RFC 2046, each delimiter line is "--" + the boundary *value*
    # (here "boundary123"), so lines read "--boundary123" / "--boundary123--".
    content_type = 'multipart/form-data; boundary="boundary123"'
    body = (
        b"--boundary123\r\n"
        b'Content-Disposition: form-data; name="SOAPENVELOPE"\r\n\r\n'
        b"<xml>hello</xml>\r\n"
        b"--boundary123\r\n"
        b'Content-Disposition: form-data; name="FILENAME"\r\n\r\n'
        b"binarydata\r\n"
        b"--boundary123--\r\n"
    )
    parts = protocol.parse_multipart_manual(content_type, body)
    assert parts["SOAPENVELOPE"] == b"<xml>hello</xml>"
    assert parts["FILENAME"] == b"binarydata"
