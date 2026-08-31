// 文件说明：封装可复用的`dialog` 模块 React 基础组件。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import * as React from "react"
import * as DialogPrimitive from "@radix-ui/react-dialog"
import { XIcon } from "lucide-react"

import { cn } from "@/lib/utils"

/**
 * 功能：渲染 `Dialog` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<typeof DialogPrimitive.Root>）：React 组件属性对象；解构字段包括 props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/ui/command.tsx` 的 `CommandDialog` 调用本符号
 *   - 内部调用：`DialogPrimitive`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function Dialog({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Root>) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />
}

/**
 * 功能：渲染 `DialogTrigger` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<typeof DialogPrimitive.Trigger>）：React 组件属性对象；解构字段包括 props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`DialogPrimitive`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function DialogTrigger({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Trigger>) {
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />
}

/**
 * 功能：渲染 `DialogPortal` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<typeof DialogPrimitive.Portal>）：React 组件属性对象；解构字段包括 props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/ui/dialog.tsx` 的 `DialogContent` 调用本符号
 *   - 内部调用：`DialogPrimitive`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function DialogPortal({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Portal>) {
  return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />
}

/**
 * 功能：渲染 `DialogClose` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<typeof DialogPrimitive.Close>）：React 组件属性对象；解构字段包括 props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`DialogPrimitive`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function DialogClose({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Close>) {
  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />
}

/**
 * 功能：渲染 `DialogOverlay` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<typeof DialogPrimitive.Overlay>）：React 组件属性对象；解构字段包括 className, props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/ui/dialog.tsx` 的 `DialogContent` 调用本符号
 *   - 内部调用：`return`、`cn`、`DialogPrimitive`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function DialogOverlay({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay
      data-slot="dialog-overlay"
      className={cn(
        "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 fixed inset-0 z-50 bg-black/50",
        className
      )}
      {...props}
    />
  )
}

/**
 * 功能：渲染 `DialogContent` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 className, children, showCloseButton, true, props, React, ComponentProps, typeof
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/ui/command.tsx` 的 `CommandDialog` 调用本符号
 *   - 内部调用：`return`、`cn`、`calc`、`not`、`DialogPortal`、`DialogOverlay`、`DialogPrimitive`、`XIcon`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function DialogContent({
  className,
  children,
  showCloseButton = true,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & {
  showCloseButton?: boolean
}) {
  return (
    <DialogPortal data-slot="dialog-portal">
      <DialogOverlay />
      <DialogPrimitive.Content
        data-slot="dialog-content"
        className={cn(
          "bg-background data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 fixed top-[50%] left-[50%] z-50 grid w-full max-w-[calc(100%-2rem)] translate-x-[-50%] translate-y-[-50%] gap-4 rounded-lg border p-6 shadow-lg duration-200 outline-none sm:max-w-lg",
          className
        )}
        {...props}
      >
        {children}
        {showCloseButton && (
          <DialogPrimitive.Close
            data-slot="dialog-close"
            className="ring-offset-background focus:ring-ring data-[state=open]:bg-accent data-[state=open]:text-muted-foreground absolute top-4 right-4 rounded-xs opacity-70 transition-opacity hover:opacity-100 focus:ring-2 focus:ring-offset-2 focus:outline-hidden disabled:pointer-events-none [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4"
          >
            <XIcon />
            <span className="sr-only">Close</span>
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPortal>
  )
}

/**
 * 功能：渲染 `DialogHeader` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<"div">）：React 组件属性对象；解构字段包括 className, props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/ui/command.tsx` 的 `CommandDialog` 调用本符号
 *   - 内部调用：`return`、`cn`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-header"
      className={cn("flex flex-col gap-2 text-center sm:text-left", className)}
      {...props}
    />
  )
}

/**
 * 功能：渲染 `DialogFooter` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<"div">）：React 组件属性对象；解构字段包括 className, props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`cn`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function DialogFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-footer"
      className={cn(
        "flex flex-col-reverse gap-2 sm:flex-row sm:justify-end",
        className
      )}
      {...props}
    />
  )
}

/**
 * 功能：渲染 `DialogTitle` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<typeof DialogPrimitive.Title>）：React 组件属性对象；解构字段包括 className, props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/ui/command.tsx` 的 `CommandDialog` 调用本符号
 *   - 内部调用：`return`、`cn`、`DialogPrimitive`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function DialogTitle({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      data-slot="dialog-title"
      className={cn("text-lg leading-none font-semibold", className)}
      {...props}
    />
  )
}

/**
 * 功能：渲染 `DialogDescription` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<typeof DialogPrimitive.Description>）：React 组件属性对象；解构字段包括 className, props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/ui/command.tsx` 的 `CommandDialog` 调用本符号
 *   - 内部调用：`return`、`cn`、`DialogPrimitive`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description
      data-slot="dialog-description"
      className={cn("text-muted-foreground text-sm", className)}
      {...props}
    />
  )
}

export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
}
