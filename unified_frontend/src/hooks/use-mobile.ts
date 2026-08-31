// 文件说明：封装`use-mobile` 模块的 React 状态与副作用。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import * as React from "react"

const MOBILE_BREAKPOINT = 768

/**
 * 功能：封装 `useIsMobile` React Hook，向调用组件提供`use-mobile` 模块状态与操作
 * 参数：无。
 * 返回：boolean（由实现推断）；返回条件是否成立。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/ui/sidebar.tsx` 的 `SidebarProvider` 调用本符号；`unified_frontend/src/App.tsx` 的 `App` 调用本符号
 *   - 内部调用：`useState`、`useEffect`、`matchMedia`、`setIsMobile`、`addEventListener`、`return`、`removeEventListener`。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染；会读取或修改浏览器全局对象/DOM 状态。
 */
export function useIsMobile() {
  const [isMobile, setIsMobile] = React.useState<boolean | undefined>(undefined)

  React.useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
    const onChange = () => {
      setIsMobile(window.innerWidth < MOBILE_BREAKPOINT)
    }
    mql.addEventListener("change", onChange)
    setIsMobile(window.innerWidth < MOBILE_BREAKPOINT)
    return () => mql.removeEventListener("change", onChange)
  }, [])

  return !!isMobile
}
