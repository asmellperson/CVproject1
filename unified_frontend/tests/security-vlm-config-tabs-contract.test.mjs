import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const section = await readFile(
  new URL('../src/sections/SecurityVlmSection.tsx', import.meta.url),
  'utf8',
)
const cameraDialog = await readFile(
  new URL('../src/components/security-vlm/SecurityCameraDialog.tsx', import.meta.url),
  'utf8',
)
const videoPanel = await readFile(
  new URL('../src/components/security-vlm/SecurityVideoPanel.tsx', import.meta.url),
  'utf8',
)

test('uses realtime monitor and nested configuration tabs', () => {
  assert.match(section, /const \[activeTab, setActiveTab\] = useState\('dashboard'\)/)
  assert.match(section, /const \[configTab, setConfigTab\] = useState\('camera'\)/)
  assert.match(section, /const roiActive = activeTab === 'config' && configTab === 'roi'/)
  assert.match(section, /<TabsTrigger value="dashboard"[^>]*>[\s\S]*?实时监控/)
  assert.match(section, /<TabsTrigger value="config"[^>]*>[\s\S]*?配置管理/)
  assert.match(section, /<Tabs value=\{configTab\} onValueChange=\{setConfigTab\}/)
  assert.match(section, /<TabsTrigger value="camera"[^>]*>[\s\S]*?摄像头管理/)
  assert.match(section, /<TabsTrigger value="roi"[^>]*>[\s\S]*?ROI 绘制/)

  const primaryTabsStart = section.indexOf('<Tabs value={activeTab}')
  const pageHeading = section.indexOf('<div className="flex flex-wrap items-center justify-between', primaryTabsStart)
  const primaryTabList = section.slice(primaryTabsStart, pageHeading)
  assert.doesNotMatch(primaryTabList, /TabsTrigger value="roi"/)
})

test('places camera operations and ROI drawing under configuration', () => {
  const dashboardContent = section.indexOf('<TabsContent\n          value="dashboard"')
  const configContent = section.indexOf('<TabsContent value="config"')
  const cameraContent = section.indexOf('<TabsContent value="camera"', configContent)
  const cameraBar = section.indexOf('<SecurityCameraBar', cameraContent)
  const startAll = section.indexOf("handleAllCameras('start')", cameraContent)
  const roiContent = section.indexOf('<TabsContent value="roi"', cameraContent)
  const roiEditor = section.indexOf('工位 ROI 绘制', roiContent)
  const multiView = section.indexOf("singleView ? '多画面' : '单画面'")

  assert.ok(dashboardContent >= 0)
  assert.ok(configContent > dashboardContent)
  assert.ok(cameraContent > configContent)
  assert.ok(cameraBar > cameraContent)
  assert.ok(startAll > cameraContent)
  assert.ok(roiContent > cameraBar)
  assert.ok(roiEditor > roiContent)
  assert.ok(multiView >= 0 && multiView < dashboardContent)
  assert.match(section, /activeTab === 'dashboard' && \(/)
  assert.equal(section.match(/<SecurityCameraBar/g)?.length, 1)

  const cameraPanel = section.slice(cameraContent, roiContent)
  assert.match(cameraPanel, /<SecurityCameraBar/)
  assert.match(cameraPanel, /handleAllCameras\('start'\)/)
  assert.match(cameraPanel, /handleAllCameras\('stop'\)/)
})

test('preserves camera, ROI, video, and dialog behavior', () => {
  for (const name of [
    'handleAllCameras',
    'handleToggleCamera',
    'handleRestartCamera',
    'openCameraDialog',
    'saveCamera',
    'deleteCamera',
    'getSecurityVlmCameraRois',
    'saveSecurityVlmCameraRois',
    'securityVlmCameraVideoUrl',
    'SecurityCameraDialog',
    'handlePointerDown',
    'handlePointerMove',
    'handlePointerUp',
  ]) {
    assert.match(section, new RegExp(name))
  }
  assert.match(section, /roiActive \? 'original' : 'rule'/)
  assert.match(section, /const setRoiImageRef = useCallback/)
  assert.match(section, /ref=\{setRoiImageRef\}/)
  assert.match(section, /image\.src = activeVideoUrl[\s\S]*?image\.removeAttribute\('src'\)/)
  assert.match(cameraDialog, /setMessage\(`操作失败：\$\{error instanceof Error \? error\.message : String\(error\)\}`\)/)
})

test('history only displays completed compliance decisions', () => {
  assert.match(
    section,
    /const judgedItems = items\.filter\([\s\S]*?item\.status === 'compliant' \|\| item\.status === 'non_compliant'/,
  )
  assert.match(
    section,
    /const filteredItems = cameraFilter === 'all'[\s\S]*?\? judgedItems[\s\S]*?: judgedItems\.filter/,
  )
})

test('defaults to all-camera view and only selects a camera in single view', () => {
  assert.match(section, /const \[singleView, setSingleView\] = useState\(false\)/)
  assert.match(section, /useEffect\(\(\) => \{[\s\S]*?setSingleView\(false\)[\s\S]*?getSecurityVlmHealth\(department\)/)
  assert.doesNotMatch(section, /secondaryCameraId|dualView/)
  assert.match(section, /singleView \? \([\s\S]*?cameraId=\{selectedCameraId\}/)
  assert.match(section, /cameras\.map\(\(camera\) => \([\s\S]*?cameraId=\{camera\.camera_id\}[\s\S]*?selectable=\{false\}/)
  assert.match(section, /cameras\.length === 3 && 'md:grid-cols-2 xl:grid-cols-3'/)
  assert.match(section, /cameras\.length >= 4 && 'md:grid-cols-2'/)
  assert.match(videoPanel, /selectable = true/)
  assert.match(videoPanel, /selectable \? \([\s\S]*?<Select value=\{cameraId\}/)
  assert.match(videoPanel, /camera\?\.name \|\| '暂无摄像头'/)
  assert.match(videoPanel, /image\.src = streamUrl[\s\S]*?image\.removeAttribute\('src'\)/)
  assert.doesNotMatch(videoPanel, /<img[\s\S]*?src=\{securityVlmCameraVideoUrl/)
})
