import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

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
  assert.doesNotMatch(manager, /onAddCamera|onRemoveCamera|selectedExistingCamera|availableCameras|canAddSelectedCamera|handleEnableExisting/)
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

  assert.match(guardConfig, /await createGuardRoomSiteCamera\(site\.id, \{ name, rtsp_url: rtsp \}, department\)/)
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


test('camera queries and Guard mutations transmit explicit department context', async () => {
  const calls = []
  const compile = (source) => ts.transpileModule(source.replaceAll('import.meta.env', '({})'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const load = async (path) => {
    const context = {
      exports: {}, URLSearchParams,
      fetch: async (url, options) => {
        calls.push({ url, options })
        return { ok: true, status: 200, json: async () => [] }
      },
      require(name) {
        if (name === '@/lib/camera-events') return { notifyPlatformCamerasChanged() {} }
        if (name === '@/lib/runtime-events') return { notifyPlatformRuntimeChanged() {} }
        if (name === '@/lib/horn-alarm-binding') return { validateHornBinding() {} }
        throw new Error(`unexpected import: ${name}`)
      },
    }
    vm.runInNewContext(compile(await readFrontendSource(path)), context)
    return context.exports
  }
  const ai = await load('src/lib/aivision.ts')
  const guard = await load('src/lib/api.ts')
  const catalog = await load('src/auth/permissions.ts')
  for (const department of catalog.DEPARTMENTS) {
    calls.length = 0
    await ai.getAiVisionCameras(department)
    await guard.getGuardRoomSites(department)
    await guard.updateGuardRoomSite(12, { name: '当前站点' }, department)
    await guard.deleteGuardRoomSite(12, department)
    await guard.saveGuardRoomSiteConfig(12, {}, department)
    await guard.startGuardRoomSiteRuntime(12, department)
    await guard.stopGuardRoomSiteRuntime(12, department)
    await guard.restartGuardRoomSiteRuntime(12, department)
    await guard.createGuardRoomSiteCamera(12, { name: '当前摄像头', rtsp_url: 'rtsp://camera' }, department)
    await guard.updateGuardRoomCamera(23, { name: '更新名称' }, department)
    await guard.deleteGuardRoomCamera(23, department)
    const expected = [
      ['GET', '/api/cameras'], ['GET', '/api/sites'],
      ['PUT', '/api/sites/12'], ['DELETE', '/api/sites/12'],
      ['POST', '/api/sites/12/config'], ['POST', '/api/sites/12/control/start'],
      ['POST', '/api/sites/12/control/stop'], ['POST', '/api/sites/12/control/restart'],
      ['POST', '/api/sites/12/cameras'],
      ['PUT', '/api/integrations/guard-room/api/cameras/23'],
      ['DELETE', '/api/integrations/guard-room/api/cameras/23'],
    ]
    assert.equal(calls.length, expected.length)
    calls.forEach(({ url, options }, index) => {
      assert.equal(url, `${expected[index][1]}?department=${department}`)
      assert.equal(options.method ?? 'GET', expected[index][0])
      assert.equal(options.credentials, 'include')
    })
    calls.length = 0
    await ai.saveAiVisionCameraOrder(department, [3, 7, 2])
    assert.equal(calls[0].url, '/api/cameras/order')
    assert.equal(calls[0].options.method, 'PUT')
    assert.equal(calls[0].options.credentials, 'include')
    assert.deepEqual(JSON.parse(calls[0].options.body), { department, camera_ids: [3, 7, 2] })
  }
})
