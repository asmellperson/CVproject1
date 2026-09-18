import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const read = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')
const section = await read('sections/SecurityVlmSection.tsx')
const configuration = await read('components/security-inspection/InspectionConfiguration.tsx')

test('inspection keeps monitor and configuration panels with platform camera and alarm controls', () => {
  assert.match(section, /<DetectionPageHeader/)
  assert.match(section, /monitorValue="dashboard"/)
  for (const tab of ['camera', 'roi', 'parameters', 'alarm']) {
    assert.match(section, new RegExp(`DetectionConfigTab value="${tab}"`))
  }
  assert.match(section, /<FeatureCameraManager/)
  assert.match(configuration, /<AiVisionRoiEditor/)
  assert.match(configuration, /<AlarmPushConfig/)
  assert.match(configuration, /saveAiVisionFeatureConfig/)
  assert.doesNotMatch(section + configuration, /createSecurityVlmCamera|restartCamera|\/integrations\//)
})

test('inspection defaults to all cameras and retains the overview and history', () => {
  assert.match(section, /\[singleView, setSingleView\] = useState\(false\)/)
  assert.match(section, /key=\{department\}/)
  for (const title of ['合规', '不合规', '合规率', 'VLM 队列']) assert.ok(section.includes(title))
  assert.match(section, /<SecurityVideoPanel/)
  assert.match(section, /<InspectionHistory/)
})
