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
  assert.match(firstGrid, /onClick=\{\(\) => openEditCameraDialog\(camera\)\}/)
  assert.match(firstGrid, /setCameraToDelete\(camera\)/)
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

  assert.match(sidebar, /user\.employee_id/)
  assert.match(sidebar, /user\.name/)
  assert.match(sidebar, /修改密码/)
  assert.match(sidebar, /退出/)
  assert.match(sidebar, /aria-label="修改密码"/)
  assert.match(sidebar, /aria-label="退出"/)
  assert.doesNotMatch(sidebar, /部分异常|模块在线|平台连接异常/)
  assert.doesNotMatch(topbar, /修改密码|退出|employee_id|changePassword|logout/)
  assert.notEqual(sidebarElement, '', 'expected the application sidebar')
  assert.doesNotMatch(sidebarElement, /platformStatus=\{platformStatus\}/)
})
