// 文件说明：实现状态管理的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

export type ChannelListRequestIdentity = {
  feature: string
  generation: number
}

export type ChannelDetailRequestIdentity = ChannelListRequestIdentity & {
  channelId: number | null
}

export type ChannelRequestCursor = {
  feature: string
  listGeneration: number
  detailGeneration: number
  selectedChannelId: number | null
}

/**
 * 功能：读取或查询 `isCurrentChannelListRequest` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `request`（ChannelListRequestIdentity）：当前 HTTP 请求及上下文
 *   - `current`（ChannelListRequestIdentity）：`current` 对应的业务输入值
 * 返回：boolean（由实现推断）；返回条件是否成立。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/channelRequestState.ts` 的 `isCurrentChannelDetailRequest`
 *         调用本符号；`unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts` 的 `useLogisticsChannels` 调用本符号
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function isCurrentChannelListRequest(
  request: ChannelListRequestIdentity,
  current: ChannelListRequestIdentity,
) {
  return request.feature === current.feature && request.generation === current.generation
}

/**
 * 功能：检查或判断 `isCurrentChannelDetailRequest` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `request`（ChannelDetailRequestIdentity）：当前 HTTP 请求及上下文
 *   - `current`（ChannelDetailRequestIdentity）：`current` 对应的业务输入值
 * 返回：boolean（由实现推断）；返回条件是否成立。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts` 的 `useLogisticsChannels` 调用本符号
 *   - 内部调用：`isCurrentChannelListRequest`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function isCurrentChannelDetailRequest(
  request: ChannelDetailRequestIdentity,
  current: ChannelDetailRequestIdentity,
) {
  return isCurrentChannelListRequest(request, current) && request.channelId === current.channelId
}

/**
 * 功能：实现 `advanceChannelRequestsForCreatedChannel` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `current`（ChannelRequestCursor）：`current` 对应的业务输入值
 *   - `createdChannelId`（number）：`createdChannelId` 对应业务对象的唯一标识
 * 返回：ChannelRequestCursor；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts` 的 `useLogisticsChannels` 调用本符号
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function advanceChannelRequestsForCreatedChannel(
  current: ChannelRequestCursor,
  createdChannelId: number,
): ChannelRequestCursor {
  return {
    ...current,
    listGeneration: current.listGeneration + 1,
    detailGeneration: current.detailGeneration + 1,
    selectedChannelId: createdChannelId,
  }
}
