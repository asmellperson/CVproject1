export type FeatureCameraCounts = Record<string, {
  cameraCount: number
  enabledCameraCount: number
}>

type CameraInventoryItem = {
  enabled: boolean
  functions: Record<string, boolean> | string[]
}

const AI_VISION_FEATURES = [
  'blocks',
  'detect_door',
  'detect_face',
  'detect_human',
  'detect_logistics_single_person',
  'detect_logistics_single_person_electronics_electrician',
  'detect_logistics_single_person_electrical_components',
  'detect_logistics_single_person_precious_metal_recycling',
  'detect_phone',
]

function hasFeature(camera: CameraInventoryItem, feature: string) {
  return Array.isArray(camera.functions)
    ? camera.functions.includes(feature)
    : Boolean(camera.functions?.[feature])
}

export function getLoadedAiVisionFeatureCounts(
  cameras: CameraInventoryItem[],
  loaded: boolean,
): FeatureCameraCounts | undefined {
  if (!loaded) return undefined
  return AI_VISION_FEATURES.reduce<FeatureCameraCounts>((counts, feature) => {
    const featureCameras = cameras.filter((camera) => hasFeature(camera, feature))
    counts[feature] = {
      cameraCount: featureCameras.length,
      enabledCameraCount: featureCameras.filter((camera) => camera.enabled).length,
    }
    return counts
  }, {})
}
