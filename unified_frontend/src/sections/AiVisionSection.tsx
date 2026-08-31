// 文件说明：实现`AiVisionSection` 模块的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { ExternalLink, Shield, Workflow } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { AIVISION_URL } from '@/lib/aivision'

/**
 * 功能：渲染 `AiVisionSection` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：无。
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`Badge`、`Shield`、`Button`、`ExternalLink`、`Card`、`CardHeader`、`CardTitle`、`CardContent`、`Workflow`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function AiVisionSection() {
  return (
    <div className="space-y-6 text-slate-950 dark:text-slate-100">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900 dark:text-slate-100">AiVision</h2>
          <p className="text-slate-500">当前阶段采用低侵入接入，优先保留其现有 Gradio 页面能力。</p>
        </div>

        <div className="flex w-full flex-wrap items-center gap-3 sm:w-auto">
          <Badge variant="outline" className="gap-2">
            <Shield className="h-4 w-4" />
            低风险接入
          </Badge>
          <Button asChild className="gap-2">
            <a href={AIVISION_URL} target="_blank" rel="noreferrer">
              新窗口打开
              <ExternalLink className="h-4 w-4" />
            </a>
          </Button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.2fr_2fr]">
        <Card className="dark:border-slate-800 dark:bg-slate-900">
          <CardHeader>
            <CardTitle className="text-lg">接入说明</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm leading-6 text-slate-600 dark:text-slate-300">
            <p>AiVision 当前是独立 Gradio 应用，直接深度嵌入到 React 组件树内的成本和耦合都偏高。</p>
            <p>本轮先使用 iframe + 外链双入口方式接入，先解决统一入口与导航，不改动其核心页面结构。</p>
            <p>后续如果需要统一统计或报警总览，再补极少量只读接口，由统一前端聚合展示。</p>
            <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-950/60">
              <div className="mb-2 flex items-center gap-2 font-medium text-slate-900 dark:text-slate-100">
                <Workflow className="h-4 w-4" />
                下一步建议
              </div>
              <p>优先补一个只读概览接口，例如 AiVision 告警计数、设备状态、最近事件列表，再接入聚合页。</p>
            </div>
          </CardContent>
        </Card>

        <Card className="overflow-hidden dark:border-slate-800 dark:bg-slate-900">
          <CardHeader className="border-b bg-slate-50 dark:border-slate-800 dark:bg-slate-900">
            <CardTitle className="text-lg">AiVision 嵌入视图</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <iframe
              title="AiVision"
              src={AIVISION_URL}
              className="h-[70vh] min-h-[420px] w-full bg-white dark:bg-slate-950 lg:h-[720px]"
              referrerPolicy="no-referrer"
            />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
