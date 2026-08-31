// 文件说明：封装可复用的`spinner` 模块 React 基础组件。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { Loader2Icon } from "lucide-react"

import { cn } from "@/lib/utils"

/**
 * 功能：渲染 `Spinner` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<"svg">）：React 组件属性对象；解构字段包括 className, props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`cn`、`Loader2Icon`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function Spinner({ className, ...props }: React.ComponentProps<"svg">) {
  return (
    <Loader2Icon
      role="status"
      aria-label="Loading"
      className={cn("size-4 animate-spin", className)}
      {...props}
    />
  )
}

export { Spinner }
