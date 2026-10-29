import type { DepartmentId } from '@/auth/permissions'
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'

import { useSerialPoll } from '@/hooks/use-serial-poll'
import {
  LOGISTICS_CHANNEL_QUERY_INVALIDATED,
  getLogisticsChannelAlarms,
  getLogisticsChannel,
  getLogisticsChannelStatistics,
  getLogisticsChannelStatus,
  listLogisticsChannels,
  type LogisticsChannelQueryInvalidation,
} from './api'
import {
  advanceChannelRequestsForCreatedChannel,
  isCurrentChannelDetailRequest,
  isCurrentChannelListRequest,
} from './channelRequestState'
import { selectAfterChannelDeletion } from './channelSelection'
import {
  appendLogisticsStatusEvent,
  type LogisticsChannelStatusEvent,
} from './monitorPresentation'
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
const JSON_REQUEST_TIMEOUT_MS = 8000

type LogisticsChannelInvalidationEvent = CustomEvent<LogisticsChannelQueryInvalidation>

function isToday(value: string | null, now = new Date()) {
  if (!value) return false
  const date = new Date(value)
  return !Number.isNaN(date.getTime())
    && date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate()
}

export function useLogisticsChannels(feature: LogisticsFeatureName, department: DepartmentId, enabled = true) {
  const [channels, setChannels] = useState<LogisticsChannel[]>([])
  const [selectedChannelDetail, setSelectedChannelDetail] = useState<LogisticsChannelDetail | null>(null)
  const [selectedChannelId, setSelectedChannelId] = useState<number | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [error, setError] = useState<string | null>(null)
  const [listRevision, refresh] = useReducer((value: number) => value + 1, 0)
  const [detailRevision, refreshSelectedChannel] = useReducer((value: number) => value + 1, 0)
  const currentFeatureRef = useRef(feature)
  const currentDepartmentRef = useRef(department)
  const currentSelectedChannelIdRef = useRef(selectedChannelId)
  const listRequestGenerationRef = useRef(0)
  const detailRequestGenerationRef = useRef(0)

  useEffect(() => {
    currentFeatureRef.current = feature
    currentDepartmentRef.current = department
    currentSelectedChannelIdRef.current = selectedChannelId
  }, [feature, department, selectedChannelId])

  const loadChannels = useCallback(async (signal?: AbortSignal) => {
    const request = { feature, department, generation: listRequestGenerationRef.current }
    const isCurrentRequest = () => isCurrentChannelListRequest(request, {
      feature: currentFeatureRef.current,
      department: currentDepartmentRef.current,
      generation: listRequestGenerationRef.current,
    })
    try {
      const response = await listLogisticsChannels(request.feature, request.department, { signal })
      if (!isCurrentRequest()) return
      setChannels(response.items)
      setSelectedChannelId((current) => {
        if (current !== null && response.items.some((channel) => channel.id === current)) {
          return current
        }
        return response.items[0]?.id ?? null
      })
      setError(null)
    } catch (reason) {
      if (signal?.aborted || !isCurrentRequest()) return
      setError(reason instanceof Error ? reason.message : '物流通道加载失败')
    } finally {
      if (isCurrentRequest()) setLoading(false)
    }
  }, [feature, department])

  const loadSelectedChannel = useCallback(async (signal?: AbortSignal) => {
    if (selectedChannelId === null) return
    const request = {
      feature,
      department,
      channelId: selectedChannelId,
      generation: detailRequestGenerationRef.current,
    }
    const isCurrentRequest = () => isCurrentChannelDetailRequest(request, {
      feature: currentFeatureRef.current,
      department: currentDepartmentRef.current,
      channelId: currentSelectedChannelIdRef.current,
      generation: detailRequestGenerationRef.current,
    })
    try {
      const detail = await getLogisticsChannel(request.feature, request.channelId, { signal })
      if (!isCurrentRequest()) return
      setSelectedChannelDetail(detail)
      setError(null)
    } catch (reason) {
      if (signal?.aborted || !isCurrentRequest()) return
      setError(reason instanceof Error ? reason.message : '物流通道详情加载失败')
    }
  }, [feature, department, selectedChannelId])

  useEffect(() => {
    currentFeatureRef.current = feature
    currentDepartmentRef.current = department
    listRequestGenerationRef.current += 1
    detailRequestGenerationRef.current += 1
    setChannels([])
    setSelectedChannelDetail(null)
    setSelectedChannelId(null)
    setError(null)
    setLoading(enabled)
  }, [enabled, feature, department])

  useEffect(() => {
    setSelectedChannelDetail(null)
  }, [feature, department, selectedChannelId])

  useSerialPoll(
    async (signal) => loadChannels(signal),
    {
      intervalMs: CHANNEL_LIST_POLL_INTERVAL_MS,
      timeoutMs: JSON_REQUEST_TIMEOUT_MS,
      enabled,
      restartKey: `${feature}:${department}:${listRevision}`,
    },
  )

  useSerialPoll(loadSelectedChannel, {
    intervalMs: CHANNEL_LIST_POLL_INTERVAL_MS,
    timeoutMs: JSON_REQUEST_TIMEOUT_MS,
    enabled: enabled && selectedChannelId !== null,
    restartKey: `${feature}:${department}:${selectedChannelId ?? ''}:${detailRevision}`,
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

  const removeChannelLocally = useCallback((channelId: number) => {
    listRequestGenerationRef.current += 1
    detailRequestGenerationRef.current += 1
    setChannels((current) => {
      const nextSelected = selectAfterChannelDeletion(
        current,
        channelId,
        currentSelectedChannelIdRef.current,
      )
      currentSelectedChannelIdRef.current = nextSelected
      setSelectedChannelId(nextSelected)
      return current.filter((channel) => channel.id !== channelId)
    })
    setSelectedChannelDetail(null)
  }, [])

  const selectCreatedChannelLocally = useCallback((channel: LogisticsChannelDetail) => {
    if (channel.department !== department) return
    const next = advanceChannelRequestsForCreatedChannel({
      feature,
      department,
      listGeneration: listRequestGenerationRef.current,
      detailGeneration: detailRequestGenerationRef.current,
      selectedChannelId: currentSelectedChannelIdRef.current,
    }, channel.id)
    listRequestGenerationRef.current = next.listGeneration
    detailRequestGenerationRef.current = next.detailGeneration
    currentSelectedChannelIdRef.current = next.selectedChannelId
    setSelectedChannelId(next.selectedChannelId)
    setSelectedChannelDetail(channel)
    setChannels((current) => {
      const withoutCreated = current.filter((item) => item.id !== channel.id)
      return [...withoutCreated, channel].sort((left, right) => (
        left.sort_order - right.sort_order || left.id - right.id
      ))
    })
    refresh()
  }, [feature, department])

  return {
    channels,
    selectedChannel,
    selectedChannelDetail,
    selectedChannelId,
    setSelectedChannelId,
    selectCreatedChannelLocally,
    removeChannelLocally,
    loading,
    error,
    refresh,
    refreshSelectedChannel,
  }
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
  const [statusErrorState, setStatusErrorState] = useState<KeyedValue<string> | null>(null)
  const [summaryErrorState, setSummaryErrorState] = useState<KeyedValue<string> | null>(null)
  const [statusRevision, refreshStatus] = useReducer((value: number) => value + 1, 0)
  const [summaryRevision, refreshSummary] = useReducer((value: number) => value + 1, 0)
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
        value: appendLogisticsStatusEvent(
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
      setStatusState(null)
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

  useEffect(() => { previousReasonRef.current = null }, [selectionToken])

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
  useEffect(() => {
    if (!canPoll || channelId === null) return
    const onInvalidated = (rawEvent: Event) => {
      const event = rawEvent as LogisticsChannelInvalidationEvent
      if (event.detail.feature !== feature) return
      if (event.detail.channelId !== undefined && event.detail.channelId !== channelId) return
      refreshStatus()
      refreshSummary()
    }
    window.addEventListener(LOGISTICS_CHANNEL_QUERY_INVALIDATED, onInvalidated)
    return () => window.removeEventListener(LOGISTICS_CHANNEL_QUERY_INVALIDATED, onInvalidated)
  }, [canPoll, channelId, feature])

  return {
    status: statusState?.selection === selectionToken ? statusState.value : null,
    alarms: alarmState?.selection === selectionToken ? alarmState.value : [],
    statistics: statisticsState?.selection === selectionToken ? statisticsState.value : null,
    events: eventState?.selection === selectionToken ? eventState.value : [],
    error: statusErrorState?.selection === selectionToken
      ? statusErrorState.value
      : summaryErrorState?.selection === selectionToken
        ? summaryErrorState.value
        : null,
    errors: {
      status: statusErrorState?.selection === selectionToken ? statusErrorState.value : null,
      summary: summaryErrorState?.selection === selectionToken ? summaryErrorState.value : null,
    },
    refreshStatus,
    refreshSummary,
  }
}
