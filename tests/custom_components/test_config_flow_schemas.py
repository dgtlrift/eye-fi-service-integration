"""Regression test for a real bug: HA's frontend serializes every
config-flow schema via ``voluptuous_serialize.convert()`` before sending it
to the browser. A bare custom function used as a validator (e.g.
``vol.All(str, my_func)``) can't be serialized and raises ValueError at
form-render time — a 500 error on "Add Integration" that only ever shows up
against a real Home Assistant instance, never in a plain py_compile/unit
test. This test catches that class of bug without needing `homeassistant`
installed, since voluptuous_serialize itself has no HA dependency.
"""

import pytest
import voluptuous_serialize

from _ha_stub import load_config_flow_schemas


@pytest.fixture(scope="module")
def schemas():
    return load_config_flow_schemas("eyefi")


def test_card_schema_is_frontend_serializable(schemas):
    _serialize(schemas["_CARD_SCHEMA"])


def test_destination_schemas_are_frontend_serializable(schemas):
    for schema in schemas["_DESTINATION_SCHEMAS"].values():
        _serialize(schema)


def test_local_path_destination_schemas_are_frontend_serializable(schemas):
    build_destination_schema = schemas["_build_destination_schema"]
    for destination in schemas["_LOCAL_PATH_DESTINATIONS"]:
        _serialize(build_destination_schema(destination, "/config/eyefi_downloads"))


def test_local_path_destination_default_is_subfolder_of_download_dir(schemas):
    build_destination_schema = schemas["_build_destination_schema"]
    for destination in schemas["_LOCAL_PATH_DESTINATIONS"]:
        schema = build_destination_schema(destination, "/config/eyefi_downloads")
        (marker,) = schema.schema.keys()
        assert marker.default() == "/config/eyefi_downloads/photos"


def _serialize(schema):
    # UNSUPPORTED (not None) signals "no special handling" to voluptuous_serialize,
    # matching HA's real cv.custom_serializer — returning None here would mask
    # exactly the bug this test exists to catch.
    voluptuous_serialize.convert(
        schema, custom_serializer=lambda _schema: voluptuous_serialize.UNSUPPORTED
    )
