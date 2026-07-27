# Security VLM ROI Membership Design

## Goal

Keep full-frame YOLO and ByteTrack tracking, while making it clear and stable
which people participate in each security-inspection ROI.

## Confirmed behavior

- YOLO continues to process the full frame so track IDs remain stable while a
  person approaches or leaves a workstation.
- A person may enter an ROI when either:
  - the bounding-box center is inside the ROI; or
  - the intersection area between the person box and ROI is at least 30% of
    the person-box area.
- An active session uses a looser 10% overlap threshold to keep its people in
  scope near an ROI edge.
- Existing `fingerprint_lost_seconds` remains the temporal exit buffer. No
  second membership timer is added.
- `/video/rule` draws ROI members in green and full-frame tracks outside every
  ROI in gray.

## Architecture

Create a focused `roi_geometry.py` module shared by `session_worker.py` and
`main.py`. It owns coordinate normalization, person-box overlap calculation,
and the center-or-overlap membership predicate.

`PairSessionManager.step()` uses the enter threshold before a session starts
and the hold threshold while a session is active. The MJPEG overlay uses the
enter threshold only, because its purpose is to show who currently counts as
inside an ROI.

The thresholds live under `session` configuration:

```yaml
roi_enter_overlap_ratio: 0.30
roi_hold_overlap_ratio: 0.10
```

Invalid boxes and ROIs are treated as outside. Thresholds are clamped to the
range `[0, 1]`.

## Testing

- Geometry tests cover center inclusion, partial overlap entry, hold-only
  overlap, disjoint boxes, reversed coordinates, and invalid person boxes.
- Session tests verify that inactive ROIs use the enter threshold and active
  sessions use the hold threshold.
- Overlay tests verify green ROI-member boxes and gray outside boxes.
- The complete `security_vlm/tests` suite and Python compilation must pass.

## Scope

No changes to capture, frontend ROI coordinate conversion, YOLO model
parameters, ByteTrack configuration, VLM prompts, or `max_side`.
