// 文件说明：实现认证授权相关的基础能力。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { createContext } from 'react'
import type { Department, UserRole } from '@/auth/permissions'

export type AuthUser = {
  employee_id: string
  name: string
  role: UserRole | string
  department?: Department | string | null
  departments?: Array<Department | string>
  capabilities?: {
    view_access_audit?: boolean
  }
}

export type AuthContextValue = {
  user: AuthUser | null
  loading: boolean
  isAdmin: boolean
  /**
   * 功能：实现 `login` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `account`（string）：`account` 对应的业务输入值
   *   - `password`（string）：`password` 对应的业务输入值
   * 返回：Promise<void>；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  login: (account: string, password: string) => Promise<void>
  /**
   * 功能：实现 `changePassword` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `currentPassword`（string）：`currentPassword` 对应的业务输入值
   *   - `newPassword`（string）：`newPassword` 对应的业务输入值
   * 返回：Promise<void>；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>
  /**
   * 功能：实现 `logout` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：Promise<void>；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  logout: () => Promise<void>
  /**
   * 功能：实现 `refreshMe` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：Promise<void>；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  refreshMe: () => Promise<void>
  /**
   * 功能：处理 `handleUnauthorized` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  handleUnauthorized: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)
