export const PLATFORM_RUNTIME_CHANGED_EVENT = 'platform:runtime-changed'

export function notifyPlatformRuntimeChanged() {
  window.dispatchEvent(new Event(PLATFORM_RUNTIME_CHANGED_EVENT))
}
