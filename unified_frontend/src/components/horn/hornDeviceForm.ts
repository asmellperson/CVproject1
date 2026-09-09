import type { HornConnectionInput, HornDevice, HornState, HornWrite } from '@/lib/horns'

export const HORN_STATE_LABELS: Record<HornState, string> = {
  online: '在线', offline: '离线', connecting: '连接中', failed: '连接失败',
  disabled: '已停用', stopping: '停止中', stopped: '已停止', pending: '等待同步', not_started: '服务未启动',
}

export function hornDraft(device: HornDevice | null): HornWrite & { password: string } {
  return {
    name: device?.name ?? '', url: device?.url ?? '', username: device?.username ?? 'admin',
    password: '', enable: device?.enable ?? false, description: device?.description ?? '',
  }
}

export function validateHornDraft(draft: HornWrite, editing: boolean, connectionOnly = false): string | null {
  if (!connectionOnly && !draft.name.trim()) return '请输入设备名称。'
  if (!connectionOnly && draft.name.trim().length > 100) return '设备名称不能超过 100 个字符。'
  if (!draft.username.trim() || draft.username.trim().length > 100) return '请输入有效的设备用户名（最多 100 个字符）。'
  try {
    const url = new URL(draft.url.trim())
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash
      || /\s|\\/.test(draft.url.trim()) || draft.url.trim().length > 500) throw new Error('invalid URL')
  } catch {
    return '请输入 HTTP/HTTPS 设备地址，不要在地址中填写账号、密码或查询参数。'
  }
  if (!editing && !draft.password) return '新建设备必须输入密码。'
  if ((draft.password?.length ?? 0) > 200) return '密码不能超过 200 个字符。'
  if (!connectionOnly && (draft.description?.length ?? 0) > 10000) return '备注不能超过 10000 个字符。'
  return null
}

export function hornWritePayload(draft: HornWrite): HornWrite {
  return {
    name: draft.name.trim(), url: draft.url.trim(), username: draft.username.trim(),
    enable: draft.enable, description: draft.description?.trim() || null,
    // 编辑留空时不发送 password，密码中的有效空格不做 trim。
    ...(draft.password ? { password: draft.password } : {}),
  }
}

export function hornConnectionPayload(draft: HornWrite, id?: number): HornConnectionInput {
  return {
    ...(id === undefined ? {} : { horn_id: id }),
    url: draft.url.trim(), username: draft.username.trim(),
    ...(draft.password ? { password: draft.password } : {}),
  }
}
