// 文件说明：实现摄像头的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { Camera, Pencil, Plus, Power, PowerOff, RotateCw, VideoOff } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { SecurityVlmCamera } from '@/lib/security-vlm'

type Props = {
  cameras: SecurityVlmCamera[]
  selectedId?: string
  isAdmin: boolean
  busyId?: string | null
  /**
   * 功能：处理 `onSelect` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `cameraId`（string）：摄像头唯一标识
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/components/security-vlm/SecurityCameraBar.tsx` 的 `SecurityCameraBar` 调用本符号
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onSelect: (cameraId: string) => void
  /**
   * 功能：处理 `onToggle` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `camera`（SecurityVlmCamera）：摄像头配置或实体
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/components/security-vlm/SecurityCameraBar.tsx` 的 `SecurityCameraBar` 调用本符号
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onToggle: (camera: SecurityVlmCamera) => void
  /**
   * 功能：处理 `onRestart` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `camera`（SecurityVlmCamera）：摄像头配置或实体
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/components/security-vlm/SecurityCameraBar.tsx` 的 `SecurityCameraBar` 调用本符号
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onRestart: (camera: SecurityVlmCamera) => void
  /**
   * 功能：处理 `onEdit` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `camera`（SecurityVlmCamera）：摄像头配置或实体
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/components/security-vlm/SecurityCameraBar.tsx` 的 `SecurityCameraBar` 调用本符号
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onEdit: (camera: SecurityVlmCamera) => void
  /**
   * 功能：创建或构建 `onAdd` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onAdd: () => void
}

/**
 * 功能：渲染 `SecurityCameraBar` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（Props）：React 组件属性对象；解构字段包括 cameras, selectedId, isAdmin, busyId, onSelect, onToggle, onRestart, onEdit
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`map`、`cn`、`onSelect`、`stopPropagation`、`onToggle`、`onRestart`、`Boolean`、`onEdit`、`Camera` 等共 18 个调用。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function SecurityCameraBar({
  cameras,
  selectedId,
  isAdmin,
  busyId,
  onSelect,
  onToggle,
  onRestart,
  onEdit,
  onAdd,
}: Props) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {cameras.map((camera) => (
        <div
          key={camera.camera_id}
          role="button"
          tabIndex={0}
          className={cn(
            'rounded-xl border bg-white p-4 text-left shadow-sm transition hover:border-blue-300 dark:border-slate-800 dark:bg-slate-900',
            selectedId === camera.camera_id && 'border-blue-500 ring-2 ring-blue-100',
          )}
          onClick={() => onSelect(camera.camera_id)}
          onKeyDown={(event) => {
            if (event.target !== event.currentTarget) return
            if (event.key === 'Enter' || event.key === ' ') onSelect(camera.camera_id)
          }}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Camera className="h-4 w-4 shrink-0 text-slate-500" />
                <span className="truncate font-semibold text-slate-900 dark:text-slate-100">{camera.name}</span>
              </div>
            </div>
            <Badge
              variant={camera.running ? 'default' : 'secondary'}
              className={cn(
                camera.running && 'bg-emerald-600',
                camera.desired_running && !camera.running && 'bg-amber-500 text-white',
              )}
            >
              {camera.running
                ? '运行中'
                : camera.desired_running
                  ? '重启中'
                  : '已停止'}
            </Badge>
          </div>
          <div className="mt-3 flex items-center justify-between gap-2">
            <span className="text-xs text-slate-500">
              {camera.running
                ? '检测与会话处理中'
                : camera.desired_running
                  ? '正在恢复画面'
                  : '摄像头已停止'}
            </span>
            {isAdmin && (
              <span className="flex shrink-0 gap-1" onClick={(event) => event.stopPropagation()}>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8"
                  disabled={busyId === camera.camera_id}
                  onClick={() => onToggle(camera)}
                  title={camera.desired_running ? '关闭摄像头' : '开启摄像头'}
                >
                  {camera.desired_running
                    ? <PowerOff className="h-4 w-4" />
                    : <Power className="h-4 w-4" />}
                </Button>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8"
                  disabled={!camera.running || busyId === camera.camera_id}
                  onClick={() => onRestart(camera)}
                  title="重启摄像头"
                >
                  <RotateCw className="h-4 w-4" />
                </Button>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8"
                  disabled={Boolean(camera.desired_running) || busyId === camera.camera_id}
                  onClick={() => onEdit(camera)}
                  title="编辑摄像头"
                >
                  <Pencil className="h-4 w-4" />
                </Button>
              </span>
            )}
          </div>
        </div>
      ))}
      {cameras.length === 0 && (
        <div className="flex min-h-32 items-center justify-center gap-2 rounded-xl border border-dashed text-sm text-slate-500 sm:col-span-2">
          <VideoOff className="h-5 w-5" />
          尚未添加安检摄像头
        </div>
      )}
      {isAdmin && cameras.length < 4 && (
        <button
          type="button"
          className="flex min-h-32 items-center justify-center gap-2 rounded-xl border border-dashed bg-slate-50 text-sm font-medium text-slate-600 transition hover:border-blue-400 hover:text-blue-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300"
          onClick={onAdd}
        >
          <Plus className="h-5 w-5" />
          添加摄像头
        </button>
      )}
    </div>
  )
}
