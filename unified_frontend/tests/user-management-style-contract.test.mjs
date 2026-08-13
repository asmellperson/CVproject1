import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)

test('user management uses the compact visual identity and preserves all actions', async () => {
  const section = await readFile(
    new URL('src/sections/UserManagementSection.tsx', frontendRoot),
    'utf8',
  )

  assert.match(section, /getAvatarLabel\(item\.name\)/)
  assert.match(section, /bg-gradient-to-br from-cyan-400 via-sky-500 to-violet-500/)
  assert.match(section, /bg-gradient-to-r from-cyan-500 to-blue-600/)
  assert.match(section, /aria-label={`编辑 \$\{item\.name\}`}/)
  assert.match(section, /aria-label={`重置 \$\{item\.name\} 的密码`}/)
  assert.match(section, /aria-label={`删除 \$\{item\.name\}`}/)
  assert.match(section, /void toggleEnabled\(item\)/)
})
