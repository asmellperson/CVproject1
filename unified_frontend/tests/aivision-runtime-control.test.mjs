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

test('Guard has no manual runtime controls or save-and-restart flow', async () => {
  for (const path of ['src/sections/GuardBehaviorSection.tsx', 'src/components/guard_behavior/GuardConfigView.tsx', 'src/components/guard_behavior/GuardMonitorView.tsx', 'src/components/guard_behavior/api.ts']) {
    const source = await read(path)
    assert.doesNotMatch(source, /RuntimeControl|waitUntilRunning|\/control\/|startGuard|stopGuard|restartGuard/)
  }
})
