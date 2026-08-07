import type {
  LogisticsChannelReason,
  LogisticsChannelRuntimeStatus,
} from './types'

export type LogisticsChannelStatusEvent = {
  id: string
  reason: Exclude<LogisticsChannelReason, 'unknown' | 'unconfigured' | 'inactive'>
  occurredAt: string
}

export function appendLogisticsStatusEvent(
  events: LogisticsChannelStatusEvent[],
  previousReason: LogisticsChannelReason | null,
  status: Pick<LogisticsChannelRuntimeStatus, 'reason'>,
) {
  if (
    previousReason === null
    || status.reason === previousReason
    || status.reason === 'unknown'
    || status.reason === 'unconfigured'
    || status.reason === 'inactive'
  ) return events

  const occurredAt = new Date().toISOString()
  return [
    { id: `${occurredAt}-${status.reason}`, reason: status.reason, occurredAt },
    ...events,
  ].slice(0, 8)
}

export type LogisticsFramePresentation = {
  state: 'live' | 'stale' | 'error' | 'waiting'
  label: string
  showFrame: boolean
  errorMessage: string | null
}

export function getLogisticsFramePresentation(
  frameUrl: string | null,
  frameError: string | null,
): LogisticsFramePresentation {
  if (frameError && frameUrl) {
    return {
      state: 'stale',
      label: '画面异常 / 最近帧',
      showFrame: true,
      errorMessage: frameError,
    }
  }
  if (frameError) {
    return {
      state: 'error',
      label: '画面异常',
      showFrame: false,
      errorMessage: frameError,
    }
  }
  if (frameUrl) {
    return {
      state: 'live',
      label: '画面在线',
      showFrame: true,
      errorMessage: null,
    }
  }
  return {
    state: 'waiting',
    label: '等待画面',
    showFrame: false,
    errorMessage: null,
  }
}
