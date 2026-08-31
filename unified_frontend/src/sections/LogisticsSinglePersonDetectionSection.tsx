// 文件说明：实现`LogisticsSinglePersonDetectionSection` 模块的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { LogisticsChannelSection } from '@/components/logistics_single_person/LogisticsChannelSection'

/**
 * 功能：渲染 `LogisticsSinglePersonDetectionSection` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：无。
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`LogisticsChannelSection`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function LogisticsSinglePersonDetectionSection() {
  return (
    <LogisticsChannelSection
      feature="detect_logistics_single_person"
      title="物流通道单人检测监控与配置"
    />
  )
}

export default LogisticsSinglePersonDetectionSection
