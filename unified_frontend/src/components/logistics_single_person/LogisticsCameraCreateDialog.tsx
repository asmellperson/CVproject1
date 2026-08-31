// 文件说明：实现摄像头的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

import {
  initialLogisticsCameraDraft,
  normalizeLogisticsCameraDraft,
  validateLogisticsCameraDraft,
  type LogisticsCameraCreateInput,
} from './logisticsCameraCreateState'

type Props = {
  /**
   * 功能：停止并释放 `onClose` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onClose: () => void
  /**
   * 功能：处理 `onSubmit` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `payload`（LogisticsCameraCreateInput）：接口或事件携带的业务数据
   * 返回：Promise<void>；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsCameraCreateDialog.tsx` 的
   *         `LogisticsCameraCreateDialog` 调用本符号
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onSubmit: (payload: LogisticsCameraCreateInput) => Promise<void>
  title?: string
  description?: string
  submitLabel?: string
}

/**
 * 功能：实现 `messageOf` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `reason`（unknown）：`reason` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`String`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function messageOf(reason: unknown) {
  return reason instanceof Error ? reason.message : String(reason)
}

/**
 * 功能：渲染 `LogisticsCameraCreateDialog` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（Props）：React 组件属性对象；解构字段包括 onClose, onSubmit, title, description, submitLabel
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`useState`、`validateLogisticsCameraDraft`、`async`、`setError`、`setBusy`、`normalizeLogisticsCameraDraft`、`onSubmit`、`onClose`、`messageOf`、`return`
 *          等共 21 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染。
 */
export function LogisticsCameraCreateDialog({
  onClose,
  onSubmit,
  title = '新建摄像头并绑定',
  description = '填写摄像头信息，保存后将直接加入当前物流通道。',
  submitLabel = '新建并绑定',
}: Props) {
  const [draft, setDraft] = useState(initialLogisticsCameraDraft)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const validationError = validateLogisticsCameraDraft(draft)

  const submit = async () => {
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

  return (
    <Dialog open onOpenChange={(open) => {
      if (!open && !busy) onClose()
    }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="logistics-new-camera-name">摄像头名称</Label>
            <Input
              id="logistics-new-camera-name"
              value={draft.name}
              onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
              disabled={busy}
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="logistics-new-camera-fps">FPS</Label>
            <Input
              id="logistics-new-camera-fps"
              type="number"
              min="1"
              step="1"
              value={draft.fps}
              onChange={(event) => setDraft((current) => ({ ...current, fps: event.target.value }))}
              disabled={busy}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="logistics-new-camera-url">RTSP 地址</Label>
            <Input
              id="logistics-new-camera-url"
              value={draft.url}
              onChange={(event) => setDraft((current) => ({ ...current, url: event.target.value }))}
              placeholder="rtsp://用户名:密码@地址/stream"
              autoComplete="off"
              disabled={busy}
            />
          </div>
          {error ? (
            <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950/40 dark:text-rose-200">
              {error}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button type="button" onClick={() => void submit()} disabled={busy || validationError !== null}>
            {busy ? '正在新建' : submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
