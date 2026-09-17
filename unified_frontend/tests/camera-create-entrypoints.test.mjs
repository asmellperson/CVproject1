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
  assert.match(manager, /onCamerasChanged\(camera\.shm_name\)/)
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

test('Guard binds platform cameras while security retains its camera creation entrypoint', async () => {
  const [guardConfig, securityConfig] = await Promise.all([
    readFrontendSource('src/components/guard_behavior/CameraMembership.tsx'),
    readFrontendSource('src/sections/SecurityVlmSection.tsx'),
  ])

  assert.match(guardConfig, /addCamera\(site\.id, Number\(selected\)\)/)
  assert.doesNotMatch(guardConfig, /rtsp|createAiVisionCamera/i)
  assert.match(securityConfig, /await createSecurityVlmCamera\(department, name, rtspUrl\)/)
  assert.match(securityConfig, /onAdd=\{\(\) => void openCameraDialog\(null\)\}/)
})

test('camera mutations from every backend notify the shared overview inventory', async () => {
  const [aiVision, securityVlm, platformStatus] = await Promise.all([
    readFrontendSource('src/lib/aivision.ts'),
    readFrontendSource('src/lib/security-vlm.ts'),
    readFrontendSource('src/hooks/use-overview.ts'),
  ])

  for (const source of [aiVision, securityVlm]) {
    assert.match(source, /notifyPlatformCamerasChanged\(\)/)
  }
  assert.match(aiVision, /\/api\/features\/\$\{encodeURIComponent\(feature\)\}\/cameras/)
  assert.match(platformStatus, /PLATFORM_CAMERAS_CHANGED_EVENT/)
  assert.match(platformStatus, /restartKey: context/)
})


test('camera queries and native Guard APIs transmit the formal resource contracts', async () => {
  const calls = []
  const cache = new Map()
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
        if (name === '@/lib/api') return cache.get(name)
        if (name === '@/lib/camera-events') return { notifyPlatformCamerasChanged() {} }
        if (name === '@/lib/horn-alarm-binding') return { validateHornBinding() {} }
        throw new Error(`unexpected import: ${name}`)
      },
    }
    vm.runInNewContext(compile(await readFrontendSource(path)), context)
    return context.exports
  }
  cache.set('@/lib/api', await load('src/lib/api.ts'))
  const ai = await load('src/lib/aivision.ts')
  const guard = await load('src/components/guard_behavior/api.ts')
  await ai.getAiVisionCameras('general_electric')
  const signal = new AbortController().signal
  await guard.getSites('general_electric', signal)
  await guard.getSite(12)
  await guard.createSite({ name: '南门', department: 'general_electric' })
  await guard.updateSite(12, { enabled: false, sort_order: 3 })
  await guard.getMembers(12)
  await guard.addCamera(12, 23)
  await guard.reorderCameras(12, [23, 24])
  await guard.setCameraEnabled(12, 23, false)
  await guard.getPolicy(12)
  await guard.updatePolicy(12, { phone_seconds: 4 })
  await guard.getRoi(12, 23)
  await guard.updateRoi(12, 23, [])
  await guard.getAlarmPolicies(12)
  await guard.updateAlarmPolicy(12, 9, { sql_enable: true })
  await guard.getSiteStatus(12)
  await guard.removeCamera(12, 23)
  await guard.deleteSite(12)
  const prefix = '/api/guard-behavior/sites'
  const expected = [
    ['GET', '/api/cameras?department=general_electric'], ['GET', `${prefix}?department=general_electric`],
    ['GET', `${prefix}/12`], ['POST', prefix], ['PATCH', `${prefix}/12`],
    ['GET', `${prefix}/12/cameras`], ['POST', `${prefix}/12/cameras`],
    ['PUT', `${prefix}/12/cameras/order`], ['PUT', `${prefix}/12/cameras/23/enabled`],
    ['GET', `${prefix}/12/policy`], ['PATCH', `${prefix}/12/policy`],
    ['GET', `${prefix}/12/cameras/23/roi`], ['PUT', `${prefix}/12/cameras/23/roi`],
    ['GET', `${prefix}/12/alarm-policies`], ['PATCH', `${prefix}/12/alarm-policies/9`],
    ['GET', `${prefix}/12/status`], ['DELETE', `${prefix}/12/cameras/23`], ['DELETE', `${prefix}/12`],
  ]
  assert.equal(calls.length, expected.length)
  calls.forEach(({ url, options }, index) => {
    assert.equal(url, expected[index][1])
    assert.equal(options.method ?? 'GET', expected[index][0])
    assert.equal(options.credentials, 'include')
  })
  assert.equal(calls[1].options.signal, signal)
  assert.deepEqual(JSON.parse(calls[6].options.body), { camera_id: 23 })
  assert.deepEqual(JSON.parse(calls[7].options.body), { camera_ids: [23, 24] })
  assert.deepEqual(JSON.parse(calls[12].options.body), { vehicle_roi_pos: [] })
  assert.deepEqual(JSON.parse(calls[14].options.body), { sql_enable: true })
  assert.equal(guard.siteFrameUrl(12), `${prefix}/12/frame.jpg`)
  calls.length = 0
  await ai.saveAiVisionCameraOrder('general_electric', [3, 7, 2])
  assert.deepEqual(JSON.parse(calls[0].options.body), { department: 'general_electric', camera_ids: [3, 7, 2] })
})
