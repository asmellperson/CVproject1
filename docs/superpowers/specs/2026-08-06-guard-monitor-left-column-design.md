# Guard Monitor Left Column Card Placement

## Goal

Move the existing detection-detail and recent-alarm cards into the monitor dashboard's left column, directly below the real-time detection card, without changing their data bindings or behavior.

## Approved layout

The left column order is:

1. Monitoring object
2. Detection controls
3. Real-time detection items
4. Detection details
5. Recent alarms

The stitched-frame video card remains in the right two columns with its intrinsic-ratio rendering unchanged.

## Implementation boundary

- Move the existing card JSX; do not duplicate it or emulate placement with CSS ordering.
- Keep the current `site` visibility condition for detection details and recent alarms.
- Preserve all progress values, alarm fields, API calls, polling, permissions, control handlers, and frame-loading behavior.
- Remove the obsolete lower two-column wrapper after both cards move.

## Verification

- Extend the source contract to assert both cards occur inside the left-column block and before the video card.
- Run all frontend contract tests, production build, lint, and `git diff --check`.
