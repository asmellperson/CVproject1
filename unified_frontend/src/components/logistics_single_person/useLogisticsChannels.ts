import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'

import { useSerialPoll } from '@/hooks/use-serial-poll'
import {
  LOGISTICS_CHANNEL_QUERY_INVALIDATED,
  fetchLogisticsChannelFrame,
  getLogisticsChannelAlarms,
  getLogisticsChannel,
  getLogisticsChannelStatistics,
  getLogisticsChannelStatus,
  listLogisticsChannels,
  replaceLogisticsChannelFrameObjectUrl,
  revokeLogisticsChannelFrameObjectUrl,
  type LogisticsChannelQueryInvalidation,
} from './api'
import type {
  LogisticsChannel,
  LogisticsChannelDetail,
  LogisticsChannelAlarm,
  LogisticsChannelReason,
  LogisticsChannelRuntimeStatus,
  LogisticsChannelStatistics,
  LogisticsFeatureName,
} from './types'

const CHANNEL_LIST_POLL_INTERVAL_MS = 5000
export const STATUS_POLL_INTERVAL_MS = 1000
export const SUMMARY_POLL_INTERVAL_MS = 5000
export const FRAME_POLL_INTERVAL_MS = 200
const JSON_REQUEST_TIMEOUT_MS = 8000
const FRAME_REQUEST_TIMEOUT_MS = 5000

type LogisticsChannelInvalidationEvent = CustomEvent<LogisticsChannelQueryInvalidation>

function isToday(value: string | null, now = new Date()) {
  if (!value) return false
  const date = new Date(value)
  return !Number.isNaN(date.getTime())
    && date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate()
}

export function useLogisticsChannels(feature: LogisticsFeatureName, enabled = true) {
  const [channels, setChannels] = useState<LogisticsChannel[]>([])
  const [selectedChannelDetail, setSelectedChannelDetail] = useState<LogisticsChannelDetail | null>(null)
  const [selectedChannelId, setSelectedChannelId] = useState<number | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [error, setError] = useState<string | null>(null)
  const [listRevision, refresh] = useReducer((value: number) => value + 1, 0)
  const [detailRevision, refreshSelectedChannel] = useReducer((value: number) => value + 1, 0)
  const currentFeatureRef = useRef(feature)
  const currentSelectedChannelIdRef = useRef(selectedChannelId)

  useEffect(() => {
    currentFeatureRef.current = feature
    currentSelectedChannelIdRef.current = selectedChannelId
  }, [feature, selectedChannelId])

  const loadChannels = useCallback(async (signal?: AbortSignal) => {
    const requestedFeature = feature
    try {
      const response = await listLogisticsChannels(requestedFeature, { signal })
      if (currentFeatureRef.current !== requestedFeature) return
      setChannels(response.items)
      setSelectedChannelId((current) => {
        if (current !== null && response.items.some((channel) => channel.id === current)) {
          return current
        }
        return response.items[0]?.id ?? null
      })
      setError(null)
    } catch (reason) {
      if (signal?.aborted || currentFeatureRef.current !== requestedFeature) return
      setError(reason instanceof Error ? reason.message : '物流通道加载失败')
    } finally {
      if (currentFeatureRef.current === requestedFeature) setLoading(false)
    }
  }, [feature])

  const loadSelectedChannel = useCallback(async (signal?: AbortSignal) => {
    if (selectedChannelId === null) return
    const requestedFeature = feature
    const requestedChannelId = selectedChannelId
    try {
      const detail = await getLogisticsChannel(requestedFeature, requestedChannelId, { signal })
      if (
        currentFeatureRef.current !== requestedFeature
        || requestedChannelId !== currentSelectedChannelIdRef.current
      ) return
      setSelectedChannelDetail(detail)
      setError(null)
    } catch (reason) {
      if (signal?.aborted || currentFeatureRef.current !== requestedFeature) return
      setError(reason instanceof Error ? reason.message : '物流通道详情加载失败')
    }
  }, [feature, selectedChannelId])

  useEffect(() => {
    currentFeatureRef.current = feature
    setChannels([])
    setSelectedChannelDetail(null)
    setSelectedChannelId(null)
    setError(null)
    setLoading(enabled)
  }, [enabled, feature])

  useEffect(() => {
    setSelectedChannelDetail(null)
  }, [feature, selectedChannelId])

  useSerialPoll(
    async (signal) => loadChannels(signal),
    {
      intervalMs: CHANNEL_LIST_POLL_INTERVAL_MS,
      timeoutMs: JSON_REQUEST_TIMEOUT_MS,
      enabled,
      restartKey: `${feature}:${listRevision}`,
    },
  )

  useSerialPoll(loadSelectedChannel, {
    intervalMs: CHANNEL_LIST_POLL_INTERVAL_MS,
    timeoutMs: JSON_REQUEST_TIMEOUT_MS,
    enabled: enabled && selectedChannelId !== null,
    restartKey: `${feature}:${selectedChannelId ?? ''}:${detailRevision}`,
  })

  useEffect(() => {
    if (!enabled) return
    const onInvalidated = (rawEvent: Event) => {
      const event = rawEvent as LogisticsChannelInvalidationEvent
      if (event.detail.feature !== feature) return
      refresh()
      if (
        selectedChannelId !== null
        && (event.detail.channelId === undefined || event.detail.channelId === selectedChannelId)
      ) refreshSelectedChannel()
    }
    window.addEventListener(LOGISTICS_CHANNEL_QUERY_INVALIDATED, onInvalidated)
    return () => window.removeEventListener(LOGISTICS_CHANNEL_QUERY_INVALIDATED, onInvalidated)
  }, [enabled, feature, selectedChannelId])

  const selectedChannel = useMemo(
    () => channels.find((channel) => channel.id === selectedChannelId) ?? null,
    [channels, selectedChannelId],
  )

  return {
    channels,
    selectedChannel,
    selectedChannelDetail,
    selectedChannelId,
    setSelectedChannelId,
    loading,
    error,
    refresh,
    refreshSelectedChannel,
  }
}

export type LogisticsChannelStatusEvent = {
  id: string
  reason: Exclude<LogisticsChannelReason, 'unknown' | 'unconfigured' | 'inactive'>
  occurredAt: string
}

function appendStatusEvent(
  events: LogisticsChannelStatusEvent[],
  previousReason: LogisticsChannelReason | null,
  status: LogisticsChannelRuntimeStatus,
) {
  if (
    status.reason === previousReason
    || status.reason === 'unknown'
    || status.reason === 'unconfigured'
    || status.reason === 'inactive'
  ) return events
  const occurredAt = new Date().toISOString()
  return [{ id: `${occurredAt}-${status.reason}`, reason: status.reason, occurredAt }, ...events].slice(0, 8)
}

type SelectionToken = { key: string }
type KeyedValue<T> = { selection: SelectionToken; value: T }

export function useLogisticsChannelStatus(
  feature: LogisticsFeatureName,
  channelId: number | null,
  enabled = true,
) {
  const [statusState, setStatusState] = useState<KeyedValue<LogisticsChannelRuntimeStatus> | null>(null)
  const [alarmState, setAlarmState] = useState<KeyedValue<LogisticsChannelAlarm[]> | null>(null)
  const [statisticsState, setStatisticsState] = useState<KeyedValue<LogisticsChannelStatistics> | null>(null)
  const [eventState, setEventState] = useState<KeyedValue<LogisticsChannelStatusEvent[]> | null>(null)
  const [frameUrlState, setFrameUrlState] = useState<KeyedValue<string> | null>(null)
  const [statusErrorState, setStatusErrorState] = useState<KeyedValue<string> | null>(null)
  const [summaryErrorState, setSummaryErrorState] = useState<KeyedValue<string> | null>(null)
  const [frameErrorState, setFrameErrorState] = useState<KeyedValue<string> | null>(null)
  const [statusRevision, refreshStatus] = useReducer((value: number) => value + 1, 0)
  const [summaryRevision, refreshSummary] = useReducer((value: number) => value + 1, 0)
  const [frameRevision, refreshFrame] = useReducer((value: number) => value + 1, 0)
  const frameObjectUrlRef = useRef<string | null>(null)
  const previousReasonRef = useRef<KeyedValue<LogisticsChannelReason | null> | null>(null)
  const selectionKey = `${feature}:${channelId ?? ''}`
  const selectionToken = useMemo<SelectionToken>(() => ({ key: selectionKey }), [selectionKey])
  const currentSelectionRef = useRef(selectionToken)
  const canPoll = enabled && channelId !== null

  useEffect(() => {
    currentSelectionRef.current = selectionToken
  }, [selectionToken])

  const loadStatus = useCallback(async (signal?: AbortSignal) => {
    if (channelId === null) return
    const requestedSelection = selectionToken
    try {
      const nextStatus = await getLogisticsChannelStatus(feature, channelId, { signal })
      if (currentSelectionRef.current !== requestedSelection) return
      setEventState((current) => ({
        selection: requestedSelection,
        value: appendStatusEvent(
          current?.selection === requestedSelection ? current.value : [],
          previousReasonRef.current?.selection === requestedSelection
            ? previousReasonRef.current.value
            : null,
          nextStatus,
        ),
      }))
      previousReasonRef.current = { selection: requestedSelection, value: nextStatus.reason }
      setStatusState({ selection: requestedSelection, value: nextStatus })
      setStatusErrorState(null)
    } catch (reason) {
      if (signal?.aborted || currentSelectionRef.current !== requestedSelection) return
      setStatusErrorState({
        selection: requestedSelection,
        value: reason instanceof Error ? reason.message : '物流通道状态加载失败',
      })
    }
  }, [channelId, feature, selectionToken])

  const loadSummary = useCallback(async (signal?: AbortSignal) => {
    if (channelId === null) return
    const requestedSelection = selectionToken
    try {
      const [alarmResponse, nextStatistics] = await Promise.all([
        getLogisticsChannelAlarms(feature, channelId, 1000, { signal }),
        getLogisticsChannelStatistics(feature, channelId, 7, { signal }),
      ])
      if (currentSelectionRef.current !== requestedSelection) return
      setAlarmState({
        selection: requestedSelection,
        value: alarmResponse.items.filter((alarm) => isToday(alarm.created_at)),
      })
      setStatisticsState({ selection: requestedSelection, value: nextStatistics })
      setSummaryErrorState(null)
    } catch (reason) {
      if (signal?.aborted || currentSelectionRef.current !== requestedSelection) return
      setSummaryErrorState({
        selection: requestedSelection,
        value: reason instanceof Error ? reason.message : '物流通道告警统计加载失败',
      })
    }
  }, [channelId, feature, selectionToken])

  const loadFrame = useCallback(async (signal?: AbortSignal) => {
    if (channelId === null) return
    const requestedSelection = selectionToken
    try {
      const blob = await fetchLogisticsChannelFrame(feature, channelId, signal, { nonce: Date.now() })
      if (currentSelectionRef.current !== requestedSelection) return
      const nextUrl = replaceLogisticsChannelFrameObjectUrl(blob, frameObjectUrlRef.current)
      frameObjectUrlRef.current = nextUrl
      setFrameUrlState({ selection: requestedSelection, value: nextUrl })
      setFrameErrorState(null)
    } catch (reason) {
      if (signal?.aborted || currentSelectionRef.current !== requestedSelection) return
      setFrameErrorState({
        selection: requestedSelection,
        value: reason instanceof Error ? reason.message : '物流通道画面加载失败',
      })
    }
  }, [channelId, feature, selectionToken])

  useEffect(() => {
    previousReasonRef.current = null
    revokeLogisticsChannelFrameObjectUrl(frameObjectUrlRef.current)
    frameObjectUrlRef.current = null
  }, [selectionToken])

  useEffect(() => () => {
    revokeLogisticsChannelFrameObjectUrl(frameObjectUrlRef.current)
    frameObjectUrlRef.current = null
  }, [])

  useSerialPoll(loadStatus, {
    intervalMs: STATUS_POLL_INTERVAL_MS,
    timeoutMs: JSON_REQUEST_TIMEOUT_MS,
    enabled: canPoll,
    restartKey: `${selectionKey}:${statusRevision}`,
  })
  useSerialPoll(loadSummary, {
    intervalMs: SUMMARY_POLL_INTERVAL_MS,
    timeoutMs: JSON_REQUEST_TIMEOUT_MS,
    enabled: canPoll,
    restartKey: `${selectionKey}:${summaryRevision}`,
  })
  useSerialPoll(loadFrame, {
    intervalMs: FRAME_POLL_INTERVAL_MS,
    timeoutMs: FRAME_REQUEST_TIMEOUT_MS,
    enabled: canPoll,
    restartKey: `${selectionKey}:${frameRevision}`,
  })

  useEffect(() => {
    if (!canPoll || channelId === null) return
    const onInvalidated = (rawEvent: Event) => {
      const event = rawEvent as LogisticsChannelInvalidationEvent
      if (event.detail.feature !== feature) return
      if (event.detail.channelId !== undefined && event.detail.channelId !== channelId) return
      refreshStatus()
      refreshSummary()
      refreshFrame()
    }
    window.addEventListener(LOGISTICS_CHANNEL_QUERY_INVALIDATED, onInvalidated)
    return () => window.removeEventListener(LOGISTICS_CHANNEL_QUERY_INVALIDATED, onInvalidated)
  }, [canPoll, channelId, feature])

  return {
    status: statusState?.selection === selectionToken ? statusState.value : null,
    alarms: alarmState?.selection === selectionToken ? alarmState.value : [],
    statistics: statisticsState?.selection === selectionToken ? statisticsState.value : null,
    events: eventState?.selection === selectionToken ? eventState.value : [],
    frameUrl: frameUrlState?.selection === selectionToken ? frameUrlState.value : null,
    error: statusErrorState?.selection === selectionToken
      ? statusErrorState.value
      : summaryErrorState?.selection === selectionToken
        ? summaryErrorState.value
        : frameErrorState?.selection === selectionToken
          ? frameErrorState.value
          : null,
    errors: {
      status: statusErrorState?.selection === selectionToken ? statusErrorState.value : null,
      summary: summaryErrorState?.selection === selectionToken ? summaryErrorState.value : null,
      frame: frameErrorState?.selection === selectionToken ? frameErrorState.value : null,
    },
    refreshStatus,
    refreshSummary,
    refreshFrame,
  }
}
