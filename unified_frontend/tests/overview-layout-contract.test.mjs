// 文件说明：包含`overview-layout-contract.test` 模块的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)
const homeSection = await readFile(new URL('src/sections/HomeSection.tsx', frontendRoot), 'utf8')
const sidebar = await readFile(new URL('src/components/Sidebar.tsx', frontendRoot), 'utf8')
const topbar = await readFile(new URL('src/components/Topbar.tsx', frontendRoot), 'utf8')
const app = await readFile(new URL('src/App.tsx', frontendRoot), 'utf8')

test('places platform summary before the renamed supervision summary', () => {
  const firstGrid = homeSection.match(/<section className="grid gap-4 lg:grid-cols-\[[\s\S]*?<\/section>/)?.[0] ?? ''
  const secondGrid = homeSection.match(/<section className="grid gap-4 xl:grid-cols-\[[\s\S]*?<\/section>/)?.[0] ?? ''
  const platformSummaryIndex = homeSection.indexOf('平台汇总')
  const supervisionSummaryIndex = homeSection.indexOf('监管概况')

  assert.notEqual(firstGrid, '', 'expected the first overview grid')
  assert.notEqual(secondGrid, '', 'expected the second overview grid')
  assert.notEqual(platformSummaryIndex, -1, 'expected the platform summary module')
  assert.notEqual(supervisionSummaryIndex, -1, 'expected the renamed supervision summary')
  assert.ok(platformSummaryIndex < supervisionSummaryIndex, 'expected platform summary to render before supervision summary')
  assert.match(firstGrid, /平台汇总/)
  assert.match(firstGrid, /onClick=\{openCreateCameraDialog\}/)
  assert.match(firstGrid, /onClick=\{\(\) => openEditCameraDialog\(camera\.aiVisionCamera!\)\}/)
  assert.match(firstGrid, /setCameraToDelete\(camera\.aiVisionCamera!\)/)
  assert.match(homeSection, /onClick=\{handleDeleteCamera\}/)
  assert.doesNotMatch(firstGrid, /监管概况/)
  assert.match(secondGrid, /监管概况/)
  assert.doesNotMatch(secondGrid, /平台汇总/)
  assert.doesNotMatch(homeSection, /统一监管总览/)
})

test('gives every supervision metric tone an explicit dark appearance', () => {
  const metricTile = homeSection.slice(homeSection.indexOf('function MetricTile'), homeSection.indexOf('function StatusBadge'))

  assert.match(metricTile, /blue: \{[\s\S]*?dark:border-blue-900\/60[\s\S]*?rgba\(30,64,175,0\.24\)[\s\S]*?dark:bg-blue-500[\s\S]*?dark:text-blue-300/)
  assert.match(metricTile, /cyan: \{[\s\S]*?dark:border-cyan-900\/60[\s\S]*?rgba\(14,116,144,0\.22\)[\s\S]*?dark:bg-cyan-500[\s\S]*?dark:text-cyan-300/)
  assert.match(metricTile, /amber: \{[\s\S]*?dark:border-amber-900\/60[\s\S]*?rgba\(180,83,9,0\.22\)[\s\S]*?dark:bg-amber-500[\s\S]*?dark:text-amber-300/)
  assert.match(metricTile, /green: \{[\s\S]*?dark:border-emerald-900\/60[\s\S]*?rgba\(6,95,70,0\.22\)[\s\S]*?dark:bg-emerald-500[\s\S]*?dark:text-emerald-300/)
})

test('removes decorative top ribbons from overview cards', () => {
  assert.doesNotMatch(homeSection, /className="h-1\.5 bg-gradient-to-r/)
  assert.doesNotMatch(homeSection, /className=\{cn\('h-1\.5'/)
  assert.doesNotMatch(homeSection, /h-1\.5 bg-gradient-to-r \$\{entry\.accent\}/)
})

test('keeps only the bilingual brand at the top of the sidebar', () => {
  assert.match(sidebar, /福达视觉平台/)
  assert.match(sidebar, /AI Vision Platform/)
  assert.doesNotMatch(sidebar, /src="\/mascot\.png"/)
})

test('moves account controls to the sidebar and removes global status', () => {
  const sidebarElement = app.match(/<Sidebar\b[\s\S]*?\/>/)?.[0] ?? ''

  assert.match(sidebar, /<UserIdentity user=\{user\}/)
  assert.match(sidebar, /修改密码/)
  assert.match(sidebar, /退出/)
  assert.match(sidebar, /aria-label="修改密码"/)
  assert.match(sidebar, /aria-label="退出"/)
  assert.doesNotMatch(sidebar, /部分异常|模块在线|平台连接异常/)
  assert.doesNotMatch(topbar, /修改密码|退出|employee_id|changePassword|logout/)
  assert.notEqual(sidebarElement, '', 'expected the application sidebar')
  assert.doesNotMatch(sidebarElement, /platformStatus=\{platformStatus\}/)
})

test('keeps cameras in one scroller with a responsive two-column grid and hover actions', () => {
  const cameraListStart = homeSection.indexOf('全部摄像头')
  const cameraListEnd = homeSection.indexOf('</section>', cameraListStart)
  const cameraList = homeSection.slice(cameraListStart, cameraListEnd)

  assert.notEqual(cameraListStart, -1, 'expected the all-camera list')
  assert.match(cameraList, /grid-cols-1/)
  assert.match(cameraList, /lg:grid-cols-2/)
  assert.match(cameraList, /\bgroup\b/)
  assert.match(cameraList, /opacity-0/)
  assert.match(cameraList, /group-hover:opacity-100/)
  assert.match(cameraList, /group-focus-within:opacity-100/)
  assert.match(cameraList, /transition-opacity/)
  assert.match(cameraList, /\[@media\(hover:hover\)\]:opacity-0/)
  assert.match(cameraList, /\[@media\(hover:hover\)\]:pointer-events-none/)
  assert.match(cameraList, /group-hover:pointer-events-auto/)
  assert.doesNotMatch(cameraList, /tabIndex=/)
  assert.match(cameraList, /platformCameras\.map\(\(camera\) =>/)
  assert.match(cameraList, /cameraSourceLabel\(camera\.source\)/)
  assert.match(cameraList, /camera\.featureLabels\.map/)
  assert.match(cameraList, /onClick=\{\(\) => openEditCameraDialog\(camera\.aiVisionCamera!\)\}/)
  assert.match(cameraList, /setCameraToDelete\(camera\.aiVisionCamera!\)/)
  assert.match(cameraList, /onClick=\{\(\) => onNavigate\(camera\.pageId!\)\}/)
})

test('aggregates every camera source including logistics and routes overview creation to the selected backend', () => {
  assert.match(homeSection, /source: 'aivision' as const/)
  assert.match(homeSection, /source: 'guard_room' as const/)
  assert.match(homeSection, /source: 'security_vlm' as const/)
  assert.match(homeSection, /已汇总 AiVision、物流通道、保安行为和安检流程摄像头/)
  assert.match(homeSection, /<Label htmlFor="overview-camera-source">目标能力<\/Label>/)
  assert.match(homeSection, /<Label htmlFor="overview-camera-department">所属事业部<\/Label>/)
  assert.match(homeSection, /cameraSource === 'guard_room'[\s\S]*?<Label htmlFor="overview-camera-guard-site">所属保安室<\/Label>/)
  assert.match(homeSection, /<Label htmlFor="overview-camera-fps">FPS<\/Label>/)
  assert.match(homeSection, /FPS 必须是大于等于 1 的整数/)
  assert.match(homeSection, /await createAiVisionCamera\(\{[\s\S]*?shm_name: generatedShmName,[\s\S]*?fps,/)
  assert.match(homeSection, /await updateAiVisionCamera\([^\n]*\{ name, url, fps \}\)/)
  assert.match(homeSection, /await createGuardRoomSiteCamera\(/)
  assert.match(homeSection, /await createSecurityVlmCamera\(/)
  assert.match(homeSection, /await loadCameraInventory\(\)[\s\S]*?setCameraDialogOpen\(false\)/)
})

test('compresses global exception push into a wrapping horizontal bar', () => {
  const pushBar = homeSection.match(/<div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 p-3[\s\S]*?\{visibleStatusCards\.map/)?.[0] ?? ''

  assert.notEqual(pushBar, '', 'expected global exception push settings')
  assert.match(pushBar, /flex flex-wrap items-center/)
  assert.match(pushBar, /bg-slate-50/)
  assert.match(pushBar, /dark:bg-slate-950/)
  assert.match(pushBar, /<Bell[\s\S]*?全局异常推送[\s\S]*?<Switch[\s\S]*?<Input[\s\S]*?<Button/)
  assert.match(pushBar, /min-w-\[220px\]/)
  assert.match(pushBar, /bg-\[#001b43\]/)
  assert.match(pushBar, /aria-label="启用全局异常推送"/)
  assert.match(pushBar, /aria-label="异常重复提醒间隔（分钟）"/)
  assert.match(pushBar, /aria-label="推送群号"/)
})

test('renders the five latest alarms as a severity timeline with navigation', () => {
  const alarmHelpers = homeSection.slice(homeSection.indexOf('const criticalAlarmTypes'), homeSection.indexOf('function departmentLabel'))
  const timeline = homeSection.slice(homeSection.indexOf('最近异常'), homeSection.indexOf('运行状态看板'))

  assert.match(homeSection, /recentAlarms: AlarmEvent\[\]/)
  assert.match(homeSection, /alarmItems\.slice\(0, 5\)/)
  assert.match(alarmHelpers, /criticalAlarmTypes = new Set\(\['blocks', 'guard_absent'\]\)/)
  for (const eventType of ['detect_door', 'detect_phone', 'guard_phone_use', 'guard_prone_sleep', 'security_vlm_non_compliant', 'security_vlm_error']) {
    assert.match(alarmHelpers, new RegExp(`'${eventType}'`))
  }
  assert.match(alarmHelpers, /function getAlarmSeverity[\s\S]*?return 'normal'/)
  assert.match(alarmHelpers, /alarm\.subject_name \|\| alarm\.channel_name \|\| alarm\.camera_name \|\| alarm\.site_name \|\| alarm\.camera_no \|\| '未知位置'/)
  assert.match(timeline, /overview\.recentAlarms\.map/)
  assert.match(timeline, /severity === 'critical' && 'bg-red-500'/)
  assert.match(timeline, /severity === 'warning' && 'bg-amber-400'/)
  assert.match(timeline, /severity === 'normal' && 'bg-slate-400'/)
  assert.match(timeline, /absolute left-\[/)
  assert.match(timeline, /alarm\.event_label \|\| alarm\.event_type/)
  assert.match(timeline, /getAlarmLocation\(alarm\)/)
  assert.match(timeline, /严重报警/)
  assert.match(timeline, /查看全部报警/)
  assert.match(timeline, /onClick=\{\(\) => onNavigate\('alarms'\)\}/)
})

test('removes the bottom feature entry cards from the overview', () => {
  assert.doesNotMatch(homeSection, /ModuleEntryCard/)
  assert.doesNotMatch(homeSection, /进入功能/)
  assert.match(homeSection, /const moduleEntries =/)
  assert.match(homeSection, /getVisibleStatusCards\(visibleModuleEntries\)/)
})
