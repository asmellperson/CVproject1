// 文件说明：实现`useLogisticsChannels` 模块的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

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
export const FRAME_POLL_INTERVAL_MS = 200
const JSON_REQUEST_TIMEOUT_MS = 8000
const FRAME_REQUEST_TIMEOUT_MS = 5000

type LogisticsChannelInvalidationEvent = CustomEvent<LogisticsChannelQueryInvalidation>

/**
 * 功能：检查或判断 `isToday` 对应的`useLogisticsChannels` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（string | null）：待转换、校验或写入的值
 *   - `now`（未显式标注）：`now` 对应的业务输入值；声明包含默认值 `new Date()`
 * 返回：boolean（由实现推断）；返回条件是否成立。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`Date`、`isNaN`、`getTime`、`getFullYear`、`getMonth`、`getDate`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function isToday(value: string | null, now = new Date()) {
  if (!value) return false
  const date = new Date(value)
  return !Number.isNaN(date.getTime())
    && date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate()
}

/**
 * 功能：封装 `useLogisticsChannels` React Hook，向调用组件提供`useLogisticsChannels` 模块状态与操作
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `enabled`（未显式标注）：是否启用相应能力；声明包含默认值 `true`
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelSection.tsx` 的 `LogisticsChannelSection` 调用本符号
 *   - 内部调用：`useState`、`useReducer`、`useRef`、`useEffect`、`useCallback`、`async`、`isCurrentChannelListRequest`、`listLogisticsChannels`、`isCurrentRequest`、`setChannels`
 *          等共 32 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染；会读取或修改浏览器全局对象/DOM 状态。
 */
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
  const listRequestGenerationRef = useRef(0)
  const detailRequestGenerationRef = useRef(0)

  useEffect(() => {
    currentFeatureRef.current = feature
    currentSelectedChannelIdRef.current = selectedChannelId
  }, [feature, selectedChannelId])

  const loadChannels = useCallback(async (signal?: AbortSignal) => {
    const request = { feature, generation: listRequestGenerationRef.current }
    const isCurrentRequest = () => isCurrentChannelListRequest(request, {
      feature: currentFeatureRef.current,
      generation: listRequestGenerationRef.current,
    })
    try {
      const response = await listLogisticsChannels(request.feature, { signal })
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
  }, [feature])

  const loadSelectedChannel = useCallback(async (signal?: AbortSignal) => {
    if (selectedChannelId === null) return
    const request = {
      feature,
      channelId: selectedChannelId,
      generation: detailRequestGenerationRef.current,
    }
    const isCurrentRequest = () => isCurrentChannelDetailRequest(request, {
      feature: currentFeatureRef.current,
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
  }, [feature, selectedChannelId])

  useEffect(() => {
    currentFeatureRef.current = feature
    listRequestGenerationRef.current += 1
    detailRequestGenerationRef.current += 1
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
    const next = advanceChannelRequestsForCreatedChannel({
      feature,
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
  }, [feature])

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

/**
 * 功能：封装 `useLogisticsChannelStatus` React Hook，向调用组件提供`useLogisticsChannels` 模块状态与操作
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number | null）：`channelId` 对应业务对象的唯一标识
 *   - `enabled`（未显式标注）：是否启用相应能力；声明包含默认值 `true`
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelSection.tsx` 的 `LogisticsChannelSection` 调用本符号
 *   - 内部调用：`useReducer`、`useRef`、`useMemo`、`useEffect`、`useCallback`、`async`、`getLogisticsChannelStatus`、`setEventState`、`appendLogisticsStatusEvent`、`setStatusState`
 *          等共 39 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染；会读取或修改浏览器全局对象/DOM 状态。
 */
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
