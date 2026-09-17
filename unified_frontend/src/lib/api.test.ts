import { siteFrameUrl } from '../components/guard_behavior/api'

if (!siteFrameUrl(12).endsWith('/api/guard-behavior/sites/12/frame.jpg')) {
  throw new Error('expected native Guard Behavior frame endpoint')
}
