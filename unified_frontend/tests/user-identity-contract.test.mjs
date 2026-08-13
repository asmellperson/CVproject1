import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)
const identity = await readFile(new URL('src/components/UserIdentity.tsx', frontendRoot), 'utf8')
const topbar = await readFile(new URL('src/components/Topbar.tsx', frontendRoot), 'utf8')
const sidebar = await readFile(new URL('src/components/Sidebar.tsx', frontendRoot), 'utf8')

test('derives a gradient text avatar from the current user name', () => {
  assert.match(identity, /user\.name\.slice\(-1\)/)
  assert.match(identity, /h-9 w-9/)
  assert.match(identity, /rounded-full/)
  assert.match(identity, /bg-gradient-to-br/)
  assert.match(identity, /from-cyan-500/)
  assert.match(identity, /to-indigo-600/)
  assert.match(identity, /user-identity-avatar/)
  assert.match(identity, /items-center/)
  assert.match(identity, /justify-center/)
  assert.match(identity, /text-white/)
  assert.doesNotMatch(identity, /<img\b/)
})

test('shows current user details without changing the auth data source', () => {
  assert.match(identity, /user\.name/)
  assert.match(identity, /user\.role/)
  assert.match(identity, /user\.employee_id/)
  assert.doesNotMatch(identity, /fetch\(/)
})

test('reuses the user identity in the topbar and sidebar footer', () => {
  assert.match(topbar, /<UserIdentity[\s\S]*?user=\{user\}/)
  assert.match(sidebar, /<UserIdentity user=\{user\}/)
})
