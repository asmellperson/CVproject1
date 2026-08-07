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

type KeyedValue<T> = { key: string; value: T }

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
  const [errorState, setErrorState] = useState<KeyedValue<string> | null>(null)
  const [statusRevision, refreshStatus] = useReducer((value: number) => value + 1, 0)
  const [summaryRevision, refreshSummary] = useReducer((value: number) => value + 1, 0)
  const [frameRevision, refreshFrame] = useReducer((value: number) => value + 1, 0)
  const frameObjectUrlRef = useRef<string | null>(null)
  const previousReasonRef = useRef<KeyedValue<LogisticsChannelReason | null> | null>(null)
  const selectionKey = `${feature}:${channelId ?? ''}`
  const currentSelectionRef = useRef(selectionKey)
  const canPoll = enabled && channelId !== null

  useEffect(() => {
    currentSelectionRef.current = selectionKey
  }, [selectionKey])

  const loadStatus = useCallback(async (signal?: AbortSignal) => {
    if (channelId === null) return
    const requestedKey = `${feature}:${channelId}`
    try {
      const nextStatus = await getLogisticsChannelStatus(feature, channelId, { signal })
      if (currentSelectionRef.current !== requestedKey) return
      setEventState((current) => ({
        key: requestedKey,
        value: appendStatusEvent(
          current?.key === requestedKey ? current.value : [],
          previousReasonRef.current?.key === requestedKey ? previousReasonRef.current.value : null,
          nextStatus,
        ),
      }))
      previousReasonRef.current = { key: requestedKey, value: nextStatus.reason }
      setStatusState({ key: requestedKey, value: nextStatus })
      setErrorState(null)
    } catch (reason) {
      if (signal?.aborted || currentSelectionRef.current !== requestedKey) return
      setErrorState({
        key: requestedKey,
        value: reason instanceof Error ? reason.message : '物流通道状态加载失败',
      })
    }
  }, [channelId, feature])

  const loadSummary = useCallback(async (signal?: AbortSignal) => {
    if (channelId === null) return
    const requestedKey = `${feature}:${channelId}`
    try {
      const [alarmResponse, nextStatistics] = await Promise.all([
        getLogisticsChannelAlarms(feature, channelId, 1000, { signal }),
        getLogisticsChannelStatistics(feature, channelId, 7, { signal }),
      ])
      if (currentSelectionRef.current !== requestedKey) return
      setAlarmState({
        key: requestedKey,
        value: alarmResponse.items.filter((alarm) => isToday(alarm.created_at)),
      })
      setStatisticsState({ key: requestedKey, value: nextStatistics })
    } catch (reason) {
      if (signal?.aborted || currentSelectionRef.current !== requestedKey) return
      setErrorState({
        key: requestedKey,
        value: reason instanceof Error ? reason.message : '物流通道告警统计加载失败',
      })
    }
  }, [channelId, feature])

  const loadFrame = useCallback(async (signal?: AbortSignal) => {
    if (channelId === null) return
    const requestedKey = `${feature}:${channelId}`
    try {
      const blob = await fetchLogisticsChannelFrame(feature, channelId, signal, { nonce: Date.now() })
      if (currentSelectionRef.current !== requestedKey) return
      const nextUrl = replaceLogisticsChannelFrameObjectUrl(blob, frameObjectUrlRef.current)
      frameObjectUrlRef.current = nextUrl
      setFrameUrlState({ key: requestedKey, value: nextUrl })
    } catch (reason) {
      if (signal?.aborted || currentSelectionRef.current !== requestedKey) return
      setErrorState({
        key: requestedKey,
        value: reason instanceof Error ? reason.message : '物流通道画面加载失败',
      })
    }
  }, [channelId, feature])

  useEffect(() => {
    previousReasonRef.current = null
    revokeLogisticsChannelFrameObjectUrl(frameObjectUrlRef.current)
    frameObjectUrlRef.current = null
  }, [selectionKey])

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
    status: statusState?.key === selectionKey ? statusState.value : null,
    alarms: alarmState?.key === selectionKey ? alarmState.value : [],
    statistics: statisticsState?.key === selectionKey ? statisticsState.value : null,
    events: eventState?.key === selectionKey ? eventState.value : [],
    frameUrl: frameUrlState?.key === selectionKey ? frameUrlState.value : null,
    error: errorState?.key === selectionKey ? errorState.value : null,
    refreshStatus,
    refreshSummary,
    refreshFrame,
  }
}
