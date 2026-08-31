// 文件说明：实现摄像头相关的基础能力。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

export const PLATFORM_CAMERAS_CHANGED_EVENT = 'platform:cameras-changed'

/**
 * 功能：发送或分发 `notifyPlatformCamerasChanged` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/security-vlm.ts` 的 `createSecurityVlmCamera` 调用本符号；`unified_frontend/src/lib/security-vlm.ts` 的
 *         `updateSecurityVlmCamera` 调用本符号；`unified_frontend/src/lib/security-vlm.ts` 的 `deleteSecurityVlmCamera`
 *         调用本符号；`unified_frontend/src/lib/api.ts` 的 `createGuardRoomSiteCamera` 调用本符号；另有 8 处静态调用
 *   - 内部调用：`dispatchEvent`、`Event`。
 * 副作用/注意事项：会读取或修改浏览器全局对象/DOM 状态。
 */
export function notifyPlatformCamerasChanged() {
  window.dispatchEvent(new Event(PLATFORM_CAMERAS_CHANGED_EVENT))
}
