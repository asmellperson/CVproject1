// 文件说明：包含`user-management-style-contract.test` 模块的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

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
  assert.match(section, /负责范围（可多选）/)
  assert.match(section, /<Checkbox/)
  assert.match(section, /editorForm\.departments\.includes/)
  assert.match(section, /departments: editorForm\.role === 'admin' \? null : editorForm\.departments/)
  assert.doesNotMatch(section, /<select[\s\S]*?id="user-department"/)
})
