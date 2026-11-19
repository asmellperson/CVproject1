export const STATUS_ELAPSED_HEADER = 'X-AiVision-Status-Elapsed-Ms'

export type StatusRequestTiming = {
  startedAt: number
  receivedAt: number
  serverElapsed: string | null
}

export type StatusFreshness = { sampledAt: string | null; expiresAt: number }

export function hasTimedStatus(state: string | undefined): boolean {
  return state === 'ready' || state === 'error'
}

export function statusFreshness(
  sampledAt: string | null,
  validForSeconds: number,
  timing: StatusRequestTiming,
  previous: StatusFreshness | null,
): StatusFreshness {
  const { startedAt, receivedAt, serverElapsed } = timing
  const measured = serverElapsed !== null && /^\d+$/.test(serverElapsed) ? Number(serverElapsed) : 0
  // 只有可归入这一次请求的后端时长才用于补偿，代理与传输的未知时间仍按保守值扣除。
  const safeElapsed = Number.isSafeInteger(measured) && measured <= receivedAt - startedAt ? measured : 0
  const remaining = Number.isFinite(validForSeconds) ? Math.max(0, validForSeconds) * 1000 : 0
  const expiresAt = startedAt + safeElapsed + remaining
  // 保留上一次同帧的截止时间，即使界面已经撤销了该帧，也不能让后续轮询使它复活。
  return { sampledAt, expiresAt: sampledAt !== null && previous?.sampledAt === sampledAt
    ? Math.min(expiresAt, previous.expiresAt) : expiresAt }
}
