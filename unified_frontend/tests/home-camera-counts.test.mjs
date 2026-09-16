import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const frontendRoot = new URL('../', import.meta.url)

test('shared human feature counts and online state are isolated by department', async () => {
  const { getLoadedAiVisionFeatureCounts } = await importTypeScript('src/sections/homeCameraCounts.ts')
  const cameras = [
    { enabled: true, department: 'general_electric', functions: { detect_human: true }, runtimeOnline: true },
    { enabled: true, department: 'haoda_company', functions: { detect_human: true }, runtimeOnline: false },
    { enabled: false, department: 'haoda_company', functions: { detect_human: true }, runtimeOnline: true },
  ]
  assert.deepEqual(getLoadedAiVisionFeatureCounts(cameras, true, 'general_electric').detect_human,
    { cameraCount: 1, enabledCameraCount: 1, onlineCameraCount: 1 })
  assert.deepEqual(getLoadedAiVisionFeatureCounts(cameras, true, 'haoda_company').detect_human,
    { cameraCount: 2, enabledCameraCount: 1, onlineCameraCount: 0 })
})

async function importTypeScript(path) {
  const source = await readFile(new URL(path, frontendRoot), 'utf8')
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  return import(`data:text/javascript;base64,${Buffer.from(output).toString('base64')}`)
}

test('uses backend feature counts until the camera inventory has loaded', async () => {
  const { getLoadedAiVisionFeatureCounts } = await importTypeScript(
    'src/sections/homeCameraCounts.ts',
  )

  assert.equal(getLoadedAiVisionFeatureCounts([], false, 'fulida_company'), undefined)
  assert.equal(getLoadedAiVisionFeatureCounts([], true, 'fulida_company').detect_logistics_single_person.cameraCount, 0)
})

test('counts a loaded logistics camera inventory by feature', async () => {
  const { getLoadedAiVisionFeatureCounts } = await importTypeScript(
    'src/sections/homeCameraCounts.ts',
  )
  const cameras = [
    {
      enabled: true,
      department: 'fulida_company',
      functions: { detect_logistics_single_person: true },
    },
    {
      enabled: false,
      department: 'fulida_company',
      functions: { detect_logistics_single_person: true },
    },
  ]

  const counts = getLoadedAiVisionFeatureCounts(cameras, true, 'fulida_company')
  assert.deepEqual(counts.detect_logistics_single_person, {
    cameraCount: 2,
    enabledCameraCount: 1,
    onlineCameraCount: 0,
  })
})

test('merges channel-backed logistics cameras into the overview without double counting', async () => {
  const { mergeAiVisionAndLogisticsCameras } = await importTypeScript(
    'src/sections/homeCameraCounts.ts',
  )
  const cameras = [{
    id: 'camera_7',
    camera_id: 7,
    name: '已有摄像头',
    shm_name: 'camera_7',
    enabled: true,
    department: 'general_electric',
    functions: {},
  }]
  const memberships = [{
    feature_name: 'detect_logistics_single_person',
    channel_id: 1,
    channel_name: '一号物流通道',
    enabled: true,
    online: true,
  }]
  const logisticsCameras = [{
    camera_id: 7,
    name: '已有摄像头',
    shm_name: 'camera_7',
    department: 'general_electric',
    enabled: true,
    online: true,
    memberships,
  }, {
    camera_id: 8,
    name: '仅存在于物流成员清单',
    shm_name: 'camera_8',
    department: 'electrical_components',
    enabled: true,
    online: false,
    memberships: [{
      ...memberships[0],
      feature_name: 'detect_logistics_single_person',
      channel_id: 2,
      channel_name: '二号物流通道',
      online: false,
    }],
  }]

  const merged = mergeAiVisionAndLogisticsCameras(cameras, logisticsCameras)

  assert.equal(merged.length, 2)
  assert.equal(merged[0].functions.detect_logistics_single_person, true)
  assert.equal(merged[0].inventoryOnly, undefined)
  assert.equal(merged[0].logisticsOnline, true)
  assert.equal(merged[1].camera_id, 8)
  assert.equal(merged[1].inventoryOnly, true)
  assert.equal(
    merged[1].functions.detect_logistics_single_person,
    true,
  )
})

test('counts online cameras from the unique loaded inventory', async () => {
  const { getCameraInventorySummary } = await importTypeScript(
    'src/sections/homeCameraCounts.ts',
  )
  const cameras = [
    { shm_name: 'camera-a', enabled: true, functions: {} },
    { shm_name: 'camera-b', enabled: true, functions: {} },
  ]

  assert.deepEqual(
    getCameraInventorySummary(cameras, ['camera-a', 'unknown-camera']),
    { cameraTotal: 2, cameraOnline: 1, cameraOffline: 1 },
  )
})

test('caps the camera online fallback at the inventory total', async () => {
  const { getCameraInventorySummary } = await importTypeScript(
    'src/sections/homeCameraCounts.ts',
  )
  const cameras = [{ id: 'camera-a', enabled: true, functions: {} }]

  assert.deepEqual(
    getCameraInventorySummary(cameras, undefined, 86),
    { cameraTotal: 1, cameraOnline: 1, cameraOffline: 0 },
  )
})

test('home overview aggregates every camera source and exposes partial failures', async () => {
  const source = await readFile(new URL('src/sections/HomeSection.tsx', frontendRoot), 'utf8')

  assert.match(source, /const \[aiVisionCamerasLoaded, setAiVisionCamerasLoaded\] = useState\(false\)/)
  assert.match(source, /const \[cameraInventoryLoaded, setCameraInventoryLoaded\] = useState\(false\)/)
  assert.match(source, /getLoadedAiVisionFeatureCounts\([\s\S]*?mergedAiVisionCameras[\s\S]*?aiVisionCamerasLoaded \|\| logisticsCamerasLoaded/)
  assert.match(source, /const cameraStatusReady = cameraInventoryLoaded && platformStatus !== null/)
  assert.match(source, /cameraStatusReady \? `\$\{cameraInventorySummary\.cameraOnline\}\/\$\{cameraInventorySummary\.cameraTotal\}` : '加载中'/)
  assert.match(source, /Promise\.allSettled\(\[[\s\S]*?getAiVisionCameras\(department\)[\s\S]*?guardRequest[\s\S]*?getLogisticsCameraInventory\(department\)/)
  assert.match(source, /getGuardRoomSites\(department\)/)
  assert.match(source, /getSecurityVlmCameras\(department\)/)
  assert.match(source, /setCameraInventoryPartial\([\s\S]*?securityResults\.some\(\(result\) => result\.status === 'rejected'\)/)
  assert.match(source, /setCameraInventoryLoaded\(true\)/)
  assert.match(source, /window\.addEventListener\(PLATFORM_CAMERAS_CHANGED_EVENT, refreshCameraInventory\)/)
  assert.match(source, /已汇总 AiVision、物流通道、保安行为和安检流程摄像头/)
})
