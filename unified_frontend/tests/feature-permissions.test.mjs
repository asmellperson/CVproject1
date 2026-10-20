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

test('非法闯闸功能按当前事业部分配，权限收回后立即拒绝入口', () => {
  const granted = { ...user, feature_access: { general_electric: ['tailgating'], research_institute: [] } }
  assert.equal(resolvePage(granted, 'tailgating-detection', 'general_electric'), 'tailgating-detection')
  assert.equal(resolvePage(granted, 'tailgating-detection', 'research_institute'), 'overview')
  assert.equal(resolvePage({ ...granted, feature_access: {} }, 'tailgating-detection', 'general_electric'), 'overview')
})

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

test('管理员未分配检测功能时仍可配置分配，普通账号没有管理入口', () => {
  const admin = { role: 'admin', departments: ['all'], feature_access: {} }
  assert.equal(resolvePage(admin, 'phone-detection', 'general_electric'), 'overview')
  assert.equal(hasPageAccess(admin, 'feature-management'), true)
  const groups = [{ id: 'system', items: [{ id: 'feature-management' }, { id: 'alarms' }] }]
  assert.equal(filterNavGroupsByPermission(user, groups)[0].items.length, 1)
  assert.equal(filterNavGroupsByPermission(admin, groups)[0].items.length, 2)
})

for (const role of ['admin', 'viewer']) {
  test(`${role} 新分配的功能显示，收回后隐藏且旧网址不可访问`, () => {
    const account = { ...user, role, departments: role === 'admin' ? ['all'] : user.departments }
    const groups = [{ id: 'modules', items: [{ id: 'phone-detection' }, { id: 'door-detection' }] }]
    for (const enabled of [false, true, false]) {
      const updated = { ...account, feature_access: { general_electric: enabled ? ['detect_phone'] : [] } }
      assert.equal(hasPageAccess(updated, 'phone-detection', 'general_electric'), enabled)
      assert.equal(hasPageAccess(updated, 'phone-detection', 'research_institute'), false)
      assert.equal(resolvePage(updated, 'phone-detection', 'general_electric'), enabled ? 'phone-detection' : 'overview')
      assert.equal(filterNavGroupsByPermission(updated, groups).length, Number(enabled))
    }
  })
}
