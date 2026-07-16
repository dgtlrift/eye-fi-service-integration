## Proposed change

Add `reorder: bool` support to the `select` selector's `SelectSelectorConfig`,
matching the existing `area`/`entity` selectors.

The frontend (`ha-selector-select.ts`) has fully supported `reorder: true`
for `select`'s `multiple: true` case since #18180 (merged 2023-10-24) —
this predates `entity`'s (#26217) and `area`'s (#30056) equivalents. It's
already used internally by several Lovelace card-feature editors
(`customizable-list-feature.ts`, `hui-select-options-card-feature-editor.ts`,
`hui-alarm-modes-card-feature-editor.ts`), which build the selector's
JSON schema directly in TypeScript and so bypass the backend entirely.

The only gap is that `SelectSelectorConfig`/`SelectSelector.CONFIG_SCHEMA`
in `homeassistant/helpers/selector.py` never grew a `reorder` key. Since
`make_selector_config_schema` defaults to `PREVENT_EXTRA`, any blueprint,
script, or custom integration passing `reorder: true` in a `select`
selector's config today gets an "extra keys not allowed" validation error
— even though the frontend would render the (already fully working) drag
UI perfectly if the config ever reached it.

This PR closes that gap the same way `AreaSelector`/`EntitySelector`
already do: add the field, wrap `CONFIG_SCHEMA` in
`vol.All(..., _validate_selector_reorder_config)`, reusing the existing
shared validator rather than adding new logic. No `__call__` changes are
needed — `reorder` is a pure pass-through config flag in both existing
selectors that support it (never read by their runtime validation logic),
and there's no reason `SelectSelector` would need to differ.

## Type of change

- [x] New feature (which adds functionality to an existing integration)

## Additional information

- This is a Python-only change. No frontend changes are needed or included
  — the rendering support already exists and ships today.
- A matching docs change (adding the `reorder` field to the "Select
  selector" section of `home-assistant.io`) is prepared separately.
- I couldn't run the full test suite against a clean checkout of `dev` —
  it currently has an unrelated, pre-existing syntax error elsewhere in
  `selector.py` (a Python 2-style `except A, B:` in a different selector
  class) that blocks importing the module at all. Not something this PR
  touches or needs to fix.

## Checklist

- [ ] The code change is tested and works locally -- *not independently
  confirmed against the real `tests/helpers/test_selector.py` run, since
  an unrelated pre-existing syntax error elsewhere in `selector.py` on
  `dev` currently blocks importing the module at all (see above). The
  identical schema-construction pattern (add field, wrap in `vol.All`,
  reuse `_validate_selector_reorder_config`) is verified passing in an
  isolated harness in a separate project, for what that's worth as
  supporting evidence, but that isn't a substitute for running HA's own
  test suite.
- [x] Tests have been added to verify that the new code works (see
  `tests/helpers/test_selector.py` changes: one new valid
  `multiple + reorder` case, two new invalid `reorder`-without-`multiple`
  cases) -- pending a real run once the blocking issue above is resolved.
