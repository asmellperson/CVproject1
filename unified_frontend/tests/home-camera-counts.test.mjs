// 文件说明：包含摄像头的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const frontendRoot = new URL('../', import.meta.url)

/**
 * 功能：实现 `importTypeScript` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（未显式标注）：目标路径
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`readFile`、`URL`、`transpileModule`、`import`、`from`、`toString`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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

  assert.equal(getLoadedAiVisionFeatureCounts([], false), undefined)
  assert.equal(getLoadedAiVisionFeatureCounts([], true).detect_logistics_single_person.cameraCount, 0)
})

test('counts a loaded logistics camera inventory by feature', async () => {
  const { getLoadedAiVisionFeatureCounts } = await importTypeScript(
    'src/sections/homeCameraCounts.ts',
  )
  const cameras = [
    {
      enabled: true,
      functions: { detect_logistics_single_person: true },
    },
    {
      enabled: false,
      functions: ['detect_logistics_single_person'],
    },
  ]

  const counts = getLoadedAiVisionFeatureCounts(cameras, true)
  assert.deepEqual(counts.detect_logistics_single_person, {
    cameraCount: 2,
    enabledCameraCount: 1,
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
      feature_name: 'detect_logistics_single_person_electrical_components',
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
    merged[1].functions.detect_logistics_single_person_electrical_components,
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
  assert.match(source, /Promise\.allSettled\(\[[\s\S]*?getAiVisionCameras\(\)[\s\S]*?guardRequest[\s\S]*?getLogisticsCameraInventory\(\)/)
  assert.match(source, /visibleGuardDepartments\.map\(\(itemDepartment\) => getGuardRoomSites\(itemDepartment\)\)/)
  assert.match(source, /cameras: \(await getSecurityVlmCameras\(itemDepartment\)\)\.cameras/)
  assert.match(source, /setCameraInventoryPartial\([\s\S]*?securityResults\.some\(\(result\) => result\.status === 'rejected'\)/)
  assert.match(source, /setCameraInventoryLoaded\(true\)/)
  assert.match(source, /window\.addEventListener\(PLATFORM_CAMERAS_CHANGED_EVENT, refreshCameraInventory\)/)
  assert.match(source, /已汇总 AiVision、物流通道、保安行为和安检流程摄像头/)
})
