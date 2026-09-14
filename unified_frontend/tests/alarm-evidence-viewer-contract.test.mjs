import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)

test('alarm details expose image zoom and shared evidence video states', async () => {
  const [section, api, preview] = await Promise.all([
    readFile(new URL('src/sections/AlarmsSection.tsx', frontendRoot), 'utf8'),
    readFile(new URL('src/lib/api.ts', frontendRoot), 'utf8'),
    readFile(new URL('src/components/ImagePreviewDialog.tsx', frontendRoot), 'utf8'),
  ])

  assert.match(section, /aria-label="放大查看报警截图"/)
  assert.match(section, /ImagePreviewDialog/)
  assert.match(section, /title="报警截图"/)
  assert.match(preview, /alt=\{`\$\{title\}大图`\}/)
  assert.match(preview, /setImageZoom\(\(value\) => Math\.min\(3/)
  assert.match(section, /selectedAlarm\.video_status === 'ready'/)
  assert.match(section, /视频录制中/)
  assert.match(section, /onError=\{\(\) => setVideoError\(true\)\}/)
  assert.match(section, /报警视频加载失败/)
  assert.match(api, /alarmVideoUrl.*\/api\/alarms\/\$\{alarmId\}\/video/)
})
