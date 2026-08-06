# Logistics Single-Person Monitor UI Design

## Goal

Rebuild the logistics single-person detection monitor page with the same visual system as the guard-behavior monitor while preserving every existing configuration request, camera-list binding, frame polling interval, image loading path, frame-size handling, and video playback behavior.

## Scope

The real-time monitor tab receives the new dashboard layout. The configuration tab keeps its existing forms, camera management, ROI editor, model settings, alarm settings, requests, permissions, and handlers. The backend annotations already burned into the JPEG frame—including the region line, its label, count text, and any source timestamp—remain unchanged.

## Page structure

The page uses `#F3F5FA` as its background, `#132C72` as its primary color, white `rounded-2xl` cards with subtle slate borders and shadows, and lucide-react icons.

The header follows the supplied reference image: `物流通道单人检测监控与配置` and an ROI single-person monitoring subtitle on the left, with a rounded segmented `实时监控 / 配置管理` control on the right.

The monitor tab renders:

1. Four statistic cards in `grid-cols-2 lg:grid-cols-4`:
   - Camera status, based on whether a current frame is connected.
   - Current frame person count, based on the new read-only status response.
   - Camera quantity, based on the existing feature-enabled camera list length.
   - Today's alarm count, based on the existing alarms API filtered by local date, selected camera, and `detect_logistics_single_person` event type.
2. A `lg:grid-cols-3` dashboard body:
   - Left column: monitoring-object card, decision-guide card, then real-time-event timeline.
   - Right two columns: the video card.

The monitoring-object card moves the existing camera select and refresh action out of the video header. The controls keep the same state, selection callback, disabled conditions, and `refreshCameras` handler.

The left column includes a decision-guide card between the monitoring-object card and the real-time event timeline, matching the supplied reference page. It explains the existing rule without changing it:

- Exactly one person in the ROI is normal and uses emerald styling.
- Zero people in the ROI is an empty-area abnormal state and uses rose styling.
- Two or more people in the ROI is a multiple-person abnormal state and uses rose styling.
- The existing empty and multiple grace-period configuration still controls when the backend emits a formal alarm.

## Read-only runtime status

The current frontend receives only a JPEG and frame dimensions; it has no machine-readable person count. Add a read-only AiVision compatibility endpoint:

```text
GET /api/aivision/cameras/{camera_key}/features/detect_logistics_single_person/status
```

The response contains:

```json
{
  "camera_key": "cam1",
  "feature": "detect_logistics_single_person",
  "online": true,
  "count": 1,
  "alarm": false,
  "reason": "normal",
  "updated_at": "2026-08-06T10:40:46+08:00"
}
```

The logistics consumer records its latest aggregate result after each completed inference. `count` is the sum of known ROI person counts. If no ROI has a known result, `count` is `null`; an unknown value is not treated as an alarm. `alarm` is true when any ROI's existing decision is alarming. This snapshot is display-only and does not alter alarm dispatch, inference, thresholds, frame drawing, or configuration.

The orchestrator exposes a read-only lookup for a consumer snapshot. The compatibility route returns a neutral offline/unknown payload when the consumer or camera has no fresh status instead of changing existing frame behavior.

## Alarm and event data flow

The frontend continues using the existing alarm request. It polls logistics alarms and derives today's selected-camera count from `created_at`, `camera_no`, and `event_type` without changing the alarm API.

The real-time event timeline is page-local presentation state derived from status transitions:

- A transition to exactly one person inserts a gray `ROI 内人数恢复正常：1 人` record.
- A transition to zero people inserts a red `ROI 内无人异常：0 人` record.
- A transition to two-or-more people inserts a red `ROI 内多人异常：X 人` record.
- Repeated polls with the same semantic state do not add duplicate records.
- Unknown count values add no event.
- The list is capped to a small recent set and resets when the selected camera changes or the page reloads.

This timeline is not a new business record store and does not modify alarm persistence.

## Video presentation

The existing `AiVisionMonitor` remains responsible for camera loading, selection, page-visibility behavior, frame requests, blob URL cleanup, request timeouts, image-size headers, and the current `<img>` callbacks. It gains an opt-in logistics dashboard presentation; the default presentation for all other feature pages stays unchanged.

The logistics dashboard presentation renders:

- Header title `物流通道单人检测监控` and selected camera number/name.
- Current-person, configured-FPS, and LIVE pills.
- Current-person state is emerald only when count is exactly one; zero or multiple is rose; unknown is neutral.
- Video top-left glass pills: `实时检测`, camera online state, frame person count, and an additional red `人员异常告警` pill during an alarm.
- A subtle vignette that does not intercept pointer events.

The existing frame annotations remain embedded and unchanged. No frontend replacement line, label, debug-text removal, or duplicate timestamp is rendered.

## Component boundaries

- `LogisticsSinglePersonDetectionSection.tsx`: page header, segmented tabs, and existing configuration logic.
- `AiVisionMonitor.tsx`: existing camera/frame lifecycle plus an opt-in logistics presentation hook-up; default mode is unchanged.
- A focused logistics monitor presentation component: statistic cards, monitoring-object card, event timeline, video chrome, and alarm coloring. It receives prepared state and callbacks and performs no camera or frame requests.
- AiVision consumer/orchestrator/compat route: read-only current detection snapshot.
- Frontend API/type layer: typed status request only.

## Error and loading states

- No selected camera: keep the existing instruction to configure a camera.
- Frame unavailable: camera card and LIVE presentation show offline while the existing message remains visible.
- Status unavailable or stale: person count displays `--`, uses neutral styling, and does not generate an event.
- Alarm request failure: retain the previous successful alarm total/list and avoid fabricating zeroes.

## Verification

- Backend unit tests cover status aggregation, unknown counts, multi-ROI alarm aggregation, and read-only route output.
- Frontend contract tests verify the dashboard layout, metric bindings, status polling, alarm color rules, event transition de-duplication, and unchanged frame-request/playback strings.
- Run focused backend tests, all frontend contract tests, TypeScript/Vite production build, lint, and `git diff --check`.
- Confirm configuration-management JSX and request handlers remain unchanged and no preview server is started.
