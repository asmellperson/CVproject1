// 文件说明：实现状态管理的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

type CameraIdentity = { camera_id: number }
type ChannelMembershipSummary = {
  members: Array<{ camera_id: number; enabled: boolean }>
}

type CountedChannelMembershipSummary = {
  id: number
  members: Array<{ enabled: boolean }>
}

export type ChannelMemberCount = { enabled: number; total: number }

export type MembershipLoadIdentity = {
  generation: number
  feature: string
  channelIdsKey: string
}

/**
 * 功能：读取或查询 `isMembershipLoadCurrent` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `request`（MembershipLoadIdentity）：当前 HTTP 请求及上下文
 *   - `current`（MembershipLoadIdentity）：`current` 对应的业务输入值
 * 返回：boolean（由实现推断）；返回条件是否成立。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx` 的 `LogisticsChannelConfigView`
 *         调用本符号
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function isMembershipLoadCurrent(
  request: MembershipLoadIdentity,
  current: MembershipLoadIdentity,
) {
  return request.generation === current.generation
    && request.feature === current.feature
    && request.channelIdsKey === current.channelIdsKey
}

/**
 * 功能：实现 `collectBoundCameraIds` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `channels`（ChannelMembershipSummary[]）：`channels` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx` 的 `LogisticsChannelConfigView`
 *         调用本符号
 *   - 内部调用：`Set`、`flatMap`、`map`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function collectBoundCameraIds(channels: ChannelMembershipSummary[]) {
  return new Set(
    channels.flatMap((channel) => channel.members)
      .map((member) => member.camera_id),
  )
}

/**
 * 功能：实现 `collectChannelMemberCounts` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `channels`（CountedChannelMembershipSummary[]）：`channels` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx` 的 `LogisticsChannelConfigView`
 *         调用本符号
 *   - 内部调用：`fromEntries`、`map`、`filter`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function collectChannelMemberCounts(channels: CountedChannelMembershipSummary[]) {
  return Object.fromEntries(channels.map((channel) => [
    channel.id,
    {
      enabled: channel.members.filter((member) => member.enabled).length,
      total: channel.members.length,
    },
  ])) as Record<number, ChannelMemberCount>
}

/**
 * 功能：实现 `filterBindableCameras` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `cameras`（Camera[]）：`cameras` 对应的业务输入值
 *   - `boundCameraIds`（ReadonlySet<number>）：`boundCameraIds` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx` 的 `LogisticsChannelConfigView`
 *         调用本符号
 *   - 内部调用：`filter`、`has`、`Camera`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function filterBindableCameras<Camera extends CameraIdentity>(
  cameras: Camera[],
  boundCameraIds: ReadonlySet<number>,
) {
  return cameras.filter((camera) => !boundCameraIds.has(camera.camera_id))
}

/**
 * 功能：实现 `removalConfirmationText` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `cameraName`（string）：`cameraName` 对应的业务输入值
 *   - `channelName`（string）：`channelName` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx` 的 `LogisticsChannelConfigView`
 *         调用本符号
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function removalConfirmationText(cameraName: string, channelName: string) {
  return `确定将摄像头“${cameraName}”从物流通道“${channelName}”移除吗？摄像头资源不会被删除。`
}

/**
 * 功能：实现 `confirmMembershipRemoval` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `confirmRemoval`（() => boolean）：`confirmRemoval` 对应的业务输入值；声明包含默认值 `> boolean`
 *   - `remove`（() => void）：`remove` 对应的业务输入值；声明包含默认值 `> void`
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx` 的 `LogisticsChannelConfigView`
 *         调用本符号
 *   - 内部调用：`confirmRemoval`、`remove`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function confirmMembershipRemoval(
  confirmRemoval: () => boolean,
  remove: () => void,
) {
  if (!confirmRemoval()) return false
  remove()
  return true
}
