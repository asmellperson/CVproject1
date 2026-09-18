import type { InspectionStatus } from '@/lib/security-inspection'

export function inspectionStatusPresentation(status: InspectionStatus | null, requestError: string) {
  if (requestError) return { label: '状态读取失败', error: requestError }
  if (!status) return { label: '正在读取检测状态', error: '' }
  if (!status.running) return { label: '检测服务未运行', error: status.error || '' }
  const health = status.vlm
  if (health.circuit_state === 'open') {
    const retry = health.checking ? '正在重新检查连接' : `${health.retry_after_sec} 秒后自动检查连接`
    return { label: '千问不可用，已暂停判定', error: `${health.last_error}；${retry}。` }
  }
  if (health.reachable === null) return { label: '正在检查千问连接', error: '' }
  if (health.reachable === false) return { label: '千问接口不可用', error: health.last_error || '' }
  if (health.circuit_state === 'half_open') return { label: '千问恢复验证中', error: '' }
  if (health.last_error || status.error) return { label: '判定服务异常', error: health.last_error || status.error || '' }
  return { label: health.last_success ? '检测服务就绪' : '千问接口可达，等待首次判定', error: '' }
}
