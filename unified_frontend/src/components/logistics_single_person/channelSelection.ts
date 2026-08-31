// 文件说明：实现`channelSelection` 模块的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

type ChannelIdentity = { id: number }

/**
 * 功能：实现 `selectAfterChannelDeletion` 对应的`channelSelection` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `channels`（readonly ChannelIdentity[]）：`channels` 对应的业务输入值
 *   - `deletedChannelId`（number）：`deletedChannelId` 对应业务对象的唯一标识
 *   - `selectedChannelId`（number | null）：`selectedChannelId` 对应业务对象的唯一标识
 * 返回：number | null；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts` 的 `useLogisticsChannels` 调用本符号
 *   - 内部调用：`some`、`findIndex`、`find`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function selectAfterChannelDeletion(
  channels: readonly ChannelIdentity[],
  deletedChannelId: number,
  selectedChannelId: number | null,
): number | null {
  if (
    selectedChannelId !== deletedChannelId
    && selectedChannelId !== null
    && channels.some((channel) => channel.id === selectedChannelId && channel.id !== deletedChannelId)
  ) return selectedChannelId

  const deletedIndex = channels.findIndex((channel) => channel.id === deletedChannelId)
  if (deletedIndex < 0) {
    return channels.find((channel) => channel.id !== deletedChannelId)?.id ?? null
  }
  return channels[deletedIndex + 1]?.id ?? channels[deletedIndex - 1]?.id ?? null
}
