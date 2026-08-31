// 文件说明：实现`AiVisionPresetActions` 模块的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'

type AiVisionPresetActionsProps = {
  disabled?: boolean
  /**
   * 功能：处理 `onApplyDay` 对应的`AiVisionPresetActions` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onApplyDay: () => void
  /**
   * 功能：处理 `onApplyNight` 对应的`AiVisionPresetActions` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onApplyNight: () => void
}

/**
 * 功能：渲染 `AiVisionPresetActions` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（AiVisionPresetActionsProps）：React 组件属性对象；解构字段包括 disabled, onApplyDay, onApplyNight
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`Button`、`Sun`、`Moon`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function AiVisionPresetActions({ disabled, onApplyDay, onApplyNight }: AiVisionPresetActionsProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
      <div>
        <div className="text-sm font-bold text-[#071d3d] dark:text-slate-100">参数预设</div>
        <div className="mt-1 text-xs font-medium text-slate-500">应用后会先写入表单，确认无误后再保存。</div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" className="gap-2" onClick={onApplyDay} disabled={disabled}>
          <Sun className="h-4 w-4" />
          白天
        </Button>
        <Button variant="outline" className="gap-2" onClick={onApplyNight} disabled={disabled}>
          <Moon className="h-4 w-4" />
          夜间
        </Button>
      </div>
    </div>
  )
}
