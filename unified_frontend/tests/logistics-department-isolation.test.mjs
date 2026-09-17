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
const feature = 'detect_logistics_single_person'
const permissionsUrl = moduleUrl(await read('auth/permissions.ts'))
const { DEPARTMENTS: departments, DETECTION_PAGE_IDS, hasPageAccess, getAccessibleAlarmEventTypes } = await import(permissionsUrl)
const iconsUrl = pathToFileURL(createRequire(import.meta.url).resolve('lucide-react')).href
const navUrl = moduleUrl((await read('lib/nav.ts')).replaceAll("'lucide-react'", JSON.stringify(iconsUrl)))
const sidebarSource = await read('components/Sidebar.tsx')
const sidebarAst = ts.createSourceFile('Sidebar.tsx', sidebarSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const groupSource = sidebarAst.statements.filter((node) => (
  ts.isFunctionDeclaration(node) && node.name?.text === 'buildSidebarNavGroups'
)).map((node) => node.getText(sidebarAst)).join('\n')
const { buildSidebarNavGroups } = await import(moduleUrl(`
  import { DEPARTMENT_LABELS, filterNavGroupsByPermission, getAccessibleDepartments } from '${permissionsUrl}'
  import { navGroups } from '${navUrl}'
  ${groupSource}
`))
const user = (assigned, role = 'viewer') => ({ employee_id: 'test', name: 'test', role, departments: assigned })

for (const department of departments) {
  test(`${department} has all nine abilities within its own department group`, () => {
    const viewer = user([department])
    assert.ok(DETECTION_PAGE_IDS.every((page) => hasPageAccess(viewer, page)))
    const modules = buildSidebarNavGroups(viewer).find((group) => group.id === 'modules')
    assert.deepEqual(modules.items, [])
    assert.deepEqual(modules.children.map((group) => group.department), [department])
    assert.deepEqual(modules.children[0].items.map((item) => item.id), DETECTION_PAGE_IDS)
    assert.ok(getAccessibleAlarmEventTypes(viewer).includes(feature))
    assert.ok(getAccessibleAlarmEventTypes(viewer).includes('recognize_face'))
  })
}
for (const [name, viewer, expected] of [
  ['admin', user([], 'admin'), departments],
  ['explicit-all-departments', user(departments), departments],
  ['multiple', user(departments.slice(0, 2)), departments.slice(0, 2)],
]) {
  test(`${name} repeats the same nine NavItems for authorized departments only`, () => {
    const modules = buildSidebarNavGroups(viewer).find((group) => group.id === 'modules')
    assert.deepEqual(modules.children.map((group) => group.department), expected)
    for (const group of modules.children) assert.deepEqual(group.items.map((item) => item.id), DETECTION_PAGE_IDS)
  })
}
test('viewer without a registered department cannot enter detection pages', () => {
  for (const assigned of [[], ['unknown']]) assert.ok(DETECTION_PAGE_IDS.every((page) => !hasPageAccess(user(assigned), page)))
})

test('API list and inventory transmit the selected department; overview uses the selected department', async () => {
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
  assert.equal((app.match(/case 'logistics-single-person':/g) || []).length, 1)
  assert.match(app, /<LogisticsSinglePersonDetectionSection department=\{currentDepartment\}/)
  assert.ok(app.includes('key={`${activePage}:${currentDepartment}`}'))
  assert.match(sidebarSource, /currentPage === item.id && currentDepartment === child.department/)
  assert.match(sidebarSource, /onPageChange\(item.id, child.department\)/)
  const section = await read('sections/LogisticsSinglePersonDetectionSection.tsx')
  assert.match(section, /key=\{department\}/)
  assert.match(section, /department=\{department\}/)
  const config = await read('components/logistics_single_person/LogisticsChannelConfigView.tsx')
  assert.match(config, /getAiVisionCameras\(department\)/)
  assert.match(config, /createLogisticsChannel\(feature, \{ name, department \}\)/)
  assert.doesNotMatch(config, /createDialog\.department|change-department/)
  const home = await read('sections/HomeSection.tsx')
  assert.match(home, /onNavigate\(camera.capabilities\[0\], camera.department\)/)
  assert.doesNotMatch(home, /logisticsPageByFeature/)
})

test('总览直接展示后端的事业部摄像头和能力统计', async () => {
  const home = await read('sections/HomeSection.tsx')
  assert.match(home, /overviewStatus\?\.capabilities/)
  assert.match(home, /overviewStatus\?\.cameras/)
  assert.doesNotMatch(home, /getLoadedAiVisionFeatureCounts|mergeAiVisionAndLogisticsCameras/)
})
