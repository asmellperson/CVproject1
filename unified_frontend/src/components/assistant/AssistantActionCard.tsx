import type { AssistantAction } from './types'

const labels: Record<string, string> = { name: '名称', fps: '采集 FPS', enabled: '启用', enable: '启用', max_restart: '重连次数',
  alarm_interval: '报警间隔', detection_start: '检测开始', detection_end: '检测结束', weekdays: '报警星期', start: '报警开始', end: '报警结束' }
const statusLabels: Record<AssistantAction['status'], string> = { saved: '已保存', executing: '正在执行', failed: '执行失败', unknown: '结果待核对', changed: '保存后已有变化' }

function fields(value: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(value).flatMap(([key, item]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return item && typeof item === 'object' && !Array.isArray(item) ? fields(item as Record<string, unknown>, path) : [path]
  })
}
function at(value: Record<string, unknown> | null, path: string): string {
  const found = path.split('.').reduce<unknown>((current, key) => current && typeof current === 'object' ? (current as Record<string, unknown>)[key] : undefined, value)
  if (found === undefined) return '—'
  if (typeof found === 'boolean') return found ? '开启' : '关闭'
  return typeof found === 'string' ? found : JSON.stringify(found)
}

export function AssistantActionCard({ action }: { action: AssistantAction }) {
  return <details className="overflow-hidden rounded-xl border border-slate-200 bg-white text-xs dark:border-slate-700 dark:bg-slate-900">
    <summary className="cursor-pointer px-3 py-3 leading-5">
      <span className={action.status === 'saved' ? 'font-medium text-emerald-700 dark:text-emerald-400' : 'font-medium text-amber-700 dark:text-amber-400'}>{statusLabels[action.status]}</span>
      <span className="ml-2 break-words text-slate-700 dark:text-slate-200">{action.resource.name}</span>
    </summary>
    <div className="space-y-3 border-t border-slate-100 p-3 dark:border-slate-800">
      <p className="whitespace-pre-wrap break-words text-slate-500 dark:text-slate-400">{action.detail || '等待业务服务返回结果'}</p>
      <div className="overflow-x-auto"><table className="w-full text-left"><thead><tr className="text-slate-500 dark:text-slate-400"><th className="p-1">参数</th><th className="p-1">修改前</th><th className="p-1">实际结果</th></tr></thead>
        <tbody>{fields(action.changes).map((path) => <tr key={path} className="border-t border-slate-100 align-top dark:border-slate-800">
          <td className="p-1.5" title={path}>{labels[path.split('.').at(-1) ?? ''] ?? path}</td>
          <td className="max-w-48 break-words p-1.5 text-slate-500 dark:text-slate-400">{at(action.before, path)}</td>
          <td className="max-w-48 break-words p-1.5">{action.after ? at(action.after, path) : '待确认'}</td>
        </tr>)}</tbody></table></div>
      {action.after && action.resource.kind === 'camera_creation' && <p>摄像头：{String(action.after.shm_name ?? '')}</p>}
      <p className="text-slate-400">操作编号：{action.id}</p>
    </div>
  </details>
}
