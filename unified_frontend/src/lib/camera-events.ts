export const PLATFORM_CAMERAS_CHANGED_EVENT = 'platform:cameras-changed'

export function notifyPlatformCamerasChanged() {
  window.dispatchEvent(new Event(PLATFORM_CAMERAS_CHANGED_EVENT))
}
