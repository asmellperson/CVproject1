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
import type { SecurityVlmCamera } from '@/lib/security-vlm'

type Props = {
  camera?: SecurityVlmCamera | null
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
   * 功能：更新或保存 `onSave` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `name`（string）：业务对象名称
   *   - `rtspUrl`（string）：`rtspUrl` 对应的业务输入值
   * 返回：Promise<void>；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onSave: (name: string, rtspUrl: string) => Promise<void>
  /**
   * 功能：验证 `onTest` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `rtspUrl`（string）：`rtspUrl` 对应的业务输入值
   * 返回：Promise<string>；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/components/security-vlm/SecurityCameraDialog.tsx` 的 `SecurityCameraDialog` 调用本符号
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onTest: (rtspUrl: string) => Promise<string>
  /**
   * 功能：删除或清理 `onDelete` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：Promise<void>；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onDelete?: () => Promise<void>
}

/**
 * 功能：渲染 `SecurityCameraDialog` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（Props）：React 组件属性对象；解构字段包括 camera, onClose, onSave, onTest, onDelete
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`useState`、`async`、`setBusy`、`setMessage`、`operation`、`error`、`String`、`return`、`onClose`、`setName` 等共 25 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染；会读取或修改浏览器全局对象/DOM 状态。
 */
export function SecurityCameraDialog({
  camera,
  onClose,
  onSave,
  onTest,
  onDelete,
}: Props) {
  const [name, setName] = useState(camera?.name || '')
  const [rtspUrl, setRtspUrl] = useState(camera?.rtsp_url || '')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  const run = async (operation: () => Promise<void>) => {
    setBusy(true)
    setMessage('')
    try {
      await operation()
    } catch (error) {
      console.error('[SecurityCameraDialog] 摄像头操作失败', error)
      setMessage(`操作失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{camera ? '编辑安检摄像头' : '添加安检摄像头'}</DialogTitle>
          <DialogDescription>填写摄像头名称和 RTSP 地址，最多可配置 4 台。</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="security-camera-name">摄像头名称</Label>
            <Input
              id="security-camera-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：安检工位一号"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="security-camera-rtsp">RTSP 地址</Label>
            <Input
              id="security-camera-rtsp"
              type="text"
              autoComplete="off"
              value={rtspUrl}
              onChange={(event) => setRtspUrl(event.target.value)}
              placeholder="rtsp://用户名:密码@地址/stream"
            />
          </div>
          {message && <p className="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-600">{message}</p>}
        </div>
        <DialogFooter className="sm:justify-between">
          <div>
            {camera && onDelete && (
              <Button
                type="button"
                variant="destructive"
                disabled={busy}
                onClick={() => {
                  if (window.confirm(`确定删除“${camera.name}”吗？ROI 文件会保留。`)) {
                    void run(onDelete)
                  }
                }}
              >
                删除
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={busy || !rtspUrl.trim()}
              onClick={() => void run(async () => setMessage(await onTest(rtspUrl.trim())))}
            >
              测试连接
            </Button>
            <Button
              type="button"
              disabled={busy || !name.trim() || (!camera && !rtspUrl.trim())}
              onClick={() => void run(() => onSave(name.trim(), rtspUrl.trim()))}
            >
              {busy ? '处理中' : '保存'}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
