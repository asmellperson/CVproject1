// 文件说明：包含`dark-mode-coverage.test` 模块的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const root = new URL('../', import.meta.url)
/**
 * 功能：读取或查询 `read` 对应的`dark-mode-coverage.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（未显式标注）：目标路径
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`readFile`、`URL`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
const read = (path) => readFile(new URL(path, root), 'utf8')
const html = await read('index.html')
const hook = await read('src/hooks/use-theme.ts')

test('defaults first visits to dark before and after React mounts', () => {
  assert.match(html, /const theme = stored === 'light' \|\| stored === 'dark'[\s\S]*\? stored[\s\S]*: 'dark'/)
  assert.doesNotMatch(html, /prefers-color-scheme/)
  assert.match(hook, /if \(typeof window === 'undefined'\) return 'dark'/)
  assert.match(hook, /return 'dark'/)
  assert.doesNotMatch(hook, /prefers-color-scheme/)
})

test('continues to read and persist the existing manual theme choice', () => {
  assert.match(hook, /unified-frontend-theme/)
  assert.match(hook, /stored === 'light' \|\| stored === 'dark'/)
  assert.match(hook, /window\.localStorage\.setItem\(STORAGE_KEY, theme\)/)
  assert.match(hook, /prev === 'dark' \? 'light' : 'dark'/)
})

test('shared monitor views define their own dark surfaces and typography', async () => {
  for (const path of [
    'src/components/guard_room/GuardMonitorUi.tsx',
    'src/components/feature_dashboard/FeatureDashboardMonitorView.tsx',
    'src/components/human_dwell/HumanDwellMonitorView.tsx',
    'src/components/logistics_single_person/LogisticsChannelMonitorView.tsx',
    'src/components/logistics_single_person/LogisticsSinglePersonMonitorView.tsx',
  ]) {
    const source = await read(path)
    assert.match(source, /dark:bg-slate-900/)
    assert.match(source, /dark:border-slate-800/)
    assert.match(source, /dark:text-slate-100/)
    assert.match(source, /dark:text-slate-(300|400)/)
  }
})

test('every detection surface has dark page styling', async () => {
  const files = [
    'GuardBehaviorSection.tsx', 'IntrusionDetectionSection.tsx', 'FaceDetectionSection.tsx',
    'PhoneDetectionSection.tsx', 'DoorDetectionSection.tsx', 'HumanDetectionSection.tsx',
  ]
  for (const file of files) {
    const source = await read(`src/sections/${file}`)
    assert.match(source, /dark:bg-slate-950/)
    assert.match(source, /dark:text-slate-100/)
  }

  const logisticsSection = await read('src/components/logistics_single_person/LogisticsChannelSection.tsx')
  const logisticsMonitor = await read('src/components/logistics_single_person/LogisticsChannelMonitorView.tsx')
  assert.match(logisticsSection, /dark:text-slate-100/)
  assert.match(logisticsMonitor, /dark:bg-slate-900/)
  assert.match(logisticsMonitor, /dark:border-slate-800/)
})

test('detection page titles remain readable on dark surfaces', async () => {
  const header = await read('src/components/detection/DetectionPageHeader.tsx')
  assert.match(header, /<h1[^>]*dark:text-slate-100/)
  for (const [file, title] of [
    ['IntrusionDetectionSection.tsx', '区域入侵检测'],
    ['FaceDetectionSection.tsx', '人脸检测'],
    ['PhoneDetectionSection.tsx', '手机识别检测'],
    ['DoorDetectionSection.tsx', '大门开关检测'],
  ]) {
    const source = await read(`src/sections/${file}`)
    assert.match(source, /DetectionPageHeader/)
    assert.match(source, new RegExp(`title="${title}"`))
  }

  const human = await read('src/sections/HumanDetectionSection.tsx')
  assert.match(human, /title = '人员违规逗留检测'/)
})

test('guard detection rules heading keeps contrast in dark mode', async () => {
  const [source, shared] = await Promise.all([
    read('src/sections/ConfigSection.tsx'),
    read('src/components/detection/DetectionConfigUi.tsx'),
  ])
  assert.match(source, /title="检测参数"/)
  assert.match(source, /tone="emerald"/)
  assert.match(shared, /dark:from-slate-900/)
  assert.match(shared, /dark:to-slate-900/)
  assert.match(shared, /dark:text-slate-100/)
})

test('detection configuration headings remove light gradients in dark mode', async () => {
  const shared = await read('src/components/detection/DetectionConfigUi.tsx')
  assert.match(shared, /dark:from-slate-900/)
  assert.match(shared, /dark:to-slate-900/)
  assert.match(shared, /dark:bg-slate-900/)
  for (const path of [
    'src/sections/HumanDetectionSection.tsx',
    'src/sections/IntrusionDetectionSection.tsx',
    'src/sections/FaceDetectionSection.tsx',
    'src/sections/PhoneDetectionSection.tsx',
    'src/sections/DoorDetectionSection.tsx',
    'src/components/FeatureCameraManager.tsx',
    'src/components/AiVisionRoiEditor.tsx',
    'src/components/AiVisionModelConfig.tsx',
    'src/components/AlarmPushConfig.tsx',
  ]) {
    const source = await read(path)
    assert.match(source, /DetectionConfigCardHeader/, `${path} should use the shared configuration heading`)
  }
})

test('guard and security workflow business cards support dark mode', async () => {
  for (const path of [
    'src/sections/MonitorSection.tsx',
    'src/sections/ConfigSection.tsx',
    'src/sections/SecurityVlmSection.tsx',
    'src/components/security-vlm/SecurityCameraBar.tsx',
  ]) {
    const source = await read(path)
    assert.match(source, /dark:bg-slate-900/)
    assert.match(source, /dark:border-slate-800/)
    assert.match(source, /dark:text-slate-100/)
  }
})

test('remaining routed pages and shared configuration surfaces support dark mode', async () => {
  const files = [
    'src/sections/AlarmsSection.tsx', 'src/sections/StatisticsSection.tsx',
    'src/sections/UserManagementSection.tsx', 'src/sections/AiVisionSection.tsx',
    'src/components/AiVisionMonitor.tsx', 'src/components/FeatureCameraManager.tsx',
    'src/components/AiVisionRoiEditor.tsx', 'src/components/AiVisionModelConfig.tsx',
    'src/components/AiVisionPresetActions.tsx', 'src/components/AlarmPushConfig.tsx',
  ]
  for (const path of files) {
    const source = await read(path)
    assert.match(source, /dark:/)
  }
  const loginCss = await read('src/pages/LoginPage.css')
  assert.match(loginCss, /\.dark \.login-page/)
  assert.match(loginCss, /\.dark \.login-card/)
  assert.match(loginCss, /\.dark \.login-input/)
})

test('fixed navy labels and ranking bars remain visible on dark surfaces', async () => {
  const config = await read('src/sections/ConfigSection.tsx')
  const shared = await read('src/components/detection/DetectionConfigUi.tsx')
  const statistics = await read('src/sections/StatisticsSection.tsx')
  assert.match(config, /text-\[#1a2e55\] dark:text-slate-100/)
  assert.match(shared, /text-\[#0B1226\] dark:text-slate-100/)
  assert.match(statistics, /bg-slate-900 dark:bg-blue-500/)
})

test('every light indigo icon tile uses a dark variant in monitor views', async () => {
  for (const [path, expectedCount] of [
    ['src/components/guard_room/GuardMonitorUi.tsx', 1],
    ['src/sections/MonitorSection.tsx', 1],
    ['src/components/feature_dashboard/FeatureDashboardMonitorView.tsx', 3],
    ['src/components/human_dwell/HumanDwellMonitorView.tsx', 3],
    ['src/components/logistics_single_person/LogisticsSinglePersonMonitorView.tsx', 3],
  ]) {
    const source = await read(path)
    const matches = source.match(/bg-\[#EAF0FE\] text-\[#1B3FA0\] dark:bg-blue-950\/60 dark:text-blue-300/g) || []
    assert.equal(matches.length, expectedCount, path)
  }
})
