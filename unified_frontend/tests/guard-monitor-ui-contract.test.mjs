import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)

async function readIfPresent(path) {
  try {
    return await readFile(new URL(path, frontendRoot), 'utf8')
  } catch (error) {
    if (error && typeof error === 'object' && error.code === 'ENOENT') return ''
    throw error
  }
}

const guardPage = await readIfPresent('src/sections/GuardBehaviorSection.tsx')
const monitor = await readIfPresent('src/sections/MonitorSection.tsx')
const ui = await readIfPresent('src/components/guard_room/GuardMonitorUi.tsx')

test('renders the approved heading, segmented tabs, and dashboard grid', () => {
  assert.match(guardPage, /通用电气保安行为规范监控与配置/)
  assert.match(guardPage, /行为分析监控面板/)
  assert.match(guardPage, /rounded-full border border-slate-200\/70 bg-white p-1/)
  assert.match(guardPage, /data-\[state=active\]:bg-\[#132C72\]/)
  assert.match(monitor, /grid grid-cols-2 gap-4 lg:grid-cols-4/)
  assert.match(monitor, /grid gap-5 lg:grid-cols-3/)
  assert.match(monitor, /lg:col-span-2/)
  assert.match(monitor, /监控对象/)
  assert.match(monitor, /检测控制/)
  assert.match(monitor, /实时检测项/)
})

test('keeps existing status fields bound to the refreshed UI', () => {
  assert.match(monitor, /status\?\.counts\.persons/)
  assert.match(monitor, /status\?\.metrics\.person_confidence/)
  assert.match(monitor, /status\?\.fps/)
  assert.match(monitor, /status\?\.decisions\.phone_use/)
  assert.match(monitor, /status\?\.decisions\.prone_sleep/)
  assert.match(monitor, /status\?\.decisions\.vehicle_unattended/)
  assert.match(monitor, /const cameraOnline = Boolean\(site && frameSrc\)/)
  assert.doesNotMatch(monitor, /RTSP 流正常|RTSP 流中断|车辆入侵检测/)
  assert.match(monitor, /推理延迟约 154ms/)
})

test('preserves the intrinsic ratio of the stitched camera frame', () => {
  assert.match(monitor, /className=\{[^}]*'block h-auto w-full saturate-\[\.85\][^']*'/)
  assert.doesNotMatch(monitor, /aspect-video|object-cover/)
  assert.match(monitor, /检测功能已关闭/)
  assert.match(monitor, /点击左侧『检测开启』恢复行为分析/)
  assert.match(monitor, /1080P · H\.265/)
  assert.doesNotMatch(monitor, /preserveAspectRatio|vehicle_roi/)
})

test('extracts repeated display elements without moving business logic', () => {
  assert.match(ui, /export function GuardMonitorStatCard/)
  assert.match(ui, /export function GuardDetectionStatusRow/)
  assert.match(ui, /export function GuardVideoStatusPill/)
  assert.doesNotMatch(ui, /fetch\(|getGuardRoomSiteStatus|startGuardRoomSiteRuntime|stopGuardRoomSiteRuntime/)

  assert.match(monitor, /getGuardRoomSiteStatus\(site\.id, department\)/)
  assert.match(monitor, /startGuardRoomSiteRuntime\(site\.id\)/)
  assert.match(monitor, /stopGuardRoomSiteRuntime\(site\.id\)/)
  assert.match(monitor, /guardRoomSiteFrameUrl\(site\.id, department\)/)
  assert.match(monitor, /window\.setInterval\(fetchStatus, POLL_MS\)/)
})

test('places details and alarms below real-time items in the left column', () => {
  const leftColumn = monitor.indexOf('<div className="space-y-5">')
  const realtimeItems = monitor.indexOf('实时检测项', leftColumn)
  const details = monitor.indexOf('检测详情', realtimeItems)
  const recentAlarm = monitor.indexOf('最近报警', details)
  const video = monitor.indexOf("'overflow-hidden lg:col-span-2'", recentAlarm)

  assert.ok(leftColumn >= 0)
  assert.ok(leftColumn < realtimeItems)
  assert.ok(realtimeItems < details)
  assert.ok(details < recentAlarm)
  assert.ok(recentAlarm < video)
  assert.doesNotMatch(monitor, /<section className="grid gap-5 lg:grid-cols-2">/)
})
