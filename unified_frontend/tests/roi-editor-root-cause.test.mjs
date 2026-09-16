import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')

test('ROI editor uses a raw frame and exposes no feature prop', () => {
  const editor = read('src/components/AiVisionRoiEditor.tsx')

  assert.match(editor, /aiVisionFrameUrl\(cameraKey, undefined, nonce\)/)
  assert.doesNotMatch(editor, /feature\?: string/)
})

test('logistics ROI hydration depends on stable IDs instead of polled objects', () => {
  const config = read('src/components/logistics_single_person/LogisticsChannelConfigView.tsx')
  const hydrationCall = config.indexOf('getLogisticsCameraRoi(feature')
  const hydrationStart = config.lastIndexOf('  useEffect(() => {', hydrationCall)
  const hydration = config.slice(
    hydrationStart,
    config.indexOf('  const invalidateMemberships'),
  )

  assert.notEqual(hydrationCall, -1)
  assert.notEqual(hydrationStart, -1)
  assert.match(config, /const selectedChannelDetailId = selectedChannelDetail\?\.id \?\? null/)
  assert.match(hydration, /getLogisticsCameraRoi\(feature, selectedChannelDetailId, selectedCameraId\)/)
  assert.match(hydration, /\[feature, selectedCameraId, selectedChannelDetailId\]/)
  assert.doesNotMatch(hydration, /\[feature, selectedCamera, selectedChannelDetail\]/)
})


test('only the editor draws ROI geometry; monitor views display backend frames', () => {
  for (const path of [
    'components/AiVisionMonitor.tsx',
    'components/human_dwell/HumanDwellMonitorView.tsx',
    'components/feature_dashboard/FeatureDashboardMonitorView.tsx',
    'components/logistics_single_person/LogisticsChannelMonitorView.tsx',
  ]) assert.doesNotMatch(read(`src/${path}`), /<svg|<polygon|roiPolygons|buildAiVisionMonitorOverlay/)
  const editor = read('src/components/AiVisionRoiEditor.tsx')
  assert.match(editor, /image.naturalWidth/)
  assert.match(editor, /image.naturalHeight/)
  assert.match(editor, /pixelsToNormalizedPoints/)
  assert.match(editor, /normalizedPointsToPixels/)
  assert.doesNotMatch(editor, /regionJson|onRegionChange|width: 1920|height: 1080/)
})
