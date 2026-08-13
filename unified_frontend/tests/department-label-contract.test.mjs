import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)
const read = (path) => readFile(new URL(path, frontendRoot), 'utf8')
const [sidebar, home, users, audit, intrusion, face, phone, human, door] = await Promise.all([
  read('src/components/Sidebar.tsx'),
  read('src/sections/HomeSection.tsx'),
  read('src/sections/UserManagementSection.tsx'),
  read('src/sections/AccessAuditSection.tsx'),
  read('src/sections/IntrusionDetectionSection.tsx'),
  read('src/sections/FaceDetectionSection.tsx'),
  read('src/sections/PhoneDetectionSection.tsx'),
  read('src/sections/HumanDetectionSection.tsx'),
  read('src/sections/DoorDetectionSection.tsx'),
])

test('uses the current materials institute name throughout active frontend views', () => {
  for (const source of [sidebar, home, users, audit, intrusion, face, phone]) {
    assert.match(source, /福达新材院/)
    assert.doesNotMatch(source, /人工智能研究院/)
  }
})

test('shows human dwell and door detection under their actual navigation owners', () => {
  assert.match(human, /departmentLabel="通用电气事业部"/)
  assert.match(door, /departmentLabel="公共能力"/)
  assert.doesNotMatch(human, /人工智能研究院|福达新材院/)
  assert.doesNotMatch(door, /人工智能研究院|福达新材院/)
})
