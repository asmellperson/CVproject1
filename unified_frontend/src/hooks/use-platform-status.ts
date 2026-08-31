// 文件说明：封装`use-platform-status` 模块的 React 状态与副作用。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { useEffect, useState } from 'react'

import {
  getPlatformStatus,
  PLATFORM_STATUS_POLL_INTERVAL_MS,
  PLATFORM_STATUS_REQUEST_TIMEOUT_MS,
  type PlatformStatus,
} from '../lib/api'
import { useSerialPoll } from './use-serial-poll'
import { PLATFORM_CAMERAS_CHANGED_EVENT } from '../lib/camera-events'
import { PLATFORM_RUNTIME_CHANGED_EVENT } from '../lib/runtime-events'

/**
 * 功能：封装 `usePlatformStatus` React Hook，向调用组件提供`use-platform-status` 模块状态与操作
 * 参数：无。
 * 返回：PlatformStatus | null；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/App.tsx` 的 `App` 调用本符号
 *   - 内部调用：`useState`、`useEffect`、`setCameraRevision`、`addEventListener`、`return`、`removeEventListener`、`useSerialPoll`、`async`、`getPlatformStatus`、`setPlatformStatus`
 *          等共 11 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染；会读取或修改浏览器全局对象/DOM 状态。
 */
export function usePlatformStatus(): PlatformStatus | null {
  const [platformStatus, setPlatformStatus] = useState<PlatformStatus | null>(null)
  const [cameraRevision, setCameraRevision] = useState(0)

  useEffect(() => {
    const refresh = () => setCameraRevision((value) => value + 1)
    window.addEventListener(PLATFORM_CAMERAS_CHANGED_EVENT, refresh)
    window.addEventListener(PLATFORM_RUNTIME_CHANGED_EVENT, refresh)
    return () => {
      window.removeEventListener(PLATFORM_CAMERAS_CHANGED_EVENT, refresh)
      window.removeEventListener(PLATFORM_RUNTIME_CHANGED_EVENT, refresh)
    }
  }, [])

  useSerialPoll(
    async (signal) => {
      const status = await getPlatformStatus({ signal })
      setPlatformStatus(status)
    },
    {
      intervalMs: PLATFORM_STATUS_POLL_INTERVAL_MS,
      timeoutMs: PLATFORM_STATUS_REQUEST_TIMEOUT_MS,
      onError: () => setPlatformStatus(null),
      restartKey: cameraRevision,
    },
  )

  return platformStatus
}
