// 文件说明：封装可复用的`pagination` 模块 React 基础组件。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import * as React from "react"
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  MoreHorizontalIcon,
} from "lucide-react"

import { cn } from "@/lib/utils"
import { buttonVariants, type Button } from "@/components/ui/button"

/**
 * 功能：渲染 `Pagination` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<"nav">）：React 组件属性对象；解构字段包括 className, props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`cn`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function Pagination({ className, ...props }: React.ComponentProps<"nav">) {
  return (
    <nav
      role="navigation"
      aria-label="pagination"
      data-slot="pagination"
      className={cn("mx-auto flex w-full justify-center", className)}
      {...props}
    />
  )
}

/**
 * 功能：渲染 `PaginationContent` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<"ul">）：React 组件属性对象；解构字段包括 className, props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`cn`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function PaginationContent({
  className,
  ...props
}: React.ComponentProps<"ul">) {
  return (
    <ul
      data-slot="pagination-content"
      className={cn("flex flex-row items-center gap-1", className)}
      {...props}
    />
  )
}

/**
 * 功能：渲染 `PaginationItem` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<"li">）：React 组件属性对象；解构字段包括 props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function PaginationItem({ ...props }: React.ComponentProps<"li">) {
  return <li data-slot="pagination-item" {...props} />
}

type PaginationLinkProps = {
  isActive?: boolean
} & Pick<React.ComponentProps<typeof Button>, "size"> &
  React.ComponentProps<"a">

/**
 * 功能：渲染 `PaginationLink` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（PaginationLinkProps）：React 组件属性对象；解构字段包括 className, isActive, size, icon, props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/ui/pagination.tsx` 的 `PaginationPrevious`
 *         调用本符号；`unified_frontend/src/components/ui/pagination.tsx` 的 `PaginationNext` 调用本符号
 *   - 内部调用：`return`、`cn`、`buttonVariants`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function PaginationLink({
  className,
  isActive,
  size = "icon",
  ...props
}: PaginationLinkProps) {
  return (
    <a
      aria-current={isActive ? "page" : undefined}
      data-slot="pagination-link"
      data-active={isActive}
      className={cn(
        buttonVariants({
          variant: isActive ? "outline" : "ghost",
          size,
        }),
        className
      )}
      {...props}
    />
  )
}

/**
 * 功能：渲染 `PaginationPrevious` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<typeof PaginationLink>）：React 组件属性对象；解构字段包括 className, props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`cn`、`PaginationLink`、`ChevronLeftIcon`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function PaginationPrevious({
  className,
  ...props
}: React.ComponentProps<typeof PaginationLink>) {
  return (
    <PaginationLink
      aria-label="Go to previous page"
      size="default"
      className={cn("gap-1 px-2.5 sm:pl-2.5", className)}
      {...props}
    >
      <ChevronLeftIcon />
      <span className="hidden sm:block">Previous</span>
    </PaginationLink>
  )
}

/**
 * 功能：渲染 `PaginationNext` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<typeof PaginationLink>）：React 组件属性对象；解构字段包括 className, props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`cn`、`PaginationLink`、`ChevronRightIcon`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function PaginationNext({
  className,
  ...props
}: React.ComponentProps<typeof PaginationLink>) {
  return (
    <PaginationLink
      aria-label="Go to next page"
      size="default"
      className={cn("gap-1 px-2.5 sm:pr-2.5", className)}
      {...props}
    >
      <span className="hidden sm:block">Next</span>
      <ChevronRightIcon />
    </PaginationLink>
  )
}

/**
 * 功能：渲染 `PaginationEllipsis` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（React.ComponentProps<"span">）：React 组件属性对象；解构字段包括 className, props
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`cn`、`MoreHorizontalIcon`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function PaginationEllipsis({
  className,
  ...props
}: React.ComponentProps<"span">) {
  return (
    <span
      aria-hidden
      data-slot="pagination-ellipsis"
      className={cn("flex size-9 items-center justify-center", className)}
      {...props}
    >
      <MoreHorizontalIcon className="size-4" />
      <span className="sr-only">More pages</span>
    </span>
  )
}

export {
  Pagination,
  PaginationContent,
  PaginationLink,
  PaginationItem,
  PaginationPrevious,
  PaginationNext,
  PaginationEllipsis,
}
