# UI review — Patchdeck 0.6.2

Reviewed on 2026-10-20 using `apple-design`, `mobile-native`, and the requested
`apple-hig` catalogue. The catalogue points to the full
[HIG skill bundle](https://github.com/raintree-technology/hig-doctor), inspected at
`fdc35993d580730a60b827ed39adc6c9991ade41`, alongside Apple's current documentation.

Patchdeck is a browser UI used with touch, mouse, and keyboard. The review adapts
HIG principles to HTML and CSS; it does not claim native iOS or macOS conformance.
System fonts and the existing icon family remain in use. Browser text enlargement
is tested separately from native Dynamic Type.

## Findings and changes

| Finding | Change | HIG reference and section |
| --- | --- | --- |
| Status capsules also acted as update buttons. | Status is read-only; a separate, explicitly labelled Install update button performs the action. The bulk action is prominent; individual actions use a quieter tint. | [Buttons — Style, Content, Role](https://developer.apple.com/design/human-interface-guidelines/buttons), `hig-components-menus/references/buttons.md` |
| Delete, warnings, and available updates shared orange styling. | Removing a configuration uses red; warnings and update status retain their own semantic colors. | [Color — Inclusive color](https://developer.apple.com/design/human-interface-guidelines/color), `hig-foundations/references/color.md` |
| The MQTT switch was named only by its changing state. | A stable Enable MQTT label identifies the setting, with a separate state and explanatory text. | [Toggles — Best practices](https://developer.apple.com/design/human-interface-guidelines/toggles), `hig-components-controls/references/toggles.md` |
| Removing a service had no immediate recovery path. | Each removal offers Undo without a timeout while this settings page stays open. Full configurations are restored, multiple removals can be undone, failed restores can be retried, and an existing ID is checked before restoring. Focus moves to Undo and back to the restored service. | [Undo and redo — Best practices](https://developer.apple.com/design/human-interface-guidelines/undo-and-redo), `hig-patterns/references/undo-and-redo.md` |
| Autosave could discard hidden metadata or race with deletion. | Existing-service edits omit untouched metadata. Saves are serialized per service and finish before deletion. | [Entering data — Best practices](https://developer.apple.com/design/human-interface-guidelines/entering-data), `hig-patterns/references/entering-data.md` |
| Invalid settings were submitted and reported as generic failures. | Required, URL, pattern, and range checks report inline errors with `aria-invalid` and associated descriptions. Invalid values are not submitted. Save confirmation remains visible until another change. | [Accessibility — Cognitive](https://developer.apple.com/design/human-interface-guidelines/accessibility), `hig-foundations/references/accessibility.md` |
| Waiting services showed an indeterminate progress bar. | A queued service shows its queue position; only a running service shows progress, named with the service and current phase. | [Progress indicators — Best practices](https://developer.apple.com/design/human-interface-guidelines/progress-indicators), `hig-components-status/references/progress-indicators.md` |
| Dense nested field borders and decorative badges competed with content. | Grouped forms use simpler field rows, versions appear first, decorative badges are removed, and input boundaries have stronger contrast. | [Layout — Visual hierarchy](https://developer.apple.com/design/human-interface-guidelines/layout), `hig-foundations/references/layout.md` |
| Narrow layouts could overflow with enlarged English or German text. | Cards, action labels, toggle rows, and metric columns reflow at 200% root text size. Touch feedback, safe areas, hover capability checks, and reduced-motion/transparency/contrast support are retained. | [Typography — Supporting Dynamic Type](https://developer.apple.com/design/human-interface-guidelines/typography), `hig-foundations/references/typography.md` |

## Verification

- 73 Python tests; Ruff and Mypy pass.
- JavaScript syntax checks pass.
- `scripts/check-ui.cjs` verifies 32 layouts: two pages, four widths (320, 390,
  768, 1440), two languages, and two color schemes. Narrow layouts also fit
  at 200% root text size.
- Eight Axe scans (both pages, languages, and color schemes) report no detected
  WCAG A/AA violations. This is an automated check, not accessibility certification.
- Browser checks cover stable switch labels, inline validation without invalid
  writes, persistent save feedback, the autosave/delete race, full configuration
  restoration, multiple undo actions, conflicting IDs, failed restore/retry,
  focus restoration, and queued versus running progress.
- The earlier mobile checks also covered a landscape viewport, input text sizes,
  touch target heights, theme persistence, reduced motion, and loading/refresh errors.

## Repeating browser checks

The disposable fixture is available for development checks; no running demo is
required in a deployed installation. Use a fresh fixture process so the simulated
update candidates are available:

```bash
uv run --no-sync python -m patchdeck.demo --host 127.0.0.1 --port 8767
```

In another shell, install optional browser tooling outside the project:

```bash
npm install --prefix /tmp/patchdeck-ui-tools --ignore-scripts --no-audit --no-fund playwright @axe-core/playwright
/tmp/patchdeck-ui-tools/node_modules/.bin/playwright install chromium
NODE_PATH=/tmp/patchdeck-ui-tools/node_modules node scripts/check-ui.cjs http://127.0.0.1:8767
```

The runner refuses to change data unless `/healthz` identifies a demo. It restores
fixture settings and configurations afterward; simulated installed versions reset
when the fixture restarts. Stop the fixture when finished. It is not a public demo.

## Remaining manual checks

Physical iPhone/Android testing is still open: keyboard and input focus, browser
chrome expansion, portrait/landscape safe areas, long-press behavior, pinch zoom,
and touch feel. VoiceOver/Switch Control and real-world lighting checks also
remain manual. Browser emulation and Axe do not replace them.

## Upgrade-cache follow-up — 0.6.3

The original fresh-profile checks did not cover a browser retaining older language
and SVG files across an app upgrade. This was reproduced after a user reported
raw translation keys and a missing back arrow. `scripts/check-asset-cache.cjs`
primes real HTTP cache entries with legacy assets before loading the updated page;
it verifies translated labels, the rendered SVG arrow, and the MQTT control.
The regression passes in Chromium and WebKit after versioning all dependent UI
assets and adding explicit cache headers.

Against the disposable fixture, run:

```bash
NODE_PATH=/tmp/patchdeck-ui-tools/node_modules node scripts/check-asset-cache.cjs http://127.0.0.1:8767
PATCHDECK_BROWSER=webkit NODE_PATH=/tmp/patchdeck-ui-tools/node_modules node scripts/check-asset-cache.cjs http://127.0.0.1:8767
```

The WebKit check requires a matching Playwright WebKit browser and its platform
libraries, or the official matching Playwright container. These engine checks do
not replace the remaining physical-iPhone checks listed above.
