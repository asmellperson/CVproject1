import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')

test('shared logistics section owns channel selection and polled composite frame state', () => {
  const section = read('src/components/logistics_single_person/LogisticsChannelSection.tsx')
  const monitor = read('src/components/logistics_single_person/LogisticsChannelMonitorView.tsx')

  assert.match(section, /LogisticsChannelMonitorView/)
  assert.match(section, /useLogisticsChannels/)
  assert.match(section, /useLogisticsChannelStatus/)
  assert.match(monitor, /物流通道/)
  assert.match(monitor, /今日通道告警/)
  assert.match(monitor, /结果过期/)
  assert.match(monitor, /等待检测结果/)
  assert.match(monitor, /camera\.updated_at/)
  assert.match(monitor, /暂无更新时间/)
  assert.match(monitor, /Number\.isFinite/)
  assert.match(monitor, /frameUrl/)
  assert.doesNotMatch(monitor, /camera_id.*frame/i)
})

test('shared channel configuration covers channel, members, schedule and per-camera ROI', () => {
  const config = read('src/components/logistics_single_person/LogisticsChannelConfigView.tsx')

  assert.match(config, /新增物流通道/)
  assert.match(config, /绑定已有摄像头/)
  assert.match(config, /新建摄像头并绑定/)
  assert.match(config, /最多 9 路/)
  assert.match(config, /上移/)
  assert.match(config, /下移/)
  assert.match(config, /逐路 ROI/)
  assert.match(config, /每日检测开始时间/)
  assert.match(config, /每日检测结束时间/)
  assert.match(config, /无人持续时间/)
  assert.match(config, /多人持续时间/)
  assert.match(config, /AiVisionRoiEditor/)
  assert.match(config, /getLogisticsCameraConfig/)
  assert.match(config, /updateLogisticsCameraConfig/)
  assert.match(config, /isAdmin/)
  assert.match(config, /disabled=\{!isAdmin/)
})

test('all logistics mutations use the typed channel API rather than camera-id config routes', () => {
  const config = read('src/components/logistics_single_person/LogisticsChannelConfigView.tsx')
  for (const operation of [
    'createLogisticsChannel',
    'updateLogisticsChannel',
    'deleteLogisticsChannel',
    'addLogisticsChannelCamera',
    'moveLogisticsChannelCamera',
    'reorderLogisticsChannelCameras',
    'removeLogisticsChannelCamera',
    'updateLogisticsChannelConfig',
  ]) assert.match(config, new RegExp(operation))

  assert.doesNotMatch(config, /\/configs\/\$\{[^}]*camera_id/)
})
