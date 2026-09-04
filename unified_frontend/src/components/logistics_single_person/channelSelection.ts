type ChannelIdentity = { id: number }

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
