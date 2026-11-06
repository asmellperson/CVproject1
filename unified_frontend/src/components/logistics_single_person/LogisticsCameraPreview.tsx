import { useEffect, useReducer, useState } from 'react'
import type { AiVisionCamera } from '@/lib/aivision'
import type { DepartmentId } from '@/auth/permissions'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { CameraLivePreview } from '@/components/monitor/CameraLivePreview'
import { getLogisticsCameraRoi, LOGISTICS_CHANNEL_QUERY_INVALIDATED, type LogisticsChannelQueryInvalidation } from './api'
import type { LogisticsCameraRoiPayload, LogisticsFeatureName } from './types'

type Props = { feature: LogisticsFeatureName; department: DepartmentId; channelId: number; camera: AiVisionCamera }

export function LogisticsCameraPreview(props: Props) {
  return <MemberPreview key={`${props.feature}:${props.department}:${props.channelId}:${props.camera.camera_id}:${props.camera.shm_name}:${props.camera.enabled}`} {...props} />
}

function MemberPreview({ feature, department, channelId, camera }: Props) {
  const [value, setValue] = useState<LogisticsCameraRoiPayload | null>(null)
  const [error, setError] = useState('')
  const [revision, refresh] = useReducer((current: number) => current + 1, 0)
  useSerialPoll(async (signal) => {
    const roi = await getLogisticsCameraRoi(feature, channelId, camera.camera_id, { signal })
    if (signal.aborted) return
    setValue({ roi_pos: roi.roi_pos })
    setError('')
  }, { enabled: camera.enabled, intervalMs: 5000, timeoutMs: 8000, restartKey: revision,
    onError: (cause) => {
      setValue(null)
      setError(`检测区域读取失败：${cause instanceof Error ? cause.message : String(cause)}`)
    } })
  useEffect(() => {
    const onInvalidated = (event: Event) => {
      const { detail } = event as CustomEvent<LogisticsChannelQueryInvalidation>
      if (detail.feature === feature && (detail.channelId === undefined || detail.channelId === channelId)) refresh()
    }
    window.addEventListener(LOGISTICS_CHANNEL_QUERY_INVALIDATED, onInvalidated)
    return () => window.removeEventListener(LOGISTICS_CHANNEL_QUERY_INVALIDATED, onInvalidated)
  }, [feature, channelId])
  // 物流 ROI 只能由通道成员接口读取；显式传入 null 也要阻止公共预览请求普通配置。
  return <div className="relative h-full w-full">
    <CameraLivePreview cameraKey={camera.shm_name} feature={feature} department={department}
      enabled={camera.enabled} fps={camera.fps} value={value} />
    {error && <p role="status" className="absolute left-2 right-2 top-2 rounded bg-slate-950/80 p-2 text-xs text-amber-300">{error}</p>}
  </div>
}
