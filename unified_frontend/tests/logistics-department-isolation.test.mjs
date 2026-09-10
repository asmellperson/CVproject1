import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import test from 'node:test'
import ts from 'typescript'

const read = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')
const moduleUrl = (source) => `data:text/javascript;base64,${Buffer.from(ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText).toString('base64')}`
const departments = ['general_electric', 'electronics_electrician', 'electrical_components', 'precious_metal_recycling']
const pageFor = (department) => `logistics-single-person-${department.replaceAll('_', '-')}`
const feature = 'detect_logistics_single_person'
const permissionsUrl = moduleUrl(await read('auth/permissions.ts'))
const { hasPageAccess, getAccessibleAlarmEventTypes } = await import(permissionsUrl)
const iconsUrl = pathToFileURL(createRequire(import.meta.url).resolve('lucide-react')).href
const navUrl = moduleUrl((await read('lib/nav.ts')).replaceAll("'lucide-react'", JSON.stringify(iconsUrl)))
const sidebarSource = await read('components/Sidebar.tsx')
const sidebarAst = ts.createSourceFile('Sidebar.tsx', sidebarSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const groupSource = sidebarAst.statements.filter((node) => (
  ts.isFunctionDeclaration(node) && node.name?.text === 'buildSidebarNavGroups'
) || (
  ts.isVariableStatement(node) && node.declarationList.declarations.some((decl) => decl.name.getText(sidebarAst) === 'adminModuleGroups')
)).map((node) => node.getText(sidebarAst)).join('\n')
const { buildSidebarNavGroups } = await import(moduleUrl(`
  import { departmentPermissions, filterNavGroupsByPermission, getUserDepartments } from '${permissionsUrl}'
  import { navGroups } from '${navUrl}'
  ${groupSource}
  export { buildSidebarNavGroups }
`))
const user = (assigned, role = 'viewer') => ({ employee_id: 'test', name: 'test', role, departments: assigned })

for (const department of departments) {
  test(`${department} sees only its own logistics entry and keeps the canonical alarm type`, () => {
    const viewer = user([department])
    assert.deepEqual(departments.filter((item) => hasPageAccess(viewer, pageFor(item))), [department])
    const modules = buildSidebarNavGroups(viewer, false).find((group) => group.id === 'modules')
    assert.deepEqual(modules.items.filter((item) => item.id.startsWith('logistics-single-person')).map((item) => item.id), [pageFor(department)])
    assert.deepEqual(getAccessibleAlarmEventTypes(viewer).filter((item) => item.startsWith(feature)), [feature])
  })
}

for (const [name, viewer, expected] of [
  ['admin', user(['all'], 'admin'), departments],
  ['all departments', user(['all']), departments],
  ['multiple departments', user(departments.slice(0, 2)), departments.slice(0, 2)],
]) {
  test(`${name} gets logistics inside each authorized department, never shared abilities`, () => {
    const modules = buildSidebarNavGroups(viewer, viewer.role === 'admin').find((group) => group.id === 'modules')
    const logisticsGroups = modules.children.filter((group) => group.items.some((item) => item.id.startsWith('logistics-single-person')))
    assert.deepEqual(logisticsGroups.map((group) => group.id), expected)
    for (const group of logisticsGroups) {
      assert.deepEqual(group.items.filter((item) => item.id.startsWith('logistics-single-person')).map((item) => item.id), [pageFor(group.id)])
    }
    assert.ok(!modules.children.find((group) => group.id === 'shared')?.items.some((item) => item.id.startsWith('logistics-single-person')))
  })
}

test('unassigned departments cannot open a logistics page', () => {
  for (const assigned of [[], ['research_institute'], ['haoda_company']]) {
    assert.ok(departments.every((department) => !hasPageAccess(user(assigned), pageFor(department))))
  }
})

test('API list and inventory transmit the selected department; overview inventory remains authorized aggregate', async () => {
  const stubUrl = moduleUrl(`
    export const apiGet = async (path, init) => ({ path, init })
    export const apiPost = apiGet, apiPut = apiGet, apiPatch = apiGet, apiDelete = apiGet, apiUrl = (path) => path
  `)
  const api = await import(moduleUrl((await read('components/logistics_single_person/api.ts')).replace("'@/lib/api'", JSON.stringify(stubUrl))))
  const init = { signal: new AbortController().signal }
  for (const department of departments) {
    const result = await api.listLogisticsChannels(feature, department, init)
    assert.equal(result.path, `/logistics-channels/${feature}?department=${department}`)
    assert.equal(result.init, init)
    assert.equal((await api.getLogisticsCameraInventory(department)).path, `/logistics-channels/inventory?department=${department}`)
  }
  assert.equal((await api.getLogisticsCameraInventory()).path, '/logistics-channels/inventory')
  assert.notDeepEqual(api.logisticsChannelQueryKeys.list(feature, departments[0]), api.logisticsChannelQueryKeys.list(feature, departments[1]))
})

test('department switch rejects old list and detail results even when feature, id and generation match', async () => {
  const { isCurrentChannelListRequest, isCurrentChannelDetailRequest } = await import(moduleUrl(await read('components/logistics_single_person/channelRequestState.ts')))
  const old = { feature, department: departments[0], generation: 4, channelId: 1 }
  const current = { ...old, department: departments[1] }
  assert.equal(isCurrentChannelListRequest(old, current), false)
  assert.equal(isCurrentChannelDetailRequest(old, current), false)
  assert.equal(isCurrentChannelListRequest(current, current), true)
  assert.equal(isCurrentChannelDetailRequest(current, current), true)
})

test('each route passes department to one shared page and resets the whole page on department change', async () => {
  const app = await read('App.tsx')
  for (const department of departments) {
    assert.ok(app.includes(`case '${pageFor(department)}':\n        return <LogisticsSinglePersonDetectionSection department="${department}" />`))
  }
  const section = await read('sections/LogisticsSinglePersonDetectionSection.tsx')
  assert.match(section, /key=\{department\}/)
  assert.match(section, /department=\{department\}/)
  const config = await read('components/logistics_single_person/LogisticsChannelConfigView.tsx')
  assert.match(config, /getAiVisionCameras\(department\)/)
  assert.match(config, /createLogisticsChannel\(feature, \{ name, department \}\)/)
  assert.doesNotMatch(config, /createDialog\.department|change-department/)
  const home = await read('sections/HomeSection.tsx')
  assert.match(home, /logisticsPageByDepartment\[camera.department as LogisticsDepartment\]/)
  assert.doesNotMatch(home, /logisticsPageByFeature/)
})

test('logistics overview cards count only cameras and online states in their department', async () => {
  const { getLoadedAiVisionFeatureCounts } = await import(moduleUrl(await read('sections/homeCameraCounts.ts')))
  const cameras = [
    { department: departments[0], enabled: true, functions: { [feature]: true }, logisticsOnline: false },
    { department: departments[1], enabled: true, functions: { [feature]: true }, logisticsOnline: true },
    { department: departments[1], enabled: false, functions: { [feature]: true }, logisticsOnline: false },
    { department: null, enabled: true, functions: { [feature]: true }, logisticsOnline: true },
  ]
  assert.deepEqual(getLoadedAiVisionFeatureCounts(cameras, true, departments[0])[feature], { cameraCount: 1, enabledCameraCount: 1, onlineCameraCount: 0 })
  assert.deepEqual(getLoadedAiVisionFeatureCounts(cameras, true, departments[1])[feature], { cameraCount: 2, enabledCameraCount: 1, onlineCameraCount: 1 })
  assert.deepEqual(getLoadedAiVisionFeatureCounts(cameras, true, departments[2])[feature], { cameraCount: 0, enabledCameraCount: 0, onlineCameraCount: 0 })
})
