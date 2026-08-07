import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const frontendRoot = new URL('../', import.meta.url)

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

test('home overview only marks the camera inventory loaded after a successful request', async () => {
  const source = await readFile(new URL('src/sections/HomeSection.tsx', frontendRoot), 'utf8')

  assert.match(source, /const \[aiVisionCamerasLoaded, setAiVisionCamerasLoaded\] = useState\(false\)/)
  assert.match(source, /getLoadedAiVisionFeatureCounts\(aiVisionCameras, aiVisionCamerasLoaded\)/)
  assert.match(source, /const cameraStatusReady = aiVisionCamerasLoaded && platformStatus !== null/)
  assert.match(source, /cameraStatusReady \? `\$\{cameraInventorySummary\.cameraOnline\}\/\$\{cameraInventorySummary\.cameraTotal\}` : '加载中'/)
  assert.match(source, /if \(cameras\.status === 'fulfilled'\) \{[\s\S]*?setAiVisionCamerasLoaded\(true\)[\s\S]*?\} else \{[\s\S]*?setAiVisionCamerasLoaded\(false\)/)
})
