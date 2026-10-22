import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Info, Picker, Quota, Ttl } from '../types'

const info = atom({ plugin: 'session-bar', key: 'info' } as const, {
  model: null,
  effort: null,
  lastRequestAt: null,
  ttl: null,
} as Info)
const picking = atom({ plugin: 'session-bar', key: 'picking' } as const, null as Picker)
const quotasOpen = atom({ plugin: 'session-bar', key: 'quotasOpen' } as const, false)

const ACTION = '#8caaee'
const DIM = '#51576d'

/** The models the selector offers, each in its Catppuccin Frappé colour. */
const MODELS = [
  { id: 'claude-opus-5-5', color: '#ef9f76' },
  { id: 'claude-fable-5-1', color: '#ca9ee6' },
  { id: 'claude-sonnet-5-5', color: '#8caaee' },
  { id: 'claude-haiku-4-5-20251001', color: '#a6d189' },
] as const

/** The effort scale, in the colours `/effort` gives each level (Claude Code's dark theme). */
const EFFORTS = [
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

const effortLabel = (level: string | null): string => level ?? 'default'

export type Scheme = 'dark' | 'light'

/**
 * Each colour the bar draws, as written for a dark background, with its twin
 * for a light one: Catppuccin Latte for Frappé; for the status line's bright
 * grading and `/effort`'s colours, the nearest tone that reads on white.
 */
const LIGHT: Record<string, string> = {
  '#a6d189': '#40a02b',
  '#e5c890': '#9a6700',
  '#e78284': '#d20f39',
  '#ef9f76': '#fe640b',
  '#8caaee': '#1e66f5',
  '#ca9ee6': '#8839ef',
  '#a5adce': '#6c6f85',
  '#c6d0f5': '#4c4f69',
  '#51576d': '#bcc0cc',
  '#8a8a8a': '#7c7f93',
  '#5fff00': '#40a02b',
  '#ffff00': '#9a6700',
  '#ffaf00': '#fe640b',
  '#ff0000': '#d20f39',
  '#ffc107': '#9a6700',
  '#4eba65': '#40a02b',
  '#b1b9f9': '#7287fd',
  '#af87ff': '#8839ef',
  '#eb5f57': '#d20f39',
}

const swap = (props: Record<string, unknown>): Record<string, unknown> =>
  Object.fromEntries(Object.entries(props).map(([k, v]) => [k, typeof v === 'string' ? (LIGHT[v] ?? v) : v]))

export const recolor = <T,>(node: T, scheme: Scheme): T => {
  if (scheme === 'dark' || node === null || typeof node !== 'object') return node
  if (Array.isArray(node)) return node.map(child => recolor(child, scheme)) as T
  const el = node as { props?: Record<string, unknown>; hover?: Record<string, unknown>; children?: unknown[] }
  return {
    ...el,
    ...(el.props && { props: swap(el.props) }),
    ...(el.hover && { hover: swap(el.hover) }),
    ...(el.children && { children: el.children.map(child => recolor(child, scheme)) }),
  } as T
}

/** macOS's appearance: `AppleInterfaceStyle` is `Dark` in dark mode and unset in light mode; dark elsewhere. */
async function readScheme($: EngineInterface): Promise<Scheme> {
  const r = await $.process.run(['defaults', 'read', '-g', 'AppleInterfaceStyle'])
  if (r.exitCode === 0) return 'dark'
  return /does not exist/.test(r.stderr) ? 'light' : 'dark'
}

/** An alias `/model` takes (`opus`, `sonnet[1m]`) → the id the selector offers; an id as given. */
export const modelId = (model: string): string => {
  if (model.includes('claude-')) return model
  const family = /^[a-z]+/.exec(model.toLowerCase())?.[0]
  return MODELS.find(m => family && m.id.startsWith(`claude-${family}-`))?.id ?? model
}

/** `claude-opus-5-5[1m]` → `Opus 5.5`; anything else as given. */
export const prettyModel = (id: string): string => {
  const m = /claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?/.exec(id)
  if (!m) return id
  const name = m[1]!.charAt(0).toUpperCase() + m[1]!.slice(1)
  return m[3] ? `${name} ${m[2]}.${m[3]}` : `${name} ${m[2]}`
}

export const duration = (ms: number): string => {
  const s = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}h${String(m).padStart(2, '0')}m`
  if (m > 0) return `${m}m${String(sec).padStart(2, '0')}s`
  return `${sec}s`
}

/** Prompt-cache time left, as the status line counts it: whole minutes, `<1m` in the last one. */
export const minutesLeft = (ms: number): string => (ms < 60_000 ? '<1m' : `${Math.floor(ms / 60_000)}m`)

/** The status line's grading: green while half the TTL is left, yellow down to a fifth, then orange. */
export const cacheColor = (left: number, ttl: number): string =>
  left * 2 >= ttl ? '#5fff00' : left * 5 >= ttl ? '#ffff00' : '#ffaf00'

const ttlMs = (ttl: Ttl): number => (ttl === '1h' ? 3_600_000 : 300_000)

/** The status line's defaults: the auto-compact window, and how far below it compaction fires. */
const WINDOW = 200_000
const RESERVE = 33_000
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
const whole = (value: unknown): number | null => {
  const n = typeof value === 'string' && /^\d{1,12}$/.test(value) ? Number(value) : value
  return typeof n === 'number' && Number.isInteger(n) && n > 0 ? n : null
}

/**
 * The auto-compact trigger as the engine sets it (/context's figures); where
 * the engine gives none, as the status line reckons it: CC_TOKEN_LIMIT, else
 * `autoCompactWindow`, else 200k; less CC_TOKEN_RESERVE.
 */
async function readLimit($: EngineInterface): Promise<Limit> {
  const b = (await $.session.usage({ breakdown: 'summary' })).context.breakdown
  if (b?.autoCompactThreshold && b.autoCompactThreshold > 0)
    return { limit: b.autoCompactThreshold, window: Math.max(b.rawMaxTokens, b.autoCompactThreshold) }
  if (b && !b.isAutoCompactEnabled && b.rawMaxTokens > 0) return { limit: b.rawMaxTokens, window: b.rawMaxTokens }
  const window = whole(await $.env.get('CC_TOKEN_LIMIT')) ?? whole((await $.settings.read()).autoCompactWindow) ?? WINDOW
  const limit = window - (whole(await $.env.get('CC_TOKEN_RESERVE')) ?? RESERVE)
  return { limit: limit > 0 ? limit : window, window }
}

/** The rate-limit windows the status line shows, by their length. */
const WINDOWS: Record<string, { label: string; ms: number }> = {
  five_hour: { label: '5h', ms: 18_000_000 },
  seven_day: { label: '7d', ms: 604_800_000 },
}
/** Share of a window that must elapse before its pace is judged, as the status line's CC_PACE_MIN. */
const PACE_MIN = 0.1
const TONE = { ok: '#a6d189', tight: '#e5c890', out: '#e78284' } as const

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

/**
 * Selects the session's model and effort before its first turn reports them:
 * the model `/model` shows, the effort from the variable or the settings it saves to.
 */
async function seedModel($: EngineInterface) {
  const model = modelId(await $.session.model())
  const saved = (await $.env.get('CLAUDE_CODE_EFFORT_LEVEL')) ?? (await $.settings.read()).effortLevel
  const effort = typeof saved === 'string' && EFFORTS.some(e => e.level === saved) ? saved : null
  await update($, info, i => ({ ...i, model: i.model ?? model, effort: i.effort ?? effort }))
}

export const register: Register = (on, options) => {
  const defaultTtl: Ttl = options.cacheTtl === '5m' ? '5m' : '1h'
  let ticker: { cancel: () => void } | null = null
  let limit: Limit = { limit: WINDOW - RESERVE, window: WINDOW }
  let scheme: Scheme = 'dark'

  on('session.start', async ($, e, next) => {
    await update($, picking, () => null)
    ticker?.cancel()
    let ticks = 0
    ticker = $.clock.every(1000, () => {
      ticks++
      if (ticks % 5 === 0) void readScheme($).then(s => (scheme = s))
      if (ticks % 30 === 0) void readLimit($).then(n => (limit = n))
      $.ui.invalidate('ui.render')
    })
    limit = await readLimit($)
    scheme = await readScheme($)
    await seedModel($)
    return next(e)
  })

  on('classic.PreModelSwitch', async ($, e, next) => {
    await update($, info, i => ({ ...i, ttl: e.cache_ttl }))
    return next(e)
  })

  on('turn.step', async function* ($, e, next) {
    if (!e.agentId) await update($, info, i => ({ ...i, model: e.model, effort: e.effort === undefined ? null : String(e.effort) }))
    const result = yield* next(e)
    if (!e.agentId) {
      const now = await $.clock.now()
      await update($, info, i => ({ ...i, lastRequestAt: now }))
    }
    return result
  })

  /** Beneath the prompt's hint line, the engine's own line kept live above the bar. */
  on('ui.render', { component: 'PromptHint' }, async ($, e, next) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const hint = await next(e)
    const [now, i, picker, isQuotasOpen, usage] = await Promise.all([
      $.clock.now(),
      read($, info),
      read($, picking),
      read($, quotasOpen),
      $.session.usage(),
    ])

    const ttl = i.ttl ?? defaultTtl
    const cache =
      i.lastRequestAt === null
        ? { text: 'no request yet', color: undefined }
        : (() => {
            const left = i.lastRequestAt + ttlMs(ttl) - now
            if (left <= 0) return { text: 'expired', color: '#ff0000' }
            return { text: minutesLeft(left), color: cacheColor(left, ttlMs(ttl)) }
          })()
    const context = contextOf(usage.context.tokens, limit)
    const quotas = usage.rateLimits.map(l => quotaOf(l.kind, l.percentUsed, l.resetsAt, now)).filter((q): q is Quota => q !== null)

    const columns = Math.max(12, (e.viewport?.columns ?? 80) - 2)
    const isBright = Math.floor(now / 1000) % 2 === 0
    const hot = (key: string, color: string = ACTION) => ({ scope: key.slice(-64), color })

    /** A coloured dot and a label that presses: Button takes no colour of its own. */
    const chip = (key: string, label: string, color: string, onPress: () => unknown, dot = '●') => (
      <Box key={`${key}:chip`} flexDirection="row" flexShrink={0}>
        <Text color={color}>{dot} </Text>
        <Button key={key} label={label} plain hover={hot(key, color)} onPress={onPress} />
      </Box>
    )

    const toggle = (which: Exclude<Picker, null>) => update($, picking, cur => (cur === which ? null : which))
    const pickModel = async (id: string) => {
      await update($, picking, () => null)
      await update($, info, cur => ({ ...cur, model: id }))
      await $.command.run({ command: 'model', args: id })
    }
    const pickEffort = async (level: string) => {
      await update($, picking, () => null)
      await update($, info, cur => ({ ...cur, effort: level }))
      await $.command.run({ command: 'effort', args: level })
    }
    const toggleQuotas = () => update($, quotasOpen, cur => !cur)

    const options =
      picker === 'model'
        ? MODELS.map(m => chip(`model:${m.id}`, prettyModel(m.id), m.color, () => pickModel(m.id), i.model !== null && modelColor(i.model) === m.color ? '●' : '○'))
        : picker === 'effort'
          ? EFFORTS.map(l => chip(`effort:${l.level}`, effortLabel(l.level), l.color, () => pickEffort(l.level), i.effort === l.level ? '●' : '○'))
          : null

    const quotaBar = (q: Quota, width: number) => (
      <Box key={`quota:${q.label}`} flexDirection="column" width={width}>
        <Box flexDirection="row" justifyContent="space-between">
          <Text>
            <Text dimColor>{q.label} </Text>
            <Text bold color={TONE[q.verdict?.tone ?? 'ok']}>
              {q.used}%
            </Text>
            {q.verdict && <Text color={TONE[q.verdict.tone]}> {q.verdict.text}</Text>}
          </Text>
          {q.resetsIn !== null && <Text dimColor>🔄 {span(q.resetsIn)}</Text>}
        </Box>
        <Text>
          {barRuns(q, width).map((run, k) => (
            <Text key={`run:${k}`} color={run.color} bold={run.isPace} dimColor={run.isAhead && q.verdict?.tone !== 'ok' && !isBright}>
              {run.text}
            </Text>
          ))}
        </Text>
      </Box>
    )

    const bar = (
      <Box flexDirection="column">
        {hint}
        <Box flexDirection="row" flexWrap="wrap" columnGap={3} justifyContent="space-between">
          <Box flexDirection="row" columnGap={3} flexShrink={0}>
            <Text>
              ⌛ <Text dimColor>running </Text>
              {duration(now - usage.startedAt)}
            </Text>
            <Text>
              ⏳ <Text dimColor>cache </Text>
              <Text color={cache.color}>{cache.text}</Text>
            </Text>
            <Text wrap="truncate-end">
              <Text dimColor>context </Text>
              <Text bold color={context.color} inverse={context.isCompacting}>
                {context.text}
              </Text>
            </Text>
          </Box>
          <Box flexDirection="row" columnGap={2} flexShrink={0}>
            {chip('pick:model', i.model ? prettyModel(i.model) : 'model…', modelColor(i.model), () => toggle('model'), picker === 'model' ? '●' : '○')}
            {chip('pick:effort', effortLabel(i.effort), effortColor(i.effort), () => toggle('effort'), picker === 'effort' ? '●' : '○')}
            {quotas.length > 0 && (
              <Box key="quotas:row" flexDirection="row" flexShrink={0}>
                {quotas.map((q, k) => (
                  <Box key={`quotas:${q.label}:row`} flexDirection="row">
                    {k > 0 && <Text dimColor> │ </Text>}
                    <Text color={TONE[q.verdict?.tone ?? 'ok']}>● </Text>
                    <Button key={`quotas:${q.label}`} label={`${q.label} ${q.used}%`} plain hover={{ color: TONE[q.verdict?.tone ?? 'ok'] }} onPress={toggleQuotas} />
                  </Box>
                ))}
                <Button key="quotas:fold" label={isQuotasOpen ? ' 🔼' : ' 🔽'} plain hover={hot('quotas:fold')} onPress={toggleQuotas} />
              </Box>
            )}
          </Box>
        </Box>
        {options && (
          <Box flexDirection="row" flexWrap="wrap" columnGap={2} justifyContent="flex-end">
            {options}
          </Box>
        )}
        {isQuotasOpen && quotas.length > 0 && (
          <Box flexDirection="row" columnGap={3}>
            {quotas.map(q => quotaBar(q, Math.floor((columns - 3 * (quotas.length - 1)) / quotas.length)))}
          </Box>
        )}
      </Box>
    )
    return recolor(bar, scheme)
  })
}
