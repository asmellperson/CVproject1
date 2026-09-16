import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

const read = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('all detection page labels derive from the shared department catalog', async () => {
  const permissions = await read('auth/permissions.ts')
  for (const label of ['通用电气事业部', '电子电工事业部', '电气部件事业部', '福达新材院', '伟达子公司', '皓达子公司', '福力达子公司']) assert.ok(permissions.includes(label))
  for (const name of ['IntrusionDetection', 'DoorDetection', 'FaceDetection', 'FaceRecognition', 'PhoneDetection', 'HumanDetection', 'SecurityVlm', 'GuardBehavior']) {
    const source = await read(`sections/${name}Section.tsx`)
    assert.match(source, /DEPARTMENT_LABELS\[department\]/)
    assert.doesNotMatch(source, /departmentLabel="|department === 'electronics_electrician'/)
  }
  const logistics = await read('components/logistics_single_person/LogisticsChannelSection.tsx')
  assert.match(logistics, /DEPARTMENT_LABELS\[department\]/)
})

test('sidebar reuses one capability list for all authorized departments', async () => {
  const source = await read('components/Sidebar.tsx')
  assert.doesNotMatch(source, /sidebarChildMeta\.shared|公共能力|共享能力/)
  assert.match(source, /getAccessibleDepartments\(user\).map/)
  assert.match(source, /label: DEPARTMENT_LABELS\[department\], items: group.items/)
  const nav = await read('lib/nav.ts')
  assert.equal((nav.match(/id: 'logistics-single-person'/g) || []).length, 1)
  assert.match(nav, /items: detectionNavItems/)
})

test('department selection uses the formal department API catalog', async () => {
  for (const name of ['HomeSection', 'UserManagementSection', 'AccessAuditSection']) {
    assert.match(await read(`sections/${name}.tsx`), /useDepartmentCatalog/)
  }
})


test('detection URLs need explicit authorized departments; only overview initializes a default', async () => {
  const permissions = await read('auth/permissions.ts')
  const source = await read('App.tsx')
  const compile = (value) => ts.transpileModule(value, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const catalog = { exports: {} }
  vm.runInNewContext(compile(permissions), catalog)
  const ast = ts.createSourceFile('App.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const initialize = ast.statements.find((node) => ts.isFunctionDeclaration(node) && node.name?.text === 'initializeNavigation')
  assert.ok(initialize)
  const context = { ...catalog.exports }
  vm.runInNewContext(compile(initialize.getText(ast)), context)
  const departments = catalog.exports.DEPARTMENTS
  const pages = catalog.exports.DETECTION_PAGE_IDS
  const users = [
    { role: 'admin', departments: [] },
    { role: 'viewer', departments: [departments[0]] },
    { role: 'viewer', departments: [departments[0], departments[1]] },
  ]
  for (const user of users) {
    for (const page of pages) {
      for (const requested of [null, '', 'ge', 'unknown', '通用电气', ...departments]) {
        const url = new URL('http://test/')
        url.searchParams.set('page', page)
        if (requested !== null) url.searchParams.set('department', requested)
        const navigation = context.initializeNavigation(user, url.searchParams.get('page'), url.searchParams.get('department'))
        const allowed = catalog.exports.getAccessibleDepartments(user).includes(requested)
        assert.equal(navigation.page, allowed ? page : 'overview')
        assert.equal(navigation.department, allowed ? requested : departments[0])
        assert.equal(catalog.exports.resolveDepartment(user, requested), allowed ? requested : null)
      }
    }
  }
  const unassigned = context.initializeNavigation({ role: 'viewer', departments: [] }, 'face-recognition', null)
  assert.equal(unassigned.page, 'overview')
  assert.equal(unassigned.department, null)
  assert.match(source, /isDetectionPage\(page\) \? department : department \?\? currentDepartment/)
  assert.match(source, /window\.addEventListener\('popstate', syncLocation\)/)
})
