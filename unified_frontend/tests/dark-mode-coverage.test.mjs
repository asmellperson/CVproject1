import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const root = new URL('../', import.meta.url)
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
  for (const [file, title] of [
    ['HumanDetectionSection.tsx', '人员逗留监控与配置入口'],
    ['IntrusionDetectionSection.tsx', '区域入侵检测监控与配置'],
    ['FaceDetectionSection.tsx', '人脸检测监控与配置'],
    ['PhoneDetectionSection.tsx', '手机识别检测监控与配置'],
    ['DoorDetectionSection.tsx', '大门开关检测监控与配置'],
  ]) {
    const source = await read(`src/sections/${file}`)
    const heading = source.match(new RegExp(`<h1 className="([^"]*)">${title}</h1>`))
    assert.ok(heading, `${file} should render its page title as an h1`)
    assert.match(heading[1], /dark:text-slate-100/, `${file} should give its page title a dark-mode color`)
  }
})

test('guard detection rules heading keeps contrast in dark mode', async () => {
  const source = await read('src/sections/ConfigSection.tsx')
  const ruleHeader = [...source.matchAll(/<CardHeader className="([^"]*)">([\s\S]*?)<\/CardHeader>/g)]
    .find(([, , body]) => body.includes('检测规则配置'))
  assert.ok(ruleHeader, 'guard detection rules should render a card heading')
  const title = ruleHeader[2].match(
    /<CardTitle className="([^"]*)">[\s\S]*?检测规则配置[\s\S]*?<\/CardTitle>/,
  )
  assert.ok(title, 'guard detection rules should render its title inside the card heading')
  assert.match(ruleHeader[1], /dark:from-slate-900/)
  assert.match(ruleHeader[1], /dark:to-slate-900/)
  assert.match(title[1], /dark:text-slate-100/)
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
  const statistics = await read('src/sections/StatisticsSection.tsx')
  assert.match(config, /text-\[#10264d\] dark:text-slate-100/)
  assert.match(config, /text-\[#1a2e55\] dark:text-slate-100/)
  assert.match(statistics, /bg-slate-900 dark:bg-blue-500/)
})

test('every light indigo icon tile uses a dark variant in monitor views', async () => {
  for (const [path, expectedCount] of [
    ['src/components/guard_room/GuardMonitorUi.tsx', 1],
    ['src/sections/MonitorSection.tsx', 2],
    ['src/components/feature_dashboard/FeatureDashboardMonitorView.tsx', 3],
    ['src/components/human_dwell/HumanDwellMonitorView.tsx', 3],
    ['src/components/logistics_single_person/LogisticsSinglePersonMonitorView.tsx', 3],
  ]) {
    const source = await read(path)
    const matches = source.match(/bg-\[#EAF0FE\] text-\[#1B3FA0\] dark:bg-blue-950\/60 dark:text-blue-300/g) || []
    assert.equal(matches.length, expectedCount, path)
  }
})
