export type ChannelListRequestIdentity = {
  feature: string
  department: string
  generation: number
}

export type ChannelDetailRequestIdentity = ChannelListRequestIdentity & {
  channelId: number | null
}

export type ChannelRequestCursor = {
  feature: string
  department: string
  listGeneration: number
  detailGeneration: number
  selectedChannelId: number | null
}

export function isCurrentChannelListRequest(
  request: ChannelListRequestIdentity,
  current: ChannelListRequestIdentity,
) {
  return request.feature === current.feature
    && request.department === current.department
    && request.generation === current.generation
}

export function isCurrentChannelDetailRequest(
  request: ChannelDetailRequestIdentity,
  current: ChannelDetailRequestIdentity,
) {
  return isCurrentChannelListRequest(request, current) && request.channelId === current.channelId
}

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
