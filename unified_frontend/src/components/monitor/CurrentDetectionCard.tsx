import { Activity } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { DetectionStatus } from './useDetectionStatus'

const REASONS: Record<string, string> = {
  normal: '当前未触发异常', intrusion: '警戒线入侵侧有人', unconfigured: '请先配置判定线',
  phone_confirmed: '检测到持续使用手机', confirming: '候选结果持续确认中', loitering: '检测到逗留超时',
  background_initializing: '正在建立参考背景', background_unstable: '画面扰动，等待稳定',
  door_changed: '持续变化已确认，等待报警时长', door_alarm: '门状态持续变化，已达到报警条件',
  inference_error: '推理失败，暂无有效判定', offline: '摄像头离线', disabled: '检测未运行',
  stale: '检测结果已过期', unknown: '等待有效检测结果',
}

export function CurrentDetectionCard({ feature, status, error }: { feature: string; status?: DetectionStatus | null; error?: string }) {
  const valid = status?.online && status.updated_at && !['inference_error', 'unknown', 'stale', 'disabled', 'offline'].includes(status.reason)
  return <Card className="rounded-2xl border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
    <CardHeader className="p-4 pb-3 sm:p-5 sm:pb-3"><CardTitle className="flex items-center gap-2 text-base"><Activity className="h-4 w-4" />当前检测结果</CardTitle></CardHeader>
    <CardContent className="space-y-3 px-4 pb-4 text-sm sm:px-5 sm:pb-5">
      <p role="status" className={error || !valid ? 'text-amber-700 dark:text-amber-300' : status?.alarm ? 'text-rose-600 dark:text-rose-300' : 'text-emerald-700 dark:text-emerald-300'}>
        {error || REASONS[status?.reason || 'unknown'] || status?.reason}
      </p>
      {valid && <>
        {status.count !== null && <p>{feature === 'detect_face' ? '当前人脸' : feature === 'detect_phone' ? '手机候选' : '当前人员'}：{status.count}</p>}
        {status.duration_seconds != null && <p>{feature === 'detect_door' ? '已确认持续变化' : feature === 'detect_phone' ? '最长持续时间' : '最长逗留时间'}：{status.duration_seconds.toFixed(1)} 秒{status.threshold_seconds != null && ` / 阈值 ${status.threshold_seconds} 秒`}</p>}
        {status.change_ratio != null && <p>相对背景变化：{(status.change_ratio * 100).toFixed(1)}% · 连续确认 {status.hits ?? 0} 次</p>}
        {status.details?.map((detail) => <div key={detail.label} className="rounded-xl border border-slate-200 p-3 dark:border-slate-700">
          <p className="font-medium">{detail.label} · {REASONS[detail.state] || detail.state}</p>
          <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-slate-500 dark:text-slate-400">
            {detail.confidence != null && <span>置信度 {(detail.confidence * 100).toFixed(1)}%</span>}
            {detail.duration_seconds != null && <span>持续 {detail.duration_seconds.toFixed(1)} 秒</span>}
            {detail.hits != null && <span>连续命中 {detail.hits} 次</span>}
          </div>
        </div>)}
      </>}
      {status?.updated_at && <p className="text-xs text-slate-500 dark:text-slate-400">采样于 {new Date(status.updated_at).toLocaleTimeString('zh-CN', { hour12: false })}</p>}
    </CardContent>
  </Card>
}
