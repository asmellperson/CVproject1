import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const root = new URL('../', import.meta.url)
const read = (path) => readFile(new URL(path, root), 'utf8')

test('ordinary AiVision pages share the same runtime control', async () => {
  const expected = new Map([
    ['IntrusionDetectionSection.tsx', 'blocks'],
    ['DoorDetectionSection.tsx', 'detect_door'],
    ['FaceDetectionSection.tsx', 'detect_face'],
    ['PhoneDetectionSection.tsx', 'detect_phone'],
  ])

  for (const [file, feature] of expected) {
    const source = await read(`src/sections/${file}`)
    assert.match(source, /AiVisionFeatureRuntimeControl/)
    assert.match(source, new RegExp(`feature="${feature}" isAdmin=\\{isAdmin\\}`))
  }

  const [humanPage, haodaPage] = await Promise.all([
    read('src/sections/HumanDetectionSection.tsx'),
    read('src/sections/HaodaHumanDetectionSection.tsx'),
  ])
  assert.match(humanPage, /AiVisionFeatureRuntimeControl feature=\{feature\} isAdmin=\{isAdmin\}/)
  assert.match(haodaPage, /feature="detect_human_haoda"/)
})

test('runtime control polls status and exposes separate admin start and stop actions', async () => {
  const [control, sharedControl, api, platformHook] = await Promise.all([
    read('src/components/AiVisionFeatureRuntimeControl.tsx'),
    read('src/components/detection/DetectionRuntimeControl.tsx'),
    read('src/lib/aivision.ts'),
    read('src/hooks/use-platform-status.ts'),
  ])

  assert.match(control, /useSerialPoll/)
  assert.match(control, /startAiVisionCapability\(feature\)/)
  assert.match(control, /stopAiVisionCapability\(feature\)/)
  assert.match(control, /isAdmin=\{isAdmin\}/)
  assert.match(sharedControl, /!isAdmin/)
  assert.match(control, /检测控制/)
  assert.match(sharedControl, /PowerOff/)
  assert.match(sharedControl, /Power/)
  assert.doesNotMatch(sharedControl, /Play|Pause/)
  assert.match(api, /\/api\/v2\/runtime\/capabilities/)
  assert.match(platformHook, /PLATFORM_RUNTIME_CHANGED_EVENT/)
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
