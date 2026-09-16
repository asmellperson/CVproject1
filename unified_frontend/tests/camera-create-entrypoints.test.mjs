import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)

async function readFrontendSource(path) {
  return readFile(new URL(path, frontendRoot), 'utf8')
}

test('ordinary AiVision configuration can create and immediately bind a camera', async () => {
  const [manager, api, cameraTypes] = await Promise.all([
    readFrontendSource('src/components/FeatureCameraManager.tsx'),
    readFrontendSource('src/lib/aivision.ts'),
    readFrontendSource('src/components/logistics_single_person/types.ts'),
  ])

  assert.match(manager, /createAiVisionFeatureCamera\(feature, \{/)
  assert.match(manager, /department,/)
  assert.match(manager, /onSelectCamera\(camera\.shm_name\)/)
  assert.doesNotMatch(manager, /createAiVisionFeatureCamera[\s\S]*?await onAddCamera\(camera\.shm_name\)/)
  assert.match(manager, /新建摄像头并加入当前功能/)
  assert.match(manager, /<LogisticsCameraCreateDialog/)
  assert.match(manager, /notifyPlatformCamerasChanged\(\)/)
  assert.match(api, /fps\?: number/)
  const internalRestartField = ['max', 'restart'].join('_')
  assert.equal(api.includes(internalRestartField), false)
  assert.equal(cameraTypes.includes(internalRestartField), false)
  assert.match(api, /updateAiVisionCamera[\s\S]*?method: 'PATCH'/)
})

test('all ordinary pages scope camera lists, monitors and creation to the selected department', async () => {
  for (const name of ['IntrusionDetection', 'DoorDetection', 'FaceDetection', 'PhoneDetection', 'HumanDetection']) {
    const source = await readFrontendSource(`src/sections/${name}Section.tsx`)
    assert.match(source, /department: DepartmentId/)
    assert.match(source, /getAiVisionCameras\(department\)/)
    assert.doesNotMatch(source, /getAiVisionCameras\(\)/)
    assert.match(source, /<FeatureCameraManager[\s\S]*?department=\{department\}/)
    assert.match(source, /<AiVisionMonitor[^>]*department=\{department\}/)
  }
})

test('guard and security configuration pages keep their camera creation entrypoints', async () => {
  const [guardConfig, securityConfig] = await Promise.all([
    readFrontendSource('src/sections/ConfigSection.tsx'),
    readFrontendSource('src/sections/SecurityVlmSection.tsx'),
  ])

  assert.match(guardConfig, /await createGuardRoomSiteCamera\(site\.id, \{ name, rtsp_url: rtsp \}\)/)
  assert.match(guardConfig, /<DialogTitle>添加摄像头<\/DialogTitle>/)
  assert.match(securityConfig, /await createSecurityVlmCamera\(department, name, rtspUrl\)/)
  assert.match(securityConfig, /onAdd=\{\(\) => void openCameraDialog\(null\)\}/)
})

test('camera mutations from every backend notify the shared overview inventory', async () => {
  const [aiVision, guardRoom, securityVlm, platformStatus] = await Promise.all([
    readFrontendSource('src/lib/aivision.ts'),
    readFrontendSource('src/lib/api.ts'),
    readFrontendSource('src/lib/security-vlm.ts'),
    readFrontendSource('src/hooks/use-platform-status.ts'),
  ])

  for (const source of [aiVision, guardRoom, securityVlm]) {
    assert.match(source, /notifyPlatformCamerasChanged\(\)/)
  }
  assert.match(aiVision, /\/api\/features\/\$\{encodeURIComponent\(feature\)\}\/cameras/)
  assert.match(platformStatus, /PLATFORM_CAMERAS_CHANGED_EVENT/)
  assert.match(platformStatus, /restartKey: `\$\{department\}:\$\{cameraRevision\}`/)
})
