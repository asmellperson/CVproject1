// 文件说明：包含摄像头的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)

/**
 * 功能：读取或查询 `readFrontendSource` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（未显式标注）：目标路径
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`readFile`、`URL`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
async function readFrontendSource(path) {
  return readFile(new URL(path, frontendRoot), 'utf8')
}

test('ordinary AiVision configuration can create and immediately bind a camera', async () => {
  const manager = await readFrontendSource('src/components/FeatureCameraManager.tsx')

  assert.match(manager, /createAiVisionFeatureCamera\(feature, \{/)
  assert.match(manager, /department,/)
  assert.match(manager, /onSelectCamera\(camera\.shm_name\)/)
  assert.doesNotMatch(manager, /createAiVisionFeatureCamera[\s\S]*?await onAddCamera\(camera\.shm_name\)/)
  assert.match(manager, /新建摄像头并加入当前功能/)
  assert.match(manager, /<LogisticsCameraCreateDialog/)
  assert.match(manager, /notifyPlatformCamerasChanged\(\)/)
})

test('each ordinary AiVision page supplies its business department to camera creation', async () => {
  const expectedDepartments = new Map([
    ['src/sections/IntrusionDetectionSection.tsx', 'research_institute'],
    ['src/sections/DoorDetectionSection.tsx', 'general_electric'],
    ['src/sections/FaceDetectionSection.tsx', 'research_institute'],
    ['src/sections/PhoneDetectionSection.tsx', 'research_institute'],
  ])

  for (const [path, department] of expectedDepartments) {
    const source = await readFrontendSource(path)
    assert.match(source, /<FeatureCameraManager/)
    assert.match(source, new RegExp(`department="${department}"`))
  }

  const [human, haodaHuman] = await Promise.all([
    readFrontendSource('src/sections/HumanDetectionSection.tsx'),
    readFrontendSource('src/sections/HaodaHumanDetectionSection.tsx'),
  ])
  assert.match(human, /<FeatureCameraManager/)
  assert.match(human, /department = 'general_electric'/)
  assert.match(human, /department=\{department\}/)
  assert.match(haodaHuman, /department="haoda_company"/)
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
  assert.match(platformStatus, /restartKey: cameraRevision/)
})
