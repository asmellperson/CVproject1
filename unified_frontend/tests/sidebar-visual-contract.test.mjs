import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)
const [sidebar, styles, app] = await Promise.all([
  readFile(new URL('src/components/Sidebar.tsx', frontendRoot), 'utf8'),
  readFile(new URL('src/index.css', frontendRoot), 'utf8'),
  readFile(new URL('src/App.tsx', frontendRoot), 'utf8'),
])

test('renders the space-tech sidebar structure with live status and accessible compact labels', () => {
  assert.match(app, /DEFAULT_SIDEBAR_WIDTH = 272/)
  assert.match(app, /COLLAPSED_SIDEBAR_WIDTH = 84/)
  assert.match(sidebar, /sidebar-status-bar/)
  assert.match(sidebar, /monitoringCount/)
  assert.match(sidebar, /todayAlarmCount/)
  assert.match(sidebar, /TooltipContent side="right"/)
  assert.match(sidebar, /aria-current=\{active \? 'page'/)
})

test('keeps department colors, aurora, rainbow selection, user card, and reduced-motion fallback', () => {
  for (const token of ['cyan', 'yellow', 'purple', 'gold', 'green', 'blue', 'red', 'magenta', 'teal', 'orange']) {
    assert.match(sidebar, new RegExp(`${token}:`))
  }
  assert.match(styles, /#05060f/)
  assert.match(styles, /sidebar-aurora-drift/)
  assert.match(styles, /sidebar-rainbow-border/)
  assert.match(styles, /sidebar-avatar-ring/)
  assert.match(styles, /sidebar-user-card/)
  assert.match(styles, /prefers-reduced-motion: reduce/)
})
