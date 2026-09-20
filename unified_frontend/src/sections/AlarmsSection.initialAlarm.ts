export function findInitialAlarm<T extends { id: string }>(
  alarms: readonly T[],
  initialAlarmId: string,
): T | undefined {
  if (!initialAlarmId) return undefined

  return alarms.find((item) => item.id === initialAlarmId)
}

export function removeAlarmIdFromSearch(search: string) {
  const params = new URLSearchParams(search)
  params.delete('alarmId')
  const nextSearch = params.toString()
  return nextSearch ? `?${nextSearch}` : ''
}

export function buildUrlWithoutAlarmId(location: Pick<Location, 'pathname' | 'search' | 'hash'>) {
  return `${location.pathname}${removeAlarmIdFromSearch(location.search)}${location.hash}`
}
