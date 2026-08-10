# Logistics Camera Member Dialog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复物流通道已有摄像头下拉框的滚轮回顶问题，并将内嵌的新建摄像头表单改成按钮触发的专用弹窗。

**Architecture:** 为共享 `SelectContent` 增加默认兼容的滚动按钮开关，并只在物流已有摄像头列表关闭该行为。新增独立的物流摄像头弹窗与纯校验模块，父配置组件继续负责调用现有创建绑定 API 和刷新通道、成员及全局摄像头数据。

**Tech Stack:** React 19、TypeScript、Radix UI Select/Dialog、Node.js `node:test`、Vite/TypeScript build

---

## 文件结构

- 修改 `unified_frontend/src/components/ui/select.tsx`：为 `SelectContent` 增加可选滚动按钮开关，默认行为不变。
- 新建 `unified_frontend/src/components/logistics_single_person/logisticsCameraCreateState.ts`：集中定义新建摄像头草稿、校验和规范化逻辑。
- 新建 `unified_frontend/src/components/logistics_single_person/LogisticsCameraCreateDialog.tsx`：管理弹窗字段、提交、忙碌和错误展示。
- 修改 `unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx`：接入下拉修复、弹窗按钮、创建绑定及刷新链路。
- 修改 `unified_frontend/tests/logistics-channel-ui-contract.test.mjs`：覆盖 Select 局部开关、弹窗入口及页面结构。
- 新建 `unified_frontend/tests/logistics-camera-create-dialog.test.mjs`：覆盖表单校验、规范化和弹窗交互契约。
- 修改 `unified_frontend/tests/logistics-channel-membership.test.mjs`：覆盖成功创建后的刷新和失败抛出路径。

### Task 1: 修复已有摄像头下拉框滚轮回顶

**Files:**
- Modify: `unified_frontend/src/components/ui/select.tsx:48-84`
- Modify: `unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx:473-476`
- Test: `unified_frontend/tests/logistics-channel-ui-contract.test.mjs`

- [ ] **Step 1: 写入失败的 Select 局部行为测试**

在 `logistics-channel-ui-contract.test.mjs` 新增：

```javascript
test('existing camera select disables Radix scroll buttons without changing the shared default', () => {
  const select = read('src/components/ui/select.tsx')
  const config = read('src/components/logistics_single_person/LogisticsChannelConfigView.tsx')

  assert.match(select, /showScrollButtons = true/)
  assert.match(select, /showScrollButtons \? <SelectScrollUpButton \/> : null/)
  assert.match(select, /showScrollButtons \? <SelectScrollDownButton \/> : null/)
  assert.match(config, /<SelectContent showScrollButtons=\{false\}>/)
})
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
cd unified_frontend && node --test tests/logistics-channel-ui-contract.test.mjs
```

Expected: FAIL，提示找不到 `showScrollButtons = true`。

- [ ] **Step 3: 为共享 Select 增加默认开启的开关**

将 `SelectContent` 参数和滚动按钮渲染调整为：

```tsx
function SelectContent({
  className,
  children,
  position = "item-aligned",
  align = "center",
  showScrollButtons = true,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Content> & {
  showScrollButtons?: boolean
}) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        data-slot="select-content"
        className={cn(
          "bg-popover text-popover-foreground data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 relative z-50 max-h-(--radix-select-content-available-height) min-w-[8rem] origin-(--radix-select-content-transform-origin) overflow-x-hidden overflow-y-auto rounded-md border shadow-md",
          position === "popper" &&
            "data-[side=bottom]:translate-y-1 data-[side=left]:-translate-x-1 data-[side=right]:translate-x-1 data-[side=top]:-translate-y-1",
          className
        )}
        position={position}
        align={align}
        {...props}
      >
        {showScrollButtons ? <SelectScrollUpButton /> : null}
        <SelectPrimitive.Viewport
          className={cn(
            "p-1",
            position === "popper" &&
              "h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-trigger-width)] scroll-my-1"
          )}
        >
          {children}
        </SelectPrimitive.Viewport>
        {showScrollButtons ? <SelectScrollDownButton /> : null}
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  )
}
```

物流已有摄像头列表显式关闭按钮：

```tsx
<SelectContent showScrollButtons={false}>
  {existingCameraOptions.map((camera) => (
    <SelectItem key={camera.camera_id} value={String(camera.camera_id)}>
      {camera.name}
    </SelectItem>
  ))}
</SelectContent>
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `cd unified_frontend && node --test tests/logistics-channel-ui-contract.test.mjs`

Expected: 全部测试 PASS。

- [ ] **Step 5: 提交下拉修复**

```bash
git add unified_frontend/src/components/ui/select.tsx unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx unified_frontend/tests/logistics-channel-ui-contract.test.mjs
git commit -m "fix: keep logistics camera select scroll position"
```

### Task 2: 新增物流摄像头创建弹窗及校验

**Files:**
- Create: `unified_frontend/src/components/logistics_single_person/logisticsCameraCreateState.ts`
- Create: `unified_frontend/src/components/logistics_single_person/LogisticsCameraCreateDialog.tsx`
- Create: `unified_frontend/tests/logistics-camera-create-dialog.test.mjs`

- [ ] **Step 1: 写入失败的草稿校验测试**

创建测试文件，使用项目现有的 TypeScript 内存转译方式导入纯逻辑：

```javascript
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const stateSource = await readFile(
  new URL('../src/components/logistics_single_person/logisticsCameraCreateState.ts', import.meta.url),
  'utf8',
).catch(() => '')
const dialogSource = await readFile(
  new URL('../src/components/logistics_single_person/LogisticsCameraCreateDialog.tsx', import.meta.url),
  'utf8',
).catch(() => '')

async function importTypeScript(value) {
  const output = ts.transpileModule(value, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  return import(`data:text/javascript;base64,${Buffer.from(output).toString('base64')}`)
}

test('validates and normalizes a logistics camera draft', async () => {
  const { validateLogisticsCameraDraft, normalizeLogisticsCameraDraft } = await importTypeScript(stateSource)

  assert.match(validateLogisticsCameraDraft({ name: '', fps: '5', url: 'rtsp://camera' }), /名称/)
  assert.match(validateLogisticsCameraDraft({ name: '东门', fps: '0', url: 'rtsp://camera' }), /FPS/)
  assert.match(validateLogisticsCameraDraft({ name: '东门', fps: '1.5', url: 'rtsp://camera' }), /FPS/)
  assert.match(validateLogisticsCameraDraft({ name: '东门', fps: '5', url: '' }), /RTSP/)
  assert.equal(validateLogisticsCameraDraft({ name: ' 东门 ', fps: '5', url: ' rtsp://camera ' }), null)
  assert.deepEqual(
    normalizeLogisticsCameraDraft({ name: ' 东门 ', fps: '5', url: ' rtsp://camera ' }),
    { name: '东门', fps: 5, url: 'rtsp://camera' },
  )
})

test('dialog exposes the approved fields and keeps failures visible', () => {
  for (const label of ['摄像头名称', 'FPS', 'RTSP 地址', '新建并绑定']) {
    assert.match(dialogSource, new RegExp(label))
  }
  assert.match(dialogSource, /await onSubmit\(payload\)/)
  assert.match(dialogSource, /setError\(messageOf\(reason\)\)/)
  assert.match(dialogSource, /if \(!busy\) onClose\(\)/)
})
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `cd unified_frontend && node --test tests/logistics-camera-create-dialog.test.mjs`

Expected: FAIL，因为状态模块和弹窗组件尚不存在。

- [ ] **Step 3: 实现纯草稿校验模块**

```typescript
export type LogisticsCameraDraft = {
  name: string
  fps: string
  url: string
}

export type LogisticsCameraCreateInput = {
  name: string
  fps: number
  url: string
}

export const initialLogisticsCameraDraft: LogisticsCameraDraft = {
  name: '',
  fps: '5',
  url: '',
}

export function validateLogisticsCameraDraft(draft: LogisticsCameraDraft): string | null {
  if (!draft.name.trim()) return '请输入摄像头名称。'
  const fps = Number(draft.fps)
  if (!Number.isInteger(fps) || fps < 1) return 'FPS 必须是大于等于 1 的整数。'
  if (!draft.url.trim()) return '请输入 RTSP 地址。'
  return null
}

export function normalizeLogisticsCameraDraft(
  draft: LogisticsCameraDraft,
): LogisticsCameraCreateInput {
  const error = validateLogisticsCameraDraft(draft)
  if (error) throw new Error(error)
  return { name: draft.name.trim(), fps: Number(draft.fps), url: draft.url.trim() }
}
```

- [ ] **Step 4: 实现独立弹窗组件**

组件使用 `Dialog`、三个受控 `Input`、取消按钮和“新建并绑定”按钮。提交处理必须采用以下语义：

```tsx
const submit = async () => {
  const validationError = validateLogisticsCameraDraft(draft)
  if (validationError) {
    setError(validationError)
    return
  }
  setBusy(true)
  setError('')
  try {
    const payload = normalizeLogisticsCameraDraft(draft)
    await onSubmit(payload)
    onClose()
  } catch (reason) {
    setError(messageOf(reason))
  } finally {
    setBusy(false)
  }
}
```

`Dialog` 关闭约束：

```tsx
<Dialog open onOpenChange={(open) => {
  if (!open && !busy) onClose()
}}>
```

三个输入和取消按钮均使用 `disabled={busy}`；提交按钮使用：

```tsx
disabled={busy || validateLogisticsCameraDraft(draft) !== null}
```

- [ ] **Step 5: 运行弹窗测试和 TypeScript 构建**

Run:

```bash
cd unified_frontend && node --test tests/logistics-camera-create-dialog.test.mjs && npm run build
```

Expected: 测试全部 PASS，`tsc -b` 和 Vite build 成功。

- [ ] **Step 6: 提交弹窗组件**

```bash
git add unified_frontend/src/components/logistics_single_person/logisticsCameraCreateState.ts unified_frontend/src/components/logistics_single_person/LogisticsCameraCreateDialog.tsx unified_frontend/tests/logistics-camera-create-dialog.test.mjs
git commit -m "feat: add logistics camera creation dialog"
```

### Task 3: 将弹窗接入摄像头成员配置页

**Files:**
- Modify: `unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx:84-102,242-327,470-490`
- Modify: `unified_frontend/tests/logistics-channel-ui-contract.test.mjs`
- Modify: `unified_frontend/tests/logistics-channel-membership.test.mjs`

- [ ] **Step 1: 写入失败的页面接入测试**

在 UI contract 测试的配置用例中加入：

```javascript
assert.match(config, /LogisticsCameraCreateDialog/)
assert.match(config, /setCameraDialogOpen\(true\)/)
assert.match(config, /新建摄像头并绑定/)
assert.doesNotMatch(config, /setNewCamera/)
```

在 membership 测试中加入：

```javascript
test('creating a camera refreshes memberships, channel data, and the global camera list', () => {
  const createBlock = configSource.slice(
    configSource.indexOf('const createCameraAndBind'),
    configSource.indexOf('const moveMember'),
  )
  assert.match(createBlock, /await addLogisticsChannelCamera/)
  assert.match(createBlock, /invalidateMemberships\(\)/)
  assert.match(createBlock, /onChanged\(\)/)
  assert.match(createBlock, /aivision:cameras-changed/)
  assert.match(createBlock, /throw reason/)
})
```

- [ ] **Step 2: 运行相关测试并确认失败**

Run:

```bash
cd unified_frontend && node --test tests/logistics-channel-ui-contract.test.mjs tests/logistics-channel-membership.test.mjs
```

Expected: FAIL，因为页面尚未接入弹窗和刷新链路。

- [ ] **Step 3: 接入弹窗状态与成员刷新函数**

导入弹窗和输入类型，新增：

```tsx
const [cameraDialogOpen, setCameraDialogOpen] = useState(false)

const invalidateMemberships = () => {
  membershipLoadRef.current = {
    ...membershipLoadRef.current,
    generation: membershipLoadRef.current.generation + 1,
  }
  setBoundCameraIds(new Set())
  setChannelMemberCounts({})
  setMembershipsLoaded(false)
  refreshMemberships()
}
```

让现有 `run` 在 `reloadMemberships` 为真时调用 `invalidateMemberships()`，删除重复的内联刷新语句。

- [ ] **Step 4: 实现可向弹窗传播错误的创建绑定处理**

```tsx
const createCameraAndBind = async (payload: LogisticsCameraCreateInput) => {
  if (!isAdmin) throw new Error('只有管理员可以新建摄像头。')
  const channelId = selectedChannelDetail?.id
  if (channelId === undefined) throw new Error('请先选择物流通道。')
  if (busy) throw new Error('正在处理其他操作，请稍后再试。')
  if (members.length >= 9) throw new Error('当前通道最多绑定 9 路摄像头。')

  setBusy(true)
  try {
    await addLogisticsChannelCamera(feature, channelId, payload)
    invalidateMemberships()
    setMessage('摄像头已新建并绑定。')
    onChanged()
    window.dispatchEvent(new Event('aivision:cameras-changed'))
  } catch (reason) {
    setMessage(`操作失败：${messageOf(reason)}`)
    throw reason
  } finally {
    setBusy(false)
  }
}
```

- [ ] **Step 5: 用按钮卡片替换内嵌表单并挂载弹窗**

卡片内容替换为：

```tsx
<Card>
  <CardHeader>
    <CardTitle className="text-base">新建摄像头并绑定</CardTitle>
    <CardDescription>填写摄像头信息后，将其直接加入当前物流通道。</CardDescription>
  </CardHeader>
  <CardContent>
    <Button
      className="w-full"
      onClick={() => setCameraDialogOpen(true)}
      disabled={!isAdmin || busy || !selectedChannelDetail || members.length >= 9}
    >
      <Plus className="h-4 w-4" />新建摄像头并绑定
    </Button>
  </CardContent>
</Card>
```

在配置视图根节点内挂载：

```tsx
{cameraDialogOpen ? (
  <LogisticsCameraCreateDialog
    onClose={() => setCameraDialogOpen(false)}
    onSubmit={createCameraAndBind}
  />
) : null}
```

删除 `newCamera` 状态和原内嵌字段。

- [ ] **Step 6: 运行相关测试并确认通过**

Run:

```bash
cd unified_frontend && node --test tests/logistics-channel-ui-contract.test.mjs tests/logistics-channel-membership.test.mjs tests/logistics-camera-create-dialog.test.mjs
```

Expected: 全部测试 PASS。

- [ ] **Step 7: 运行完整前端构建**

Run: `cd unified_frontend && npm run build`

Expected: `tsc -b` 与 Vite build 成功，无 TypeScript 错误。

- [ ] **Step 8: 提交页面接入**

```bash
git add unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx unified_frontend/tests/logistics-channel-ui-contract.test.mjs unified_frontend/tests/logistics-channel-membership.test.mjs
git commit -m "feat: open logistics camera creation in dialog"
```

### Task 4: 最终回归验证

**Files:**
- Verify only; no planned source changes

- [ ] **Step 1: 运行物流通道相关测试**

Run: `cd unified_frontend && node --test tests/logistics-channel-*.test.mjs tests/logistics-camera-create-dialog.test.mjs`

Expected: 全部测试 PASS，0 failures。

- [ ] **Step 2: 运行前端构建和差异检查**

```bash
cd unified_frontend && npm run build
cd .. && git diff --check
```

Expected: build 成功；`git diff --check` 无输出。

- [ ] **Step 3: 人工浏览器验收**

启动现有前后端环境后检查：

1. 打开“物流通道单人检测 → 配置管理 → 摄像头成员”。
2. 展开已有摄像头下拉框，连续使用鼠标滚轮向下，确认不会跳回第一项。
3. 点击“新建摄像头并绑定”，确认弹窗显示名称、FPS 和 RTSP 地址。
4. 输入非法 FPS，确认不能提交；输入有效内容并提交，确认成功关闭弹窗并显示新成员。
5. 模拟接口失败，确认弹窗保持打开并展示错误。

Expected: 五项全部符合设计文档。
