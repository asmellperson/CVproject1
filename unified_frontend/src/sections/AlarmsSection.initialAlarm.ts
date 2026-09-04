type AlarmWithSource = {
  id: string
  source?: string
  source_id?: string | number | null
}

export function findInitialAlarm<T extends AlarmWithSource>(
  alarms: readonly T[],
  initialAlarmId: string,
): T | undefined {
  if (!initialAlarmId) return undefined

  return alarms.find((item) => {
    const sourceId = item.source_id || item.id
    return item.id === initialAlarmId || `${item.source || 'aivision'}:${sourceId}` === initialAlarmId
  })
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
