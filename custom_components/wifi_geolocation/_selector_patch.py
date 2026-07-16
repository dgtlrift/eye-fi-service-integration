"""Temporary local patch adding ``reorder`` support to HA's SelectSelector.

HA's *frontend* (``ha-selector-select.ts``) has fully supported
``reorder: true`` for the ``select`` selector since PR #18180 (merged
2023-10-24) — the drag UI, ``ha-sortable`` wiring, and TS type all
already exist and are used internally by several Lovelace card-feature
editors. The only gap is that ``homeassistant.helpers.selector.
SelectSelectorConfig``/``SelectSelector.CONFIG_SCHEMA`` (Python,
home-assistant/core) never added a ``reorder`` key, so it's rejected as
an extra key before ever reaching that already-working frontend code.

This module defensively extends the *running* ``CONFIG_SCHEMA`` to add
it, reusing HA's own ``_validate_selector_reorder_config`` (the exact
function ``AreaSelector``/``EntitySelector`` already use for the same
purpose) rather than reimplementing validation logic. Delete this module
(and switch ``config_flow.py``'s backend field back to a plain
``SelectSelector`` call without checking ``patch_select_selector_reorder()``'s
result) once the upstream PR proposing this ships in a stable HA release.
"""

from __future__ import annotations

import logging

import voluptuous as vol

_LOGGER = logging.getLogger(__name__)


def patch_select_selector_reorder() -> bool:
    """Add reorder support to SelectSelector.

    Returns True if the patch was applied (or was already applied by a
    previous call), False if upstream HA already supports it natively or
    if patching failed safely -- callers must treat False as "don't set
    reorder=True in a SelectSelectorConfig", since an unpatched HA would
    reject it outright.
    """
    try:
        from homeassistant.helpers import config_validation as cv
        from homeassistant.helpers import selector as ha_selector

        if "reorder" in getattr(ha_selector.SelectSelectorConfig, "__annotations__", {}):
            return True  # upstream already added it natively, or we already patched it

        ha_selector.SelectSelectorConfig.__annotations__["reorder"] = bool

        ha_selector.SelectSelector.CONFIG_SCHEMA = vol.All(
            ha_selector.make_selector_config_schema(
                {
                    vol.Required("options"): vol.All(
                        vol.Any([str], [ha_selector.select_option])
                    ),
                    vol.Optional("multiple", default=False): cv.boolean,
                    vol.Optional("custom_value", default=False): cv.boolean,
                    vol.Optional("mode"): vol.All(
                        vol.Coerce(ha_selector.SelectSelectorMode), lambda val: val.value
                    ),
                    vol.Optional("translation_key"): cv.string,
                    vol.Optional("sort", default=False): cv.boolean,
                    vol.Optional("reorder", default=False): cv.boolean,
                }
            ),
            ha_selector._validate_selector_reorder_config,
        )
    except Exception:
        _LOGGER.exception(
            "Could not patch SelectSelector for reorder support -- "
            "falling back to the numeric-priority backend UI"
        )
        return False
    return True
