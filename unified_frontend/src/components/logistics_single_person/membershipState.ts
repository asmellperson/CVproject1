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

export function isMembershipLoadCurrent(
  request: MembershipLoadIdentity,
  current: MembershipLoadIdentity,
) {
  return request.generation === current.generation
    && request.feature === current.feature
    && request.channelIdsKey === current.channelIdsKey
}

export function collectBoundCameraIds(channels: ChannelMembershipSummary[]) {
  return new Set(
    channels.flatMap((channel) => channel.members)
      .map((member) => member.camera_id),
  )
}

export function collectChannelMemberCounts(channels: CountedChannelMembershipSummary[]) {
  return Object.fromEntries(channels.map((channel) => [
    channel.id,
    {
      enabled: channel.members.filter((member) => member.enabled).length,
      total: channel.members.length,
    },
  ])) as Record<number, ChannelMemberCount>
}

export function filterBindableCameras<Camera extends CameraIdentity>(
  cameras: Camera[],
  boundCameraIds: ReadonlySet<number>,
) {
  return cameras.filter((camera) => !boundCameraIds.has(camera.camera_id))
}

export function removalConfirmationText(cameraName: string, channelName: string) {
  return `确定将摄像头“${cameraName}”从物流通道“${channelName}”移除吗？摄像头资源不会被删除。`
}

export function confirmMembershipRemoval(
  confirmRemoval: () => boolean,
  remove: () => void,
) {
  if (!confirmRemoval()) return false
  remove()
  return true
}
