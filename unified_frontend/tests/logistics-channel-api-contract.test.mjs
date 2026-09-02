// 文件说明：包含接口访问的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)

/**
 * 功能：读取或查询 `read` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（未显式标注）：目标路径
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`readFile`、`URL`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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
    'offending_camera_ids', 'detection_start', 'detection_end', 'confidence_threshold',
  ]) assert.match(types, new RegExp(field))
  assert.match(types, /roi_pos: LogisticsCameraRoiPolygon\[\]/)
  assert.match(types, /type LogisticsCameraInventoryItem/)
  assert.match(types, /memberships: LogisticsCameraInventoryMembership\[\]/)
})

test('uses canonical encoded API resource URLs for the complete client', () => {
  assert.match(api, /const logisticsChannelPath/)
  assert.match(api, /encodeURIComponent\(feature\)/)
  assert.match(api, /encodeURIComponent\(String\(channelId\)\)/)
  assert.match(api, /\/logistics-channels/)
  for (const resource of ['cameras', 'config', 'status', 'frame.jpg', 'alarms', 'statistics']) {
    assert.match(api, new RegExp(resource.replace('.', '\\.')))
  }
  assert.match(api, /apiPost<LogisticsChannelDetail>/)
  assert.match(api, /apiPut<LogisticsChannelDetail>/)
  assert.match(api, /apiDelete<LogisticsChannelOkResponse>/)
  assert.match(api, /memberCameraConfigPath/)
  assert.match(api, /getLogisticsCameraInventory/)
  assert.match(api, /\/logistics-channels\/inventory/)
  assert.match(api, /cameraId: number/)
  assert.doesNotMatch(api, /cameraKey: string \| number/)
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
  assert.equal([...hooks.matchAll(/useSerialPoll\(/g)].length, 5)
  assert.match(hooks, /restartKey:/)
  assert.match(hooks, /useReducer/)
  assert.doesNotMatch(hooks, /window\.setTimeout/)
  assert.doesNotMatch(hooks, /void\s+(?:refresh|load)/)
  assert.match(hooks, /selectionToken = useMemo/)
  assert.match(hooks, /statusState\?\.selection === selectionToken/)
  assert.match(hooks, /alarmState\?\.selection === selectionToken/)
  assert.match(hooks, /statisticsState\?\.selection === selectionToken/)
  assert.match(hooks, /eventState\?\.selection === selectionToken/)
  assert.match(hooks, /frameUrlState\?\.selection === selectionToken/)
  assert.match(hooks, /statusErrorState/)
  assert.match(hooks, /summaryErrorState/)
  assert.match(hooks, /frameErrorState/)
})

test('mutations stay feature-scoped and cross-channel moves invalidate source and target', () => {
  assert.match(api, /detail:\s*\(feature: LogisticsFeatureName, channelId: number\)/)
  assert.match(api, /logistics-channel-query-invalidated/)
  assert.match(hooks, /event\.detail\.feature !== feature/)
  assert.match(hooks, /event\.detail\.channelId/)
  const moveStart = api.indexOf('export const moveLogisticsChannelCamera')
  const moveEnd = api.indexOf('export const reorderLogisticsChannelCameras')
  const moveSource = api.slice(moveStart, moveEnd)
  assert.match(moveSource, /feature,\s*\)/)
  assert.doesNotMatch(moveSource, /feature,\s*channelId,\s*\)/)
})
