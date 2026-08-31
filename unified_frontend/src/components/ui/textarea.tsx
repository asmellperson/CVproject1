// 文件说明：封装可复用的`textarea` 模块 React 基础组件。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * 功能：渲染 `Textarea` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<"textarea">）：React 组件属性对象；解构字段包括 className, props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/ui/input-group.tsx` 的 `InputGroupTextarea` 调用本符号
 *   - 内部调用：`return`、`cn`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "border-input placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive dark:bg-input/30 flex field-sizing-content min-h-16 w-full rounded-md border bg-transparent px-3 py-2 text-base shadow-xs transition-[color,box-shadow] outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
