import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

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
