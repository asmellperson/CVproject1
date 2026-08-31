// 文件说明：封装`use-theme` 模块的 React 状态与副作用。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { useCallback, useEffect, useState } from 'react'

type Theme = 'light' | 'dark'

const STORAGE_KEY = 'unified-frontend-theme'

/**
 * 功能：读取或查询 `readInitialTheme` 对应的`use-theme` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：Theme；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/hooks/use-theme.ts` 的 `useTheme` 调用本符号
 *   - 内部调用：`getItem`。
 * 副作用/注意事项：会读写浏览器本地存储；会读取或修改浏览器全局对象/DOM 状态。
 */
function readInitialTheme(): Theme {
  if (typeof window === 'undefined') return 'dark'
  const stored = window.localStorage.getItem(STORAGE_KEY)
  if (stored === 'light' || stored === 'dark') return stored
  return 'dark'
}

/**
 * 功能：实现 `applyTheme` 对应的`use-theme` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `theme`（Theme）：`theme` 对应的业务输入值
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/hooks/use-theme.ts` 的 `useTheme` 调用本符号
 *   - 内部调用：`add`、`remove`。
 * 副作用/注意事项：会读取或修改浏览器全局对象/DOM 状态。
 */
function applyTheme(theme: Theme) {
  const root = document.documentElement
  if (theme === 'dark') root.classList.add('dark')
  else root.classList.remove('dark')
  root.style.colorScheme = theme
}

/**
 * 功能：封装 `useTheme` React Hook，向调用组件提供`use-theme` 模块状态与操作
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`useState`、`readInitialTheme`、`useEffect`、`applyTheme`、`setItem`、`useCallback`、`setThemeState`、`Theme`。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染；会读写浏览器本地存储；会读取或修改浏览器全局对象/DOM 状态。
 */
export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(() => (typeof window === 'undefined' ? 'dark' : readInitialTheme()))

  useEffect(() => {
    applyTheme(theme)
    window.localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => (prev === 'dark' ? 'light' : 'dark'))
  }, [])

  return { theme, setTheme: setThemeState, toggleTheme }
}
