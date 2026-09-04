import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const root = new URL('../', import.meta.url)
const read = (path) => readFile(new URL(path, root), 'utf8')

test('ordinary AiVision pages do not expose global runtime controls', async () => {
  const pages = [
    'IntrusionDetectionSection.tsx',
    'DoorDetectionSection.tsx',
    'FaceDetectionSection.tsx',
    'PhoneDetectionSection.tsx',
    'HumanDetectionSection.tsx',
  ]

  for (const file of pages) {
    const source = await read(`src/sections/${file}`)
    assert.doesNotMatch(source, /AiVisionFeatureRuntimeControl/)
    assert.doesNotMatch(source, /runtimeControl=/)
  }
})

test('AiVision API client does not expose global capability controls', async () => {
  const api = await read('src/lib/aivision.ts')

  assert.doesNotMatch(api, /getAiVisionCapabilities/)
  assert.doesNotMatch(api, /startAiVisionCapability/)
  assert.doesNotMatch(api, /stopAiVisionCapability/)
  assert.doesNotMatch(api, /\/api\/runtime\/capabilities/)
})

test('exception alert settings use the dedicated API route', async () => {
  const api = await read('src/lib/aivision.ts')

  assert.match(api, /\/api\/exception-alert/)
})

test('guard configuration saves without implicitly starting a manually stopped site', async () => {
  const [config, monitor, guardPage, runtime] = await Promise.all([
    read('src/sections/ConfigSection.tsx'),
    read('src/sections/MonitorSection.tsx'),
    read('src/sections/GuardBehaviorSection.tsx'),
    read('src/components/guard_room/GuardRoomRuntimeControl.tsx'),
  ])

  assert.match(config, /if \(site\.enabled\)/)
  assert.match(config, /配置已保存，检测保持关闭/)
  assert.doesNotMatch(monitor, /startGuardRoomSiteRuntime|stopGuardRoomSiteRuntime/)
  assert.match(runtime, /startGuardRoomSiteRuntime\(site\.id\)/)
  assert.match(runtime, /stopGuardRoomSiteRuntime\(site\.id\)/)
  assert.match(runtime, /await onChanged\(\)/)
  assert.match(guardPage, /onChanged=\{loadSites\}/)
})
