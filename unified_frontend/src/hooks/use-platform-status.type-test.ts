// 文件说明：封装`use-platform-status.type-test` 模块的 React 状态与副作用。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import type { ComponentProps } from 'react'
import type { getPlatformStatus, PlatformStatus } from '../lib/api'
import type { HomeSection } from '../sections/HomeSection'
import type { usePlatformStatus } from './use-platform-status'

type Equal<Left, Right> =
  (<Value>() => Value extends Left ? 1 : 2) extends
  (<Value>() => Value extends Right ? 1 : 2)
    ? true
    : false

type AssertTrue<Value extends true> = Value

type ExpectedHomeSectionProps = {
  /**
   * 功能：处理 `onNavigate` 对应的`use-platform-status.type-test` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `page`（string）：`page` 对应的业务输入值
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/sections/HomeSection.tsx` 的 `HomeSection` 调用本符号
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onNavigate: (page: string) => void
  platformStatus: PlatformStatus | null
}

export type UsePlatformStatusContractAssertions = [
  AssertTrue<Equal<Parameters<typeof getPlatformStatus>, [init?: RequestInit]>>,
  AssertTrue<Equal<ReturnType<typeof getPlatformStatus>, Promise<PlatformStatus>>>,
  AssertTrue<Equal<Parameters<typeof usePlatformStatus>, []>>,
  AssertTrue<Equal<ReturnType<typeof usePlatformStatus>, PlatformStatus | null>>,
  AssertTrue<Equal<ComponentProps<typeof HomeSection>, ExpectedHomeSectionProps>>,
]
