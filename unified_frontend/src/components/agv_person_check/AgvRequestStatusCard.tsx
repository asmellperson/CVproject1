import { Activity } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/utils'
import type { AgvMonitorStatus, AgvRequestStatus } from './api'
import { useAgvRequestStatus } from './useAgvRequestStatus'

const STATES: Record<AgvMonitorStatus['state'], string> = {
  waiting: '等待请求', detecting: '正在检测', returning: '正在回传',
  offline: '摄像头离线', disabled: '检测未启用', unavailable: '检测服务未运行',
}

function formatTime(value: string | null) {
  if (!value) return '--'
  const time = new Date(value)
  return Number.isFinite(time.getTime()) ? time.toLocaleString('zh-CN', { hour12: false }) : '--'
}

function deliveryText(result: AgvRequestStatus) {
  const code = result.delivery_status_code === null ? '' : ` · HTTP ${result.delivery_status_code}`
  switch (result.delivery_state) {
    case 'ready': return `同步响应已生成${code}`
    case 'sending': return '正在发送回调'
    case 'succeeded': return `回调成功${code}`
    case 'failed': return `回调失败${code}`
    case 'not_sent': return '未发送判定结果'
    default: return '等待回传'
  }
}

function LatestResult({ result }: { result: AgvRequestStatus }) {
  const completed = result.state === 'completed' && result.person_present !== null
  const label = completed ? (result.person_present ? '有人' : '无人') : result.state === 'cancelled' ? '已取消' : '检测失败'
  return (
    <div className="space-y-3 border-t border-slate-100 pt-3 dark:border-slate-800">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-slate-600 dark:text-slate-300">最近一次结果</span>
        <Badge className={cn('border-0 px-3 py-1 text-lg font-bold shadow-none', completed && !result.person_present
          ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300'
          : 'bg-rose-50 text-rose-700 dark:bg-rose-950/60 dark:text-rose-300')}>{label}</Badge>
      </div>
      <dl className="space-y-2 text-sm">
        <div className="flex flex-wrap justify-between gap-1"><dt className="text-slate-400">完成时间</dt><dd>{formatTime(result.finished_at)}</dd></div>
        <div className="flex flex-wrap justify-between gap-1"><dt className="text-slate-400">检测耗时</dt><dd>{result.duration_seconds.toFixed(2)} 秒 · {result.sample_count}/{result.sample_target} 帧</dd></div>
        <div className="flex flex-wrap justify-between gap-1"><dt className="text-slate-400">回传状态</dt><dd className={result.delivery_state === 'failed' ? 'text-rose-600 dark:text-rose-300' : ''}>{deliveryText(result)}</dd></div>
      </dl>
      {result.error && <p className="break-words text-sm text-rose-600 dark:text-rose-300">{result.error}</p>}
      {result.delivery_error && <p className="break-words text-sm text-rose-600 dark:text-rose-300">{result.delivery_error}</p>}
      <details className="rounded-lg border border-slate-200 px-3 dark:border-slate-700">
        <summary className="cursor-pointer py-3 text-sm text-slate-500 dark:text-slate-400">请求详情</summary>
        <div className="space-y-3 pb-3">
          <dl className="space-y-1 text-xs"><dt className="text-slate-400">请求 ID</dt><dd className="break-all font-mono">{result.request_id}</dd></dl>
          {result.response_body !== null && (
            <div className="space-y-1.5">
              <p className="text-xs text-slate-400">{result.mode === 'callback' ? '回调内容' : '返回内容'}</p>
              <pre className="max-h-44 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-slate-50 p-3 font-mono text-xs text-slate-700 dark:bg-slate-950 dark:text-slate-300">{JSON.stringify(result.response_body, null, 2)}</pre>
            </div>
          )}
        </div>
      </details>
    </div>
  )
}

export function AgvRequestStatusCard({ cameraKey }: { cameraKey: string }) {
  const result = useAgvRequestStatus(cameraKey)
  const status = result?.value
  const active = status?.active_request
  const busy = status?.state === 'detecting' || status?.state === 'returning'
  const label = !cameraKey ? '请选择摄像头' : result?.error ? '状态读取失败' : status ? STATES[status.state] : '读取中'

  return (
    <Card className="gap-0 rounded-2xl border border-slate-200/70 bg-white py-0 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <CardHeader className="p-4 pb-3 sm:p-5 sm:pb-3">
        <CardTitle className="flex items-center gap-3 text-base font-bold text-slate-950 dark:text-slate-100">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EAF0FE] text-[#1B3FA0] dark:bg-blue-950/60 dark:text-blue-300"><Activity className="h-4 w-4" /></span>
          请求与结果
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 px-4 pb-4 text-sm text-slate-700 dark:text-slate-300 sm:px-5 sm:pb-5">
        <div className="flex items-center justify-between gap-2" role="status" aria-live="polite">
          <span className="text-sm text-slate-500 dark:text-slate-400">当前状态</span>
          <Badge className={cn('gap-1.5 border-0 shadow-none', busy
            ? 'bg-blue-50 text-blue-700 dark:bg-blue-950/60 dark:text-blue-300'
            : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300')}>
            {(busy || (cameraKey && !result)) && <Spinner aria-label="正在处理请求" />}{label}
          </Badge>
        </div>
        {result?.error && <p className="text-xs text-rose-600 dark:text-rose-300">{result.error}</p>}
        {busy && active && (
          <div className="space-y-1.5 text-xs">
            <p>已采样 {active.sample_count}/{active.sample_target} 帧 · 已用 {active.duration_seconds.toFixed(1)} 秒</p>
            <p className="text-slate-400">开始于 {formatTime(active.started_at)}</p>
          </div>
        )}
        {status?.latest_result && <LatestResult result={status.latest_result} />}
      </CardContent>
    </Card>
  )
}
