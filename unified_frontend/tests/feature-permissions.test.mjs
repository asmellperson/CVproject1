import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

const source = readFileSync(new URL('../src/auth/permissions.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const context = { exports: {} }
vm.runInNewContext(compiled, context)
const { hasPageAccess, resolvePage, filterNavGroupsByPermission } = context.exports
const user = {
  role: 'viewer', departments: ['general_electric', 'research_institute'],
  feature_access: { general_electric: ['detect_door'], research_institute: ['detect_phone'] },
}

test('多事业部账号按当前事业部校验功能', () => {
  assert.equal(hasPageAccess(user, 'phone-detection'), true)
  assert.equal(hasPageAccess(user, 'phone-detection', 'general_electric'), false)
  assert.equal(hasPageAccess(user, 'phone-detection', 'research_institute'), true)
  assert.equal(resolvePage(user, 'phone-detection', 'general_electric'), 'overview')
  assert.equal(resolvePage(user, 'phone-detection', 'research_institute'), 'phone-detection')
  assert.equal(resolvePage(user, 'phone-detection', undefined), 'overview')
})

test('权限被收回后旧网址不可进入，公共页面仍可访问', () => {
  const revoked = { ...user, feature_access: {} }
  assert.equal(resolvePage(revoked, 'door-detection', 'general_electric'), 'overview')
  assert.equal(hasPageAccess(revoked, 'alarms'), true)
  assert.equal(hasPageAccess(revoked, 'feature-management'), false)
  assert.equal(hasPageAccess(null, 'door-detection'), false)
})

test('管理员保留维护权限，普通账号不显示功能分配入口', () => {
  const admin = { role: 'admin', departments: ['all'], feature_access: {} }
  assert.equal(resolvePage(admin, 'phone-detection', 'general_electric'), 'phone-detection')
  assert.equal(hasPageAccess(admin, 'feature-management'), true)
  const groups = [{ id: 'system', items: [{ id: 'feature-management' }, { id: 'alarms' }] }]
  assert.equal(filterNavGroupsByPermission(user, groups)[0].items.length, 1)
  assert.equal(filterNavGroupsByPermission(admin, groups)[0].items.length, 2)
})
