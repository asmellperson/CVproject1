// 文件说明：实现`SecurityVideoPanel` 模块的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { useCallback, useImperativeHandle, useLayoutEffect, useRef } from 'react'
import { Pause } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  securityVlmCameraVideoUrl,
  type SecurityVlmCamera,
  type SecurityVlmDepartment,
} from '@/lib/security-vlm'

type Props = {
  department: SecurityVlmDepartment
  cameras: SecurityVlmCamera[]
  cameraId?: string
  kind?: 'original' | 'rule'
  nonce: number
  /**
   * 功能：处理 `onCameraChange` 对应的`SecurityVideoPanel` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `cameraId`（string）：摄像头唯一标识
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onCameraChange: (cameraId: string) => void
  selectable?: boolean
  imageRef?: React.Ref<HTMLImageElement>
  onLoad?: React.ReactEventHandler<HTMLImageElement>
}

/**
 * 功能：渲染 `SecurityVideoPanel` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（Props）：React 组件属性对象；解构字段包括 department, cameras, cameraId, kind, rule, nonce, onCameraChange, selectable
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`find`、`useRef`、`useCallback`、`useImperativeHandle`、`securityVlmCameraVideoUrl`、`useLayoutEffect`、`return`、`removeAttribute`、`map`、`HTMLImageElement`
 *          等共 16 个调用。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function SecurityVideoPanel({
  department,
  cameras,
  cameraId,
  kind = 'rule',
  nonce,
  onCameraChange,
  selectable = true,
  imageRef,
  onLoad,
}: Props) {
  const camera = cameras.find((item) => item.camera_id === cameraId)
  const streamImageRef = useRef<HTMLImageElement | null>(null)
  const setStreamImageRef = useCallback((node: HTMLImageElement | null) => {
    streamImageRef.current = node
  }, [])
  useImperativeHandle(imageRef, () => streamImageRef.current as HTMLImageElement)

  const streamUrl = camera?.running
    ? securityVlmCameraVideoUrl(department, camera.camera_id, kind, nonce)
    : ''

  useLayoutEffect(() => {
    const image = streamImageRef.current
    if (!image || !streamUrl) return
    // setup 主动恢复 src，兼容 React StrictMode 的 setup→cleanup→setup 检查。
    image.src = streamUrl
    return () => {
      // 真正切页或换流时立即取消 MJPEG，释放同源连接槽。
      image.removeAttribute('src')
    }
  }, [streamUrl])

  return (
    <div className="overflow-hidden rounded-lg border bg-slate-950">
      <div className="flex items-center justify-between gap-3 border-b border-slate-800 bg-slate-900 px-3 py-2">
        {selectable ? (
          <Select value={cameraId} onValueChange={onCameraChange}>
            <SelectTrigger className="h-8 w-full max-w-64 border-slate-700 bg-slate-800 text-slate-100">
              <SelectValue placeholder="选择摄像头" />
            </SelectTrigger>
            <SelectContent>
              {cameras.map((item) => (
                <SelectItem key={item.camera_id} value={item.camera_id}>
                  {item.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <span className="truncate text-sm font-medium text-slate-100">
            {camera?.name || '暂无摄像头'}
          </span>
        )}
        <span className="shrink-0 text-xs text-slate-400">
          {camera?.running ? '实时' : '已停止'}
        </span>
      </div>
      <div className="aspect-video">
        {camera?.running ? (
          <img
            ref={setStreamImageRef}
            alt={`${camera.name}实时画面`}
            className="h-full w-full select-none object-contain"
            draggable={false}
            onLoad={onLoad}
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-slate-400">
            <Pause className="h-8 w-8" />
            <span className="text-sm">{camera ? '该摄像头检测已关闭' : '请选择摄像头'}</span>
          </div>
        )}
      </div>
    </div>
  )
}
