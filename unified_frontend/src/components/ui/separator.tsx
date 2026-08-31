// 文件说明：封装可复用的`separator` 模块 React 基础组件。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

"use client"

import * as React from "react"
import * as SeparatorPrimitive from "@radix-ui/react-separator"

import { cn } from "@/lib/utils"

/**
 * 功能：渲染 `Separator` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<typeof SeparatorPrimitive.Root>）：React 组件属性对象；解构字段包括 className, orientation, horizontal,
 *     decorative, true, props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/ui/button-group.tsx` 的 `ButtonGroupSeparator`
 *         调用本符号；`unified_frontend/src/components/ui/field.tsx` 的 `FieldSeparator`
 *         调用本符号；`unified_frontend/src/components/ui/item.tsx` 的 `ItemSeparator`
 *         调用本符号；`unified_frontend/src/components/ui/sidebar.tsx` 的 `SidebarSeparator` 调用本符号
 *   - 内部调用：`return`、`cn`、`SeparatorPrimitive`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function Separator({
  className,
  orientation = "horizontal",
  decorative = true,
  ...props
}: React.ComponentProps<typeof SeparatorPrimitive.Root>) {
  return (
    <SeparatorPrimitive.Root
      data-slot="separator"
      decorative={decorative}
      orientation={orientation}
      className={cn(
        "bg-border shrink-0 data-[orientation=horizontal]:h-px data-[orientation=horizontal]:w-full data-[orientation=vertical]:h-full data-[orientation=vertical]:w-px",
        className
      )}
      {...props}
    />
  )
}

export { Separator }
