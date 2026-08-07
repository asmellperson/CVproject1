export type ChannelListRequestIdentity = {
  feature: string
  generation: number
}

export type ChannelDetailRequestIdentity = ChannelListRequestIdentity & {
  channelId: number | null
}

export function isCurrentChannelListRequest(
  request: ChannelListRequestIdentity,
  current: ChannelListRequestIdentity,
) {
  return request.feature === current.feature && request.generation === current.generation
}

export function isCurrentChannelDetailRequest(
  request: ChannelDetailRequestIdentity,
  current: ChannelDetailRequestIdentity,
) {
  return isCurrentChannelListRequest(request, current) && request.channelId === current.channelId
}
