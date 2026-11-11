import type { Quota, Ttl } from '../types'

/** The colour an action without its own takes under the pointer: Catppuccin Frappé blue. */
export const ACTION = '#8caaee'
const DIM = '#51576d'

/** The models the selector offers, each in its Catppuccin Frappé colour. */
export const MODELS = [
  { id: 'claude-opus-5-5', color: '#ef9f76' },
  { id: 'claude-fable-5-1', color: '#ca9ee6' },
  { id: 'claude-sonnet-5-5', color: '#8caaee' },
  { id: 'claude-haiku-4-5-20251001', color: '#a6d189' },
] as const

/** The effort scale, in the colours `/effort` gives each level (Claude Code's dark theme). */
export const EFFORTS = [
  { level: 'low', color: '#ffc107' },
  { level: 'medium', color: '#4eba65' },
  { level: 'high', color: '#b1b9f9' },
  { level: 'xhigh', color: '#af87ff' },
  { level: 'max', color: '#eb5f57' },
] as const

export const modelColor = (id: string | null): string => {
  const family = id ? /claude-([a-z]+)/.exec(id)?.[1] : undefined
  return MODELS.find(m => family && m.id.startsWith(`claude-${family}`))?.color ?? '#a5adce'
}

export const effortColor = (level: string | null): string => EFFORTS.find(e => e.level === level)?.color ?? '#a5adce'

export const effortLabel = (level: string | null): string => level ?? 'default'

/** An alias `/model` takes (`opus`, `sonnet[1m]`) → the id the selector offers; an id as given. */
export const modelId = (model: string): string => {
  if (model.includes('claude-')) return model
  const family = /^[a-z]+/.exec(model.toLowerCase())?.[0]
  return MODELS.find(m => family && m.id.startsWith(`claude-${family}-`))?.id ?? model
}

/** Prompt-cache time left, as the status line counts it: whole minutes, `<1m` in the last one. */
export const minutesLeft = (ms: number): string => (ms < 60_000 ? '<1m' : `${Math.floor(ms / 60_000)}m`)

/** The status line's grading: green while half the TTL is left, yellow down to a fifth, then orange. */
export const cacheColor = (left: number, ttl: number): string =>
  left * 2 >= ttl ? '#5fff00' : left * 5 >= ttl ? '#ffff00' : '#ffaf00'

export const ttlMs = (ttl: Ttl): number => (ttl === '1h' ? 3_600_000 : 300_000)

/** The status line's defaults: the auto-compact window, and how far below it compaction fires. */
export const WINDOW = 200_000
export const RESERVE = 33_000
/** Where the context counter turns yellow, orange and red, as shares of the limit (CC_TOKEN_WARN, _DANGER, _ALERT). */
const STAGES = [0.5, 0.75, 0.9] as const

/** The auto-compact trigger (`limit`) and the window it sits a margin below. */
export type Limit = { limit: number; window: number }

/** `78234` → `78.2k`, `934` → `934`, as the status line counts tokens. */
export const kfmt = (n: number): string => (n < 1000 ? String(n) : `${Math.floor(n / 1000)}.${Math.floor((n % 1000) / 100)}k`)

const cap = (n: number): string => (n % 1000 === 0 ? `${n / 1000}k` : kfmt(n))

/**
 * The context counter: tokens against the auto-compact trigger, how it is
 * reckoned in brackets (`250k − 33k`), green to half of the trigger, yellow to
 * three quarters, orange to nine tenths, then red, and compacting once reached.
 */
export const contextOf = (tokens: number | undefined, { limit, window }: Limit): { text: string; color: string; isCompacting: boolean } => {
  const sum = window > limit ? ` (${cap(window)} − ${cap(window - limit)})` : ''
  if (tokens === undefined) return { text: `0/${cap(limit)}${sum}`, color: '#8a8a8a', isCompacting: false }
  const text = `${kfmt(tokens)}/${cap(limit)}${sum} ${Math.floor((tokens * 100) / limit)}%`
  if (tokens >= limit) return { text: `${text} ⚠ compacting`, color: '#ff0000', isCompacting: true }
  const stage = STAGES.findIndex(share => tokens <= limit * share)
  return { text, color: ['#5fff00', '#ffff00', '#ffaf00'][stage] ?? '#ff0000', isCompacting: false }
}

/** A whole positive number, from a number or its digits; null otherwise. */
export const whole = (value: unknown): number | null => {
  const n = typeof value === 'string' && /^\d{1,12}$/.test(value) ? Number(value) : value
  return typeof n === 'number' && Number.isInteger(n) && n > 0 ? n : null
}

/** The rate-limit windows the status line shows, by their length. */
const WINDOWS: Record<string, { label: string; ms: number }> = {
  five_hour: { label: '5h', ms: 18_000_000 },
  seven_day: { label: '7d', ms: 604_800_000 },
}
/** Share of a window that must elapse before its pace is judged, as the status line's CC_PACE_MIN. */
const PACE_MIN = 0.1
export const TONE = { ok: '#a6d189', tight: '#e5c890', out: '#e78284' } as const

/** Coarse time left, as the status line writes it: `2d07h`, `3h14m`, `42m`. */
export const span = (ms: number): string => {
  const m = Math.max(0, Math.floor(ms / 60_000))
  const d = Math.floor(m / 1440)
  const h = Math.floor((m % 1440) / 60)
  if (d > 0) return `${d}d${String(h).padStart(2, '0')}h`
  if (h > 0) return `${h}h${String(m % 60).padStart(2, '0')}m`
  return `${m}m`
}

/**
 * A rate-limit window read as the status line reads it: the average burn so
 * far extrapolated to the reset lands under 90% (ok), at 90-100% (tight), or
 * runs out before it; judged once a tenth of the window has elapsed.
 */
export const quotaOf = (kind: string, percentUsed: number, resetsAt: string | undefined, now: number): Quota | null => {
  const win = WINDOWS[kind]
  if (!win) return null
  const used = Math.round(percentUsed)
  const reset = resetsAt ? Date.parse(resetsAt) : NaN
  const resetsIn = Number.isFinite(reset) && reset > now ? Math.min(reset - now, win.ms) : null
  const elapsed = resetsIn === null ? null : (win.ms - resetsIn) / win.ms
  let verdict: Quota['verdict'] = null
  if (used >= 100) verdict = { text: 'max', tone: 'out' }
  else if (elapsed !== null && elapsed > 0 && elapsed >= PACE_MIN) {
    const projected = Math.round(used / elapsed)
    if (projected > 100) {
      const dry = ((100 - used) * elapsed * win.ms) / Math.max(used, 1)
      verdict = { text: `out in ${span(dry)}`, tone: 'out' }
    } else verdict = { text: `→${projected}%`, tone: projected >= 90 ? 'tight' : 'ok' }
  }
  return { label: win.label, used, elapsed, verdict, resetsIn }
}

export type BarRun = { text: string; color: string; isPace?: boolean; isAhead?: boolean }

/**
 * A quota bar `width` cells wide, in half-cell steps: fill up to the pace tick
 * in green, fill past it (ahead of even spending) in the verdict's colour, the
 * rest a faint track; the tick marks where even spending would be by now.
 */
export const barRuns = (q: Quota, width: number): BarRun[] => {
  const tone = TONE[q.verdict?.tone ?? 'ok']
  const halves = Math.round((Math.min(q.used, 100) / 100) * width * 2)
  const pace = q.elapsed === null ? -1 : Math.min(width - 1, Math.round(q.elapsed * width))
  const runs: BarRun[] = []
  const push = (text: string, color: string, flags: Omit<BarRun, 'text' | 'color'> = {}) => {
    const last = runs[runs.length - 1]
    if (last && last.color === color && !last.isPace && !flags.isPace && !!last.isAhead === !!flags.isAhead) last.text += text
    else runs.push({ text, color, ...flags })
  }
  for (let cell = 0; cell < width; cell++) {
    const filled = halves - cell * 2
    const isAhead = pace >= 0 && cell > pace
    if (cell === pace) push('┃', '#c6d0f5', { isPace: true })
    else if (filled >= 2) push('━', isAhead ? tone : TONE.ok, { isAhead })
    else if (filled === 1) push('╸', isAhead ? tone : TONE.ok, { isAhead })
    else push('─', DIM)
  }
  return runs
}
