import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)

test('access audit is capability-gated in navigation and page routing', async () => {
  const [permissions, navigation, app] = await Promise.all([
    readFile(new URL('src/auth/permissions.ts', frontendRoot), 'utf8'),
    readFile(new URL('src/lib/nav.ts', frontendRoot), 'utf8'),
    readFile(new URL('src/App.tsx', frontendRoot), 'utf8'),
  ])

  assert.match(
    permissions,
    /normalizedPageId === 'access-audit'[\s\S]*view_access_audit === true/,
  )
  assert.match(navigation, /id: 'system'[\s\S]*id: 'access-audit'/)
  assert.match(app, /case 'access-audit':[\s\S]*<AccessAuditSection/)
})

test('access audit client and page do not request sensitive visitor data', async () => {
  const [client, section] = await Promise.all([
    readFile(new URL('src/lib/access-audit.ts', frontendRoot), 'utf8'),
    readFile(new URL('src/sections/AccessAuditSection.tsx', frontendRoot), 'utf8'),
  ])

  assert.match(client, /\/api\/admin\/access-audit/)
  assert.doesNotMatch(client, /password|token|cookie|fingerprint/i)
  assert.match(section, /首次访问/)
  assert.match(section, /最近访问/)
  assert.match(section, /访问次数/)
})
