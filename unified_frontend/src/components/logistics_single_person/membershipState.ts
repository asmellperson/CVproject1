type CameraIdentity = { camera_id: number }
type ChannelMembershipSummary = {
  members: Array<{ camera_id: number; enabled: boolean }>
}

export function collectBoundCameraIds(channels: ChannelMembershipSummary[]) {
  return new Set(
    channels.flatMap((channel) => channel.members)
      .map((member) => member.camera_id),
  )
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
