import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)
const read = (path) => readFile(new URL(path, frontendRoot), 'utf8')
const [sidebar, home, users, audit, intrusion, face, phone, human, haodaHuman, door, securityVlm, alarms, statistics, logistics, nav, permissions] = await Promise.all([
  read('src/components/Sidebar.tsx'),
  read('src/sections/HomeSection.tsx'),
  read('src/sections/UserManagementSection.tsx'),
  read('src/sections/AccessAuditSection.tsx'),
  read('src/sections/IntrusionDetectionSection.tsx'),
  read('src/sections/FaceDetectionSection.tsx'),
  read('src/sections/PhoneDetectionSection.tsx'),
  read('src/sections/HumanDetectionSection.tsx'),
  read('src/sections/HaodaHumanDetectionSection.tsx'),
  read('src/sections/DoorDetectionSection.tsx'),
  read('src/sections/SecurityVlmSection.tsx'),
  read('src/sections/AlarmsSection.tsx'),
  read('src/sections/StatisticsSection.tsx'),
  read('src/components/logistics_single_person/LogisticsChannelSection.tsx'),
  read('src/lib/nav.ts'),
  read('src/auth/permissions.ts'),
])

test('uses the current materials institute name throughout active frontend views', () => {
  for (const source of [sidebar, home, users, audit, intrusion, face, phone]) {
    assert.match(source, /福达新材院/)
    assert.doesNotMatch(source, /人工智能研究院/)
  }
})

test('uses the current Weida company name throughout active frontend views', () => {
  for (const source of [sidebar, home, users, audit, securityVlm, alarms, statistics, logistics, nav]) {
    assert.match(source, /伟达公司/)
    assert.doesNotMatch(source, /贵金属回收/)
  }
  assert.match(permissions, /title: '物流通道单人检测（伟达公司）'/)
  assert.doesNotMatch(permissions, /title: '物流通道单人检测（贵金属回收）'/)
})

test('keeps the requested first-level company directories in sidebar order', () => {
  const groupConfig = sidebar.match(/const adminModuleGroups = \[[\s\S]*?\n\]/)?.[0] ?? ''
  const labels = [
    '通用电气事业部',
    '电子电工事业部',
    '电气部件事业部',
    '伟达公司',
    '皓达公司',
    '福力达公司',
    '福达新材院',
  ]

  assert.notEqual(groupConfig, '', 'expected sidebar department group configuration')
  for (const label of labels) assert.match(groupConfig, new RegExp(`label: '${label}'`))
  assert.doesNotMatch(groupConfig, /label: '贵金属回收事业部'/)
  assert.deepEqual(
    labels.map((label) => groupConfig.indexOf(`label: '${label}'`)),
    labels.map((label) => groupConfig.indexOf(`label: '${label}'`)).toSorted((left, right) => left - right),
  )
})

test('shows human dwell and door detection under their actual navigation owners', () => {
  assert.match(human, /departmentLabel = '通用电气事业部'/)
  assert.match(haodaHuman, /departmentLabel="皓达公司"/)
  assert.match(door, /departmentLabel="公共能力"/)
  assert.doesNotMatch(human, /人工智能研究院|福达新材院/)
  assert.doesNotMatch(door, /人工智能研究院|福达新材院/)
})
