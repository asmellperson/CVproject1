import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)

const read = (path) => readFile(new URL(path, frontendRoot), 'utf8')

const [types, api, hooks] = await Promise.all([
  read('src/components/logistics_single_person/types.ts').catch(() => ''),
  read('src/components/logistics_single_person/api.ts').catch(() => ''),
  read('src/components/logistics_single_person/useLogisticsChannels.ts').catch(() => ''),
])

test('declares the four isolated logistics features and exact response DTO fields', () => {
  for (const feature of [
    'detect_logistics_single_person',
    'detect_logistics_single_person_electronics_electrician',
    'detect_logistics_single_person_electrical_components',
    'detect_logistics_single_person_precious_metal_recycling',
  ]) assert.match(types, new RegExp(`'${feature}'`))

  for (const field of [
    'feature_name', 'channel_id', 'channel_name', 'duration_seconds',
    'threshold_seconds', 'camera_ids', 'camera_counts', 'camera_states',
    'offending_camera_ids', 'detection_start', 'detection_end',
  ]) assert.match(types, new RegExp(field))
  assert.match(types, /roi_pos: LogisticsCameraRoiPolygon\[\]/)
})

test('uses canonical encoded v2 resource URLs for the complete client', () => {
  assert.match(api, /const logisticsChannelPath/)
  assert.match(api, /encodeURIComponent\(feature\)/)
  assert.match(api, /encodeURIComponent\(String\(channelId\)\)/)
  assert.match(api, /\/v2\/logistics-channels/)
  for (const resource of ['cameras', 'config', 'status', 'frame.jpg', 'alarms', 'statistics']) {
    assert.match(api, new RegExp(resource.replace('.', '\\.')))
  }
  assert.match(api, /apiPost<LogisticsChannelDetail>/)
  assert.match(api, /apiPut<LogisticsChannelDetail>/)
  assert.match(api, /apiDelete<LogisticsChannelOkResponse>/)
})

test('fetches frames with auth, cancellation, and object URL lifecycle helpers', () => {
  assert.match(api, /credentials:\s*'include'/)
  assert.match(api, /signal[,:]/)
  assert.match(api, /aicv:unauthorized/)
  assert.match(api, /URL\.createObjectURL/)
  assert.match(api, /URL\.revokeObjectURL/)
  assert.match(api, /frame\.jpg/)
})

test('provides feature-scoped query keys, invalidation, and settled polling', () => {
  assert.match(api, /logisticsChannelQueryKeys/)
  assert.match(api, /invalidateLogisticsChannelQueries/)
  assert.match(hooks, /useLogisticsChannels\(feature: LogisticsFeatureName/)
  assert.match(hooks, /useLogisticsChannelStatus\(/)
  assert.match(hooks, /STATUS_POLL_INTERVAL_MS = 1000/)
  assert.match(hooks, /SUMMARY_POLL_INTERVAL_MS = 5000/)
  assert.match(hooks, /FRAME_POLL_INTERVAL_MS = 200/)
  assert.match(hooks, /useSerialPoll/)
  assert.match(hooks, /statusState\?\.key === selectionKey/)
  assert.match(hooks, /alarmState\?\.key === selectionKey/)
  assert.match(hooks, /statisticsState\?\.key === selectionKey/)
  assert.match(hooks, /eventState\?\.key === selectionKey/)
})

test('mutations invalidate only the selected logistics feature and channel', () => {
  assert.match(api, /detail:\s*\(feature: LogisticsFeatureName, channelId: number\)/)
  assert.match(api, /logistics-channel-query-invalidated/)
  assert.match(hooks, /event\.detail\.feature !== feature/)
  assert.match(hooks, /event\.detail\.channelId/)
})
