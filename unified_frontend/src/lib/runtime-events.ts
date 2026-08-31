// 文件说明：实现运行时相关的基础能力。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

export const PLATFORM_RUNTIME_CHANGED_EVENT = 'platform:runtime-changed'

/**
 * 功能：发送或分发 `notifyPlatformRuntimeChanged` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/api.ts` 的 `startGuardRoomSiteRuntime` 调用本符号；`unified_frontend/src/lib/api.ts` 的
 *         `stopGuardRoomSiteRuntime` 调用本符号；`unified_frontend/src/lib/api.ts` 的 `restartGuardRoomSiteRuntime`
 *         调用本符号；`unified_frontend/src/lib/aivision.ts` 的 `setAiVisionCapabilityState` 调用本符号
 *   - 内部调用：`dispatchEvent`、`Event`。
 * 副作用/注意事项：会读取或修改浏览器全局对象/DOM 状态。
 */
export function notifyPlatformRuntimeChanged() {
  window.dispatchEvent(new Event(PLATFORM_RUNTIME_CHANGED_EVENT))
}
