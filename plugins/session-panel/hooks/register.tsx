import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, RenderElement, ToolCallInput, ToolCallResult, UiCopyArgs } from 'claude-code'

import type { Agent, Entry, FileChange, Handover, HandoverFile, Info, Note, NotesRoot, Picker, Quota, RepoChanges, Step, Tab, TrackedIssue, TrackedPr, Ttl } from '../types'

import { LOG_FORMAT, parseLog, parseNumstat, parseStatus, treeRows } from './files'
import { noteGroups, noteOf, notePaths } from './notes'
import { PR_COLOR, RANK, findRefs, linearOfResult, prState, refsOfGh, repoOfRemote, titleOfSlug } from './tracker'
import type { GithubRef, LinearRef } from './tracker'

const PANE = 'session-panel'
const TITLE = 'Session'
/** The dock's opening width in fullscreen; a width the person dragged or keyed wins. */
const DOCK_COLUMNS = 116
const HISTORY_CAP = 400
/** An open sub-agent's latest entries and the head of its task: the whole of either can pass the engine's 100,000 drawn characters. */
const OPEN_HISTORY = 40
const OPEN_PROMPT = 4000
const STEPS_CAP = 300
/** Finished steps shown while the list is folded, above the current one. */
const DONE_SHOWN = 4

const info = atom({ plugin: 'session-panel', key: 'info' } as const, {
  model: null,
  effort: null,
  lastRequestAt: null,
  ttl: null,
} as Info)
const agents = atom({ plugin: 'session-panel', key: 'agents' } as const, [] as Agent[])
const steps = atom({ plugin: 'session-panel', key: 'steps' } as const, [] as Step[])
const expanded = atom({ plugin: 'session-panel', key: 'expanded' } as const, null as string | null)
const stepsOpen = atom({ plugin: 'session-panel', key: 'stepsOpen' } as const, false)
const roots = atom({ plugin: 'session-panel', key: 'roots' } as const, [] as string[])
const changes = atom({ plugin: 'session-panel', key: 'changes' } as const, [] as RepoChanges[])
const UNTRACKED_COUNTED = 30
const COMMITS_SHOWN = 8
const EDITING_TOOLS = new Set(['Edit', 'MultiEdit', 'Write', 'NotebookEdit', 'Bash'])
const prompts = atom({ plugin: 'session-panel', key: 'prompts' } as const, [] as string[])
const view = atom({ plugin: 'session-panel', key: 'view' } as const, 'overview' as 'overview' | 'prompts')
/** The linked worktree the session last edited in, by its folder's name; null in a main checkout. */
const worktree = atom({ plugin: 'session-panel', key: 'worktree' } as const, null as string | null)
const picking = atom({ plugin: 'session-panel', key: 'picking' } as const, null as Picker)
const tracker = atom({ plugin: 'session-panel', key: 'tracker' } as const, { issue: null, pr: null, mentioned: [] } as {
  issue: TrackedIssue | null
  pr: TrackedPr | null
  mentioned: string[]
})
const handover = atom({ plugin: 'session-panel', key: 'handover' } as const, null as Handover | null)
const notes = atom({ plugin: 'session-panel', key: 'notes' } as const, [] as Note[])
/** The quota bars unfolded beneath the top lines, from the quota pill. */
const quotasOpen = atom({ plugin: 'session-panel', key: 'quotasOpen' } as const, false)
const tab = atom({ plugin: 'session-panel', key: 'tab' } as const, 'main' as Tab)
/** The session's overall topic, as the main agent names it with the session_title tool. */
const topic = atom({ plugin: 'session-panel', key: 'topic' } as const, null as string | null)
/** The session whose title is set, and the one reminded to set it: a title carried over through /clear or a reload belongs to another. */
const titled = atom({ plugin: 'session-panel', key: 'titled' } as const, { set: null, reminded: null } as { set: string | null; reminded: string | null })
const WRITING_TOOLS = new Set(['Edit', 'MultiEdit', 'Write', 'NotebookEdit'])
let notesRoot: NotesRoot | null = null
/** Main-loop calls that returned, possibly before the step that made them ended. */
const returned = new Set<string>()
let hasLinearApp = false
const home = atom({ plugin: 'session-panel', key: 'home' } as const, null as string | null)
const LINEAR_ID = /\b[A-Z][A-Z0-9]{1,9}-\d+\b/g
const ISSUE_ICON = { github: { glyph: '◉', color: '#3fb950' }, linear: { glyph: '◐', color: '#5e6ad2' } } as const

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

export const effortColor = (level: string | null): string =>
  EFFORTS.find(e => e.level === level)?.color ?? '#a5adce'

export type Scheme = 'dark' | 'light'

/**
 * Each colour the pane draws, as written for a dark background, with its twin
 * for a light one: Catppuccin Latte for Frappé; for the status line's bright
 * grading, GitHub's and `/effort`'s colours, the nearest tone that reads on white.
 */
const LIGHT: Record<string, string> = {
  '#a6d189': '#40a02b',
  '#e5c890': '#9a6700',
  '#e78284': '#d20f39',
  '#ef9f76': '#fe640b',
  '#8caaee': '#1e66f5',
  '#ca9ee6': '#8839ef',
  '#babbf1': '#7287fd',
  '#81c8be': '#179299',
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
  '#3fb950': '#1a7f37',
  '#f85149': '#cf222e',
  '#a371f7': '#8250df',
}

const swap = (props: Record<string, unknown>): Record<string, unknown> =>
  Object.fromEntries(Object.entries(props).map(([k, v]) => [k, typeof v === 'string' ? (LIGHT[v] ?? v) : v]))

/** The pane's tree for the OS appearance: on a light one, every colour swapped for its twin (LIGHT). */
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

const effortLabel = (level: string | null): string => {
  const rank = EFFORTS.findIndex(e => e.level === level)
  return rank < 0 ? (level ?? 'default') : `${level} ${rank + 1}/${EFFORTS.length}`
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
  const whole = (value: unknown) => {
    const n = typeof value === 'string' && /^\d{1,12}$/.test(value) ? Number(value) : value
    return typeof n === 'number' && Number.isInteger(n) && n > 0 ? n : null
  }
  const window = whole(await $.env.get('CC_TOKEN_LIMIT')) ?? whole((await $.settings.read()).autoCompactWindow) ?? WINDOW
  const limit = window - (whole(await $.env.get('CC_TOKEN_RESERVE')) ?? RESERVE)
  return { limit: limit > 0 ? limit : window, window }
}

/** The message the closing reply hands the next session: its code block after `/clear`, on one line, as the handover plugin reads it. */
export const resumeMessage = (reply: string): string | null => {
  const at = reply.search(/\/clear\b/)
  const block = at < 0 ? null : /```[^\n]*\n([\s\S]*?)```/.exec(reply.slice(at))
  return block ? block[1]!.split(/\s+/).filter(Boolean).join(' ') || null : null
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
    else push('─', '#51576d')
  }
  return runs
}

/** How long ago, coarsely: minutes within the hour, then hours, then days. */
export const ago = (ms: number): string => {
  const minutes = Math.floor(Math.max(0, ms) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hour${hours > 1 ? 's' : ''} ago`
  const days = Math.floor(hours / 24)
  return `${days} day${days > 1 ? 's' : ''} ago`
}

const oneLine = (text: string, max = 160): string => {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat
}

/** The first sentence of a block of thinking or text: a step's headline. */
export const headline = (text: string): string => {
  const flat = text.replace(/\s+/g, ' ').trim()
  const end = flat.search(/[.!?](\s|$)/)
  return end > 0 ? flat.slice(0, end + 1) : flat
}

/** What a tool call is about, in a few words. */
export const describeCall = (tool: string, input: Record<string, unknown>): string => {
  for (const field of ['description', 'command', 'file_path', 'pattern', 'url', 'query', 'prompt', 'skill']) {
    const value = input[field]
    if (typeof value === 'string' && value.trim()) return `${tool}: ${oneLine(value, 100)}`
  }
  return tool
}

const SIGN: Record<FileChange['status'], string> = { added: '+', modified: '~', deleted: '−' }
const SIGN_COLOR: Record<FileChange['status'], string> = { added: '#a6d189', modified: '#e5c890', deleted: '#e78284' }

const fileName = (path: unknown) => (typeof path === 'string' ? path.split('/').pop() : undefined)

/** What a call does, in the agent's words where it gave some, and how. */
export const intentOf = (tool: string, input: Record<string, unknown>): { what: string; how?: string } => {
  const how = ['command', 'file_path', 'notebook_path', 'pattern', 'url', 'query', 'skill']
    .map(field => input[field])
    .find((value): value is string => typeof value === 'string' && value.trim() !== '')
  const description = typeof input.description === 'string' ? input.description.trim() : ''
  if (description) return { what: description, how: how && oneLine(how, 200) }
  const name = fileName(input.file_path ?? input.notebook_path)
  if (name) return { what: `${tool === 'Write' ? 'Write' : tool === 'Read' ? 'Read' : 'Edit'} ${name}`, how: String(input.file_path ?? input.notebook_path) }
  return { what: describeCall(tool, input), how: undefined }
}

/**
 * The text a person typed, without the tags the engine wraps around it: a
 * slash command's echo (`<command-name>`) or an injected block yields null.
 */
export const promptText = (raw: string): string | null => {
  if (/<command-name>|<local-command-|<task-notification>/.test(raw)) return null
  const text = raw
    .replace(/<(system-reminder|local-command-caveat|local-command-stdout)>[\s\S]*?<\/\1>/g, '')
    .replace(/<\/?[a-zA-Z][\w-]*(\s[^>]*)?>/g, '')
    .trim()
  return text || null
}

/** The last whole sentence of a text being streamed, once there is one. */
export const lastSentence = (text: string): string | null => {
  const sentences = text.replace(/\s+/g, ' ').match(/[^.!?]+[.!?]+(?=\s|$)/g)
  return sentences?.length ? sentences[sentences.length - 1]!.trim() : null
}

/** A step is current while its answer streams or a call it made has not returned. */
export const isRunning = (s: Step): boolean => !s.isDone || !(s.toolIds ?? []).every(id => s.doneIds?.includes(id))

/** A handover's title: its front matter's `summary`, else its `# Handover:` heading. */
export const handoverTitle = (text: string): string | null => {
  const front = /^---\n([\s\S]*?)\n---/.exec(text)?.[1]
  const summary = front && /^summary:\s*["']?(.+?)["']?\s*$/m.exec(front)?.[1]
  return summary || /^#\s*Hand(?:over|off):\s*(.+)$/m.exec(text)?.[1]?.trim() || null
}

/** A handover file's length and last change, `142 lines · 2026-10-07 09:32` in local time; null when neither is known. */
export const fileMeta = (lines: number | null, modifiedAt: number | null): string | null => {
  const pad = (n: number) => String(n).padStart(2, '0')
  const d = modifiedAt === null ? null : new Date(modifiedAt)
  const parts = [
    lines === null ? null : `${lines} ${lines === 1 ? 'line' : 'lines'}`,
    d && `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`,
  ].filter(Boolean)
  return parts.length ? parts.join(' · ') : null
}

const kilo = (n: number) => (n < 1000 ? String(n) : n < 10_000 ? `${(n / 1000).toFixed(1)}k` : `${Math.floor(n / 1000)}k`)

/** What the handover plugin's status line says, in the same words and colours. */
export const handoverStatus = (h: Handover, tokens: number): { text: string; color: string } => {
  if (h.error) return { text: `failed · ${h.error}`, color: '#e78284' }
  if (h.isWriting) return { text: 'writing…', color: '#ef9f76' }
  if (h.written) return { text: 'ready · run /clear', color: '#a6d189' }
  const suggested = h.suggest > 0 && tokens >= h.suggest
  if (!h.trigger) return { text: suggested ? 'suggested' : 'trigger off', color: '#a5adce' }
  if (tokens >= h.trigger) return { text: 'wind-down on the next tool call', color: '#ef9f76' }
  return {
    text: `${suggested ? 'suggested · ' : ''}triggers at ${kilo(h.trigger)} · now ${kilo(tokens)}`,
    color: tokens >= h.trigger - h.warn ? '#e5c890' : '#a5adce',
  }
}

/** The two ways to start the next session from a written handover, each in its Catppuccin Frappé colour. */
const NEXT_ACTIONS = [
  { key: 'handover:run', emoji: '🚀', label: 'Start with this prompt', color: '#a6d189', isSent: true },
  { key: 'handover:edit', emoji: '✏️', label: 'Edit the prompt first', color: '#8caaee', isSent: false },
] as const

export type HandoverPhase = 'winding' | 'writing' | 'ready'

/** Where a handover under way stands: winding down, being written, or written; null before it starts or once it failed. */
export const handoverPhase = (h: Handover, tokens: number): HandoverPhase | null => {
  if (h.error) return null
  if (h.written) return 'ready'
  if (h.isWriting) return 'writing'
  if (h.isWindingDown || (h.trigger > 0 && tokens >= h.trigger)) return 'winding'
  return null
}

/** Each phase of a handover under way, animated once a second by the pane's ticker. */
const PHASES: Record<HandoverPhase, { frames: readonly string[]; label: string; color: string; does: string }> = {
  winding: {
    frames: ['◐', '◓', '◑', '◒'],
    label: 'Winding down',
    color: '#e5c890',
    does: 'The handover has triggered: the tasks in progress and their sub-agents finish, nothing new starts.',
  },
  writing: {
    frames: ['✎   ', '✎·  ', '✎·· ', '✎···'],
    label: 'Writing the handover',
    color: '#ef9f76',
    does: 'A separate model writes the handover from the transcript; the session then writes its closing reply.',
  },
  ready: {
    frames: ['●', '◉'],
    label: 'Ready for the next session',
    color: '#a6d189',
    does: 'The handover is written and the session stopped: pick a next action.',
  },
}

/** A phase as drawn at `now`: its frame for this second, then its label. */
export const phaseLine = (phase: HandoverPhase, now: number): string => {
  const p = PHASES[phase]
  return `${p.frames[Math.floor(now / 1000) % p.frames.length]} ${p.label}`
}

/** Width of the Help tab's example column. */
const HELP_EXAMPLE = 34

/** Starts the handover's wind-down at once, as `/handover:trigger` does. */
const TRIGGER_NOW = { key: 'handover:trigger', emoji: '✋', label: 'Hand over now', color: '#e5c890' } as const

const ttlMs = (ttl: Ttl): number => (ttl === '1h' ? 3_600_000 : 300_000)

async function addEntry($: EngineInterface, agentId: string, entry: Entry) {
  await update($, agents, list =>
    list.map(a =>
      a.id === agentId
        ? { ...a, history: [...a.history, { ...entry, text: oneLine(entry.text, 400) }].slice(-HISTORY_CAP) }
        : a,
    ),
  )
}

/** Records one of a sub-agent's tool calls and its outcome in its history. */
async function logCall($: EngineInterface, agentId: string, e: ToolCallInput, ran: ToolCallResult) {
  await addEntry($, agentId, { kind: 'tool', text: describeCall(String(e.tool), e as unknown as Record<string, unknown>) })
  if (ran.deny !== undefined) await addEntry($, agentId, { kind: 'error', text: `denied: ${ran.deny}` })
  else if (ran.isError) await addEntry($, agentId, { kind: 'error', text: ran.text ?? 'failed' })
  else if (ran.text) await addEntry($, agentId, { kind: 'result', text: ran.text })
}

/** Marks the main-loop step a refused or failed call belongs to. */
async function flagStep($: EngineInterface, toolUseId: string, ran: ToolCallResult) {
  const flag: Step['flag'] = ran.deny !== undefined ? 'refused' : ran.isError ? 'failed' : undefined
  if (!flag) return
  const note = oneLine(ran.deny ?? ran.text ?? '', 160)
  await update($, steps, list => list.map((s): Step => (s.toolIds?.includes(toolUseId) ? { ...s, flag, note } : s)))
}

/** Adds the repository holding `dir` to those the Files section shows. */
async function trackRepo($: EngineInterface, dir: string) {
  const top = await $.process.run(['git', '-C', dir, 'rev-parse', '--show-toplevel'])
  const root = top.stdout.trim()
  if (top.exitCode !== 0 || !root) return
  await update($, roots, list => (list.includes(root) ? list : [...list, root]))
}

/** Reads each tracked repository's changes against HEAD, untracked files included. */
async function refreshFiles($: EngineInterface) {
  const next: RepoChanges[] = []
  const since = Math.floor((await $.session.usage()).startedAt / 1000)
  let tree: string | null = null
  for (const root of await read($, roots)) {
    const dirs = await $.process.run(['git', '-C', root, 'rev-parse', '--git-dir', '--git-common-dir'])
    const [gitDir, commonDir] = dirs.stdout.trim().split('\n')
    if (dirs.exitCode === 0 && gitDir !== commonDir) tree = root.split('/').pop() ?? root
    const status = await $.process.run(['git', '-C', root, 'status', '--porcelain=v1', '-z', '--untracked-files=all'])
    if (status.exitCode !== 0) continue
    const kinds = parseStatus(status.stdout)
    const counts = parseNumstat((await $.process.run(['git', '-C', root, 'diff', '--numstat', 'HEAD'])).stdout)
    let untracked = 0
    const files: FileChange[] = []
    for (const [path, kind] of kinds) {
      let count = counts.get(path)
      if (!count && kind === 'added' && untracked++ < UNTRACKED_COUNTED) {
        const diff = await $.process.run(['git', '-C', root, 'diff', '--no-index', '--numstat', '/dev/null', path])
        count = [...parseNumstat(diff.stdout).values()][0]
      }
      files.push({ path, status: kind, added: count?.added ?? 0, removed: count?.removed ?? 0 })
    }
    const log = await $.process.run(['git', '-C', root, 'log', `-n${COMMITS_SHOWN}`, `--since=@${since}`, `--format=${LOG_FORMAT}`])
    const ahead = await $.process.run(['git', '-C', root, 'rev-list', '@{u}..HEAD'])
    const unpushed = ahead.exitCode === 0 ? new Set(ahead.stdout.split('\n').filter(Boolean)) : ('all' as const)
    const commits = log.exitCode === 0 ? parseLog(log.stdout, unpushed) : []
    const branch = (await $.process.run(['git', '-C', root, 'branch', '--show-current'])).stdout.trim() || 'detached'
    if (files.length || commits.length) next.push({ root, branch, files, commits })
  }
  await update($, changes, () => next)
  await update($, worktree, () => tree)
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

/** Marks a main-loop call as returned, so the step that made it can end. */
async function markReturned($: EngineInterface, toolUseId: string) {
  await update($, steps, list =>
    list.map(s => (s.toolIds?.includes(toolUseId) ? { ...s, doneIds: [...(s.doneIds ?? []), toolUseId] } : s)),
  )
}

/** Keeps the issue or pull request seen with the best rank, the first one on a tie. */
async function keep($: EngineInterface, slot: 'issue' | 'pr', next: TrackedIssue | TrackedPr) {
  await update($, tracker, t => {
    const cur = t[slot]
    const same = cur && ('key' in cur ? cur.key : `${cur.repo}#${cur.number}`) === ('key' in next ? next.key : `${next.repo}#${next.number}`)
    if (same) return { ...t, [slot]: { ...next, rank: Math.min(cur.rank, next.rank) } }
    if (cur && cur.rank <= next.rank) return t
    return { ...t, [slot]: next }
  })
}

/** Reads a GitHub issue or pull request and keeps it in its slot. */
async function noteGithub($: EngineInterface, ref: GithubRef, rank: number) {
  const jq = '{title,state,url:.html_url,isPr:(.pull_request!=null),merged:(.pull_request.merged_at!=null),draft:(.draft // false)}'
  const got = await $.process.run(['gh', 'api', `repos/${ref.repo}/issues/${ref.number}`, '--jq', jq])
  let data: { title?: string; state?: string; url?: string; isPr?: boolean; merged?: boolean; draft?: boolean } | null = null
  try {
    data = got.exitCode === 0 ? JSON.parse(got.stdout) : null
  } catch {
    data = null
  }
  if (!data && ref.type === null) return
  const isPr = data ? Boolean(data.isPr) : ref.type === 'pull'
  const url = data?.url ?? `https://github.com/${ref.repo}/${isPr ? 'pull' : 'issues'}/${ref.number}`
  if (isPr) {
    const state = data ? prState(data) : null
    await keep($, 'pr', { repo: ref.repo, number: ref.number, title: data?.title ?? null, url, state, rank })
  } else {
    await keep($, 'issue', { platform: 'github', key: `${ref.repo}#${ref.number}`, title: data?.title ?? null, url, appUrl: null, rank })
  }
}

async function noteLinear($: EngineInterface, ref: LinearRef, title: string | null, rank: number) {
  const mentioned = (await read($, tracker)).mentioned.includes(ref.id)
  const base = ref.workspace ? `linear.app/${ref.workspace}/issue/${ref.id}` : null
  await keep($, 'issue', {
    platform: 'linear',
    key: ref.id,
    title: title ?? titleOfSlug(ref.slug),
    url: base && `https://${base}${ref.slug ? `/${ref.slug}` : ''}`,
    appUrl: ref.workspace ? `linear://${ref.workspace}/issue/${ref.id}` : null,
    rank: mentioned ? RANK.prompt : rank,
  })
}

/** Looks for the issues and pull requests a prompt names. */
async function scanPrompt($: EngineInterface, text: string) {
  const ids = text.match(LINEAR_ID) ?? []
  if (ids.length) await update($, tracker, t => ({ ...t, mentioned: [...new Set([...t.mentioned, ...ids])] }))
  for (const ref of findRefs(text, await read($, home))) {
    if (ref.platform === 'github') await noteGithub($, ref, RANK.prompt)
    else await noteLinear($, ref, null, RANK.prompt)
  }
}

/** Looks for an issue or pull request a `gh` command or a Linear tool worked on. */
async function scanCall($: EngineInterface, tool: string, input: Record<string, unknown>, ran: ToolCallResult) {
  if (ran.deny !== undefined || ran.isError) return
  if (tool === 'Bash' && typeof input.command === 'string') {
    const found = refsOfGh(input.command, ran.text ?? '', await read($, home))
    for (const ref of found?.refs ?? []) {
      if (ref.platform === 'github') await noteGithub($, ref, found!.rank)
      else await noteLinear($, ref, null, found!.rank)
    }
  } else if (/linear/i.test(tool) && ran.text) {
    const issue = linearOfResult(ran.text)
    if (issue) await noteLinear($, issue.ref, issue.title, /create/i.test(tool) ? RANK.created : RANK.worked)
  }
}

/** Reads the shown pull request's state again: it moves on GitHub. */
async function refreshPr($: EngineInterface) {
  const pr = (await read($, tracker)).pr
  if (pr) await noteGithub($, { platform: 'github', repo: pr.repo, number: pr.number, type: 'pull' }, pr.rank)
}

/** `$HOME` and the folder `~/Notes` links to, read once. */
async function rootOfNotes($: EngineInterface): Promise<NotesRoot> {
  if (notesRoot) return notesRoot
  const out = await $.process.run(['sh', '-c', 'printf "%s\\n" "$HOME"; cd "$HOME/Notes" 2>/dev/null && pwd -P'])
  const [home = '', real = ''] = out.stdout.split('\n')
  const root = { home, real: real && real !== `${home}/Notes` ? real : null }
  if (home) notesRoot = root
  return root
}

/** Adds the files under `~/Notes` among `paths` to the session's notes, once each. */
async function keepNotes($: EngineInterface, paths: string[]) {
  const root = await rootOfNotes($)
  if (!root.home) return
  const found = paths.map(path => noteOf(path, root)).filter((n): n is Note => n !== null)
  if (found.length) await update($, notes, list => [...list, ...found.filter(n => !list.some(o => o.rel === n.rel))])
}

const WRITTEN_SINCE = 'start=$1; shift; for f; do [ -f "$f" ] && [ "$(date -r "$f" +%s)" -ge "$start" ] && echo "$f"; done'

/** The notes a call wrote: an editing tool's file, or a file under `~/Notes` a command names and that changed since the session began. */
async function scanNotes($: EngineInterface, tool: string, input: Record<string, unknown>, ran: ToolCallResult) {
  if (ran.deny !== undefined || ran.isError) return
  const path = input.file_path ?? input.notebook_path
  if (WRITING_TOOLS.has(tool) && typeof path === 'string') return keepNotes($, [path])
  if (tool !== 'Bash' || typeof input.command !== 'string') return
  const named = notePaths(input.command, await rootOfNotes($))
  if (!named.length) return
  const since = String(Math.floor((await $.session.usage()).startedAt / 1000))
  const written = await $.process.run(['sh', '-c', WRITTEN_SINCE, 'sh', since, ...named])
  await keepNotes($, written.stdout.split('\n').filter(Boolean))
}

const HANDOVER_READ = `d="$HOME/.claude/plugins/data/handover-fundrivendev"
test -d "$d" || d="$HOME/.claude/plugins/data/handover-fundriven"
test -e "$d/live/$1" && echo on
echo "@@"; cat "$d/sessions/$1.json" 2>/dev/null
echo "@@"; cat "$d/options.json" 2>/dev/null`

/** A handover's first lines, for its title, then its line count and last change (`date -r` works on macOS and GNU). */
const HANDOVER_FILE = `head -n 40 "$1" || exit 1
printf '\\n@@\\n'; wc -l < "$1"; date -r "$1" +%s`

/** Reads the handover plugin's state for this session, as its status line does. */
async function readHandover($: EngineInterface) {
  const sid = await $.session.id()
  const out = await $.process.run(['sh', '-c', HANDOVER_READ, 'sh', sid])
  const [live = '', state = '', opts = ''] = out.stdout.split('@@\n')
  const parse = (text: string): Record<string, unknown> => {
    try {
      return JSON.parse(text) as Record<string, unknown>
    } catch {
      return {}
    }
  }
  const st = parse(state)
  const opt = parse(opts)
  const num = (key: string, fallback: number) => (typeof opt[key] === 'number' ? (opt[key] as number) : fallback)
  const titled = async (path: unknown): Promise<HandoverFile | null> => {
    if (typeof path !== 'string' || !path) return null
    const out = await $.process.run(['sh', '-c', HANDOVER_FILE, 'sh', path])
    const cut = out.stdout.lastIndexOf('\n@@\n')
    if (out.exitCode !== 0 || cut < 0) return { path, title: null, lines: null, modifiedAt: null }
    const [lines, seconds] = out.stdout.slice(cut + 4).split('\n').map(n => Number.parseInt(n.trim(), 10))
    const known = (n: number | undefined) => (n !== undefined && Number.isFinite(n) ? n : null)
    const at = known(seconds)
    return { path, title: handoverTitle(out.stdout.slice(0, cut)), lines: known(lines), modifiedAt: at === null ? null : at * 1000 }
  }
  const written = st.written as { ok?: boolean } | undefined
  const said = written?.ok ? (await $.session.messages()).filter(m => m.role === 'assistant').pop()?.text : undefined
  const writer = st.writer as { since?: number } | undefined
  const now = (await $.clock.now()) / 1000
  const next: Handover = {
    isOn: live.trim() === 'on',
    loaded: await titled(st.loaded_from),
    written: written?.ok ? await titled(st.path) : null,
    suggest: num('suggest_tokens', 150_000),
    trigger: num('trigger_tokens', 185_000),
    warn: num('warn_tokens', 20_000),
    isWriting: typeof writer?.since === 'number' && now - writer.since < 660,
    isWindingDown: Boolean(st.wind_down),
    error: typeof st.error === 'string' ? st.error : null,
    resume: said ? resumeMessage(said) : null,
  }
  await update($, handover, () => next)
  if (next.written) await keepNotes($, [next.written.path])
}

/** How long the handover plugin's SessionStart hook may take to load the handover (its timeout, plus a margin). */
const LOAD_WAIT_MS = 190_000

/**
 * Waits for the session that followed `cleared` to have loaded its handover:
 * the handover plugin records `loaded_from` in the new session's state once
 * its SessionStart hook has put the handover in the context.
 */
async function waitForLoad($: EngineInterface, cleared: string): Promise<boolean> {
  const sleep = (ms: number) => new Promise<void>(resolve => $.clock.after(ms, () => resolve()))
  const start = await $.clock.now()
  while ((await $.clock.now()) - start < LOAD_WAIT_MS) {
    if ((await $.session.id()) !== cleared) {
      await readHandover($)
      if ((await read($, handover))?.loaded) return true
    }
    await sleep(1000)
  }
  return false
}

/**
 * Starts the next session from the handover: copies the resume message, runs
 * `/clear` (the handover plugin loads the handover into the new session),
 * waits for the handover to load, then enters the message in the prompt box
 * and, when `isSent`, sends it; left in the box when the handover does not load.
 */
async function startNext($: EngineInterface, resume: string | null, surface: UiCopyArgs['surface'], isSent: boolean) {
  const text = resume?.trim()
  if (text) await $.ui.copy({ text, surface })
  const cleared = await $.session.id()
  await $.command.run({ command: 'clear' })
  if (!text) return
  const isLoaded = await waitForLoad($, cleared)
  await $.prompt.fill({ text })
  if (!isLoaded) $.ui.toast('The handover did not load: the resume message waits in the prompt box.')
  else if (isSent) {
    await $.prompt.submit({ text })
    await $.prompt.fill({ text: '' })
  }
}

/** A session started from a handover takes the handover's title at once, until the agent names it. */
async function titleFromHandover($: EngineInterface) {
  const sid = await $.session.id()
  const title = (await read($, titled)).set === sid ? null : cleanTitle((await read($, handover))?.loaded?.title ?? '')
  if (!title) return
  await update($, titled, t => ({ ...t, set: sid }))
  await update($, topic, () => title)
  const canRename = (await $.command.list()).some(c => c.name === 'rename')
  if (canRename) void $.command.run({ command: 'rename', args: title }).catch(() => undefined)
}

const TITLE_TOOL = 'session_title'
const TITLE_TOOL_ID = `mcp__session-panel__${TITLE_TOOL}`
const TITLE_TOOL_DESCRIPTION = `Sets this session's title: its overall topic in 3 to 7 words, in the language of the person's prompts. It heads the session panel and names the session (/resume, the terminal tab), so the person can tell sessions apart at a glance.
Call it once the first task is clear, then only when what the session is about changes significantly (a new task, not a new step of the same one). Never call it every turn.`

/** Added once to a session's first typed prompt while it has no title of its own: the name the terminal tab shows may be the previous session's. */
const TITLE_REMINDER = `This session has no title of its own yet (the terminal tab may still show the previous session's). Call ${TITLE_TOOL} once the task is clear.`

/** A title as given: its first line, without a label, quotes or a final period; null when empty. */
export const cleanTitle = (text: string): string | null => {
  const line = text.split('\n').map(l => l.trim()).find(Boolean)
  const title = line?.replace(/^title:\s*/i, '').replace(/^["'“«*`]+|["'”»*`.]+$/g, '').trim()
  return title ? oneLine(title, 80) : null
}

async function finish($: EngineInterface, agentId: string, answer?: string) {
  const now = await $.clock.now()
  await update($, agents, list =>
    list.map(a => {
      if (a.id !== agentId || a.endedAt !== null) return a
      const history = answer ? [...a.history, { kind: 'say' as const, text: oneLine(answer, 400) }] : a.history
      return { ...a, endedAt: now, history: history.slice(-HISTORY_CAP) }
    }),
  )
}

export const register: Register = (on, options) => {
  const defaultTtl: Ttl = options.cacheTtl === '5m' ? '5m' : '1h'
  let ticker: { cancel: () => void } | null = null
  let limit: Limit = { limit: WINDOW - RESERVE, window: WINDOW }
  let scheme: Scheme = 'dark'

  on('session.start', async ($, e, next) => {
    await update($, expanded, () => null)
    await update($, view, () => 'overview')
    await $.command.register({ name: 'session-panel', description: 'Open the session overview pane' })
    await $.tool
      .register({
      name: TITLE_TOOL,
      description: TITLE_TOOL_DESCRIPTION,
      inputSchema: {
        type: 'object',
        properties: { title: { type: 'string', description: 'The overall topic, 3 to 7 words, no final period' } },
        required: ['title'],
      },
      isDeferred: false,
    })
      .catch(() => undefined)
    void $.ui.open({ id: PANE, title: TITLE, columns: DOCK_COLUMNS })
    ticker?.cancel()
    let ticks = 0
    ticker = $.clock.every(1000, () => {
      ticks++
      if (ticks % 5 === 0) void readHandover($).then(() => titleFromHandover($))
      if (ticks % 5 === 0) void readScheme($).then(s => (scheme = s))
      if (ticks % 30 === 0) void readLimit($).then(n => (limit = n))
      if (ticks % 60 === 0) void refreshPr($)
      $.ui.invalidate('ui.render')
    })
    const remote = await $.process.run(['git', '-C', e.cwd, 'remote', 'get-url', 'origin'])
    await update($, home, () => (remote.exitCode === 0 ? repoOfRemote(remote.stdout) : null))
    hasLinearApp = (await $.process.run(['test', '-d', '/Applications/Linear.app'])).exitCode === 0
    await readHandover($)
    await titleFromHandover($)
    limit = await readLimit($)
    scheme = await readScheme($)
    await trackRepo($, e.cwd)
    await refreshFiles($)
    await seedModel($)

    if ((await read($, prompts)).length === 0) {
      const typed = (await $.session.messages())
        .filter(m => m.role === 'user' && !m.toolResults?.length)
        .map(m => promptText(m.text))
        .filter((text): text is string => text !== null)
      if (typed.length) await update($, prompts, () => typed)
      for (const text of typed) await scanPrompt($, text)
    }

    return next(e)
  })

  on('command.run', { command: 'session-panel' }, async $ => {
    await update($, expanded, () => null)
    await update($, view, () => 'overview')
    await update($, tab, () => 'main')
    await $.ui.open({ id: PANE, title: TITLE, focus: true, columns: DOCK_COLUMNS })
    void $.ui.scroll({ in: PANE, to: 'start' }).catch(() => undefined)
    return { text: 'Session panel opened.' }
  })

  on('prompt.submit', async ($, e, next) => {
    const text = e.origin.kind === 'composer' ? promptText(e.text) : null
    if (text) {
      await update($, prompts, list => [...list, text])
      await scanPrompt($, text)
      const sid = await $.session.id()
      const t = await read($, titled)
      if (t.set !== sid && t.reminded !== sid) {
        await update($, titled, cur => ({ ...cur, reminded: sid }))
        return next({ ...e, context: [...(e.context ?? []), TITLE_REMINDER] })
      }
    }
    return next(e)
  })

  on('classic.PreModelSwitch', async ($, e, next) => {
    await update($, info, i => ({ ...i, ttl: e.cache_ttl }))
    return next(e)
  })

  on('turn.step', async function* ($, e, next) {
    const agentId = e.agentId
    const stepId = `${e.turnId}:${e.index}`
    if (!agentId) {
      await update($, info, i => ({ ...i, model: e.model, effort: e.effort === undefined ? null : String(e.effort) }))
      await update($, steps, list => [...list, { id: stepId, label: 'Thinking…', isDone: false }].slice(-STEPS_CAP))
    }

    const thinking = new Map<number, string>()
    const text = new Map<number, string>()
    const toolIds: string[] = []
    let live = 'Thinking…'
    const stream = next(e)
    let item = await stream.next()
    while (!item.done) {
      const chunk = item.value
      if (chunk.kind === 'thinking') thinking.set(chunk.index, (thinking.get(chunk.index) ?? '') + chunk.text)
      if (chunk.kind === 'text') text.set(chunk.index, (text.get(chunk.index) ?? '') + chunk.text)
      if (chunk.kind === 'tool') toolIds.push(chunk.id)
      if (!agentId) {
        const label =
          chunk.kind === 'tool'
            ? `${chunk.name}…`
            : lastSentence([...(chunk.kind === 'text' ? text : thinking).values()].join(' ')) ?? live
        if (label !== live) {
          live = label
          await update($, steps, list => list.map(s => (s.id === stepId ? { ...s, label } : s)))
        }
      }
      yield chunk
      item = await stream.next()
    }
    const result = item.value

    const thought = [...thinking.values()].join(' ').trim()
    const said = [...text.values()].join(' ').trim()
    if (agentId) {
      if (thought) await addEntry($, agentId, { kind: 'think', text: thought })
      if (said) await addEntry($, agentId, { kind: 'say', text: said })
    } else {
      const now = await $.clock.now()
      const calls = result.toolUses.map(use =>
        intentOf(use.name, typeof use.input === 'object' && use.input !== null ? (use.input as Record<string, unknown>) : {}),
      )
      const label =
        (calls.length && calls.map(c => c.what).join(' · ')) || (thought && headline(thought)) || (said && headline(said)) || 'Answered'
      const how = calls.map(c => c.how).filter(Boolean).join(' · ') || undefined
      const why = calls.length && thought ? headline(thought) : undefined
      await update($, info, i => ({ ...i, lastRequestAt: now }))
      await update($, steps, list => {
        const index = list.findIndex(s => s.id === stepId)
        const earlier = list.slice(Math.max(0, index - 3), index)
        const same = calls.length ? earlier.reverse().find(s => s.label === label && s.how === how) : undefined
        const repeats = same ? (same.repeats ?? 1) + 1 : undefined
        return list.map(s =>
          s.id === stepId
            ? { ...s, label, how, why, toolIds, doneIds: toolIds.filter(id => returned.has(id)), isDone: true, ...(repeats ? { flag: 'repeat' as const, repeats } : {}) }
            : s,
        )
      })
    }

    return result
  })

  on('agent.spawn', async ($, e, next) => {
    const now = await $.clock.now()
    const draft: Agent = {
      id: null,
      toolUseId: e.tool_use_id,
      description: e.description,
      type: e.subagentType,
      prompt: e.prompt,
      model: null,
      isBackground: e.background,
      isTeammate: Boolean(e.isTeammate),
      startedAt: now,
      endedAt: null,
      history: [],
    }
    await update($, agents, list => [...list, draft])
    const spawned = await next(e)
    await update($, agents, list =>
      list.flatMap(a => {
        if (a.toolUseId !== draft.toolUseId) return [a]
        if (spawned.deny !== undefined || !spawned.agentId) return []
        return [{ ...a, id: spawned.agentId, model: spawned.model }]
      }),
    )
    return spawned
  })

  let refresh: { cancel: () => void } | null = null
  /** The title the agent set, given to `/rename` once its turn ends: a command run from a tool call would wait on that turn. */
  let renaming: string | null = null
  /** Hand over now was pressed: hidden until the handover is under way. */
  let triggered = false
  /** Start next session was pressed: one launch per handover. */
  let launched: string | null = null

  on('tool.call', async ($, e, next) => {
    const agentId = e.agentId
    const ran = await next(e)
    const tool = String(e.tool)
    const input = e as unknown as Record<string, unknown>
    if (EDITING_TOOLS.has(tool)) {
      const path = input.file_path
      if (typeof path === 'string' && path.includes('/')) await trackRepo($, path.slice(0, path.lastIndexOf('/')) || '/')
      refresh?.cancel()
      refresh = $.clock.after(400, () => void refreshFiles($))
    }
    if (agentId) await logCall($, agentId, e, ran)
    else {
      returned.add(e.tool_use_id)
      await flagStep($, e.tool_use_id, ran)
      await markReturned($, e.tool_use_id)
    }
    await scanCall($, tool, input, ran)
    await scanNotes($, tool, input, ran)
    return ran
  })

  on('tool.call', { tool: TITLE_TOOL_ID }, async ($, e) => {
    const title = cleanTitle(String((e as unknown as Record<string, unknown>).title ?? ''))
    if (!title) return { deny: 'An empty title: give the overall topic in 3 to 7 words.' }
    await update($, topic, () => title)
    const sid = await $.session.id()
    await update($, titled, t => ({ ...t, set: sid }))
    renaming = title
    const said = `Session title set: ${title}`
    return { result: said as never, text: said }
  })

  on('turn.complete', async ($, e, next) => {
    const title = e.agentId ? null : renaming
    if (title) {
      renaming = null
      const canRename = (await $.command.list()).some(c => c.name === 'rename')
      if (canRename) void $.command.run({ command: 'rename', args: title }).catch(() => undefined)
    }
    if (e.agentId && !(await read($, agents)).find(a => a.id === e.agentId)?.isTeammate) {
      await finish($, e.agentId, e.answer)
    }
    return next(e)
  })

  on('classic.SubagentStop', async ($, e, next) => {
    await finish($, e.agent_id)
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button, Link } = $.ui.resolve(e)
    const [now, i, all, done, open, isStepsOpen, picker, repos, typed, shown, t, ho] = await Promise.all([
      $.clock.now(),
      read($, info),
      read($, agents),
      read($, steps),
      read($, expanded),
      read($, stepsOpen),
      read($, picking),
      read($, changes),
      read($, prompts),
      read($, view),
      read($, tracker),
      read($, handover),
    ])
    const tree = await read($, worktree)
    const written = await read($, notes)
    const usage = await $.session.usage()
    const shownTab = await read($, tab)
    const isQuotasOpen = await read($, quotasOpen)
    const title = await read($, topic)
    const quotas = usage.rateLimits
      .map(l => quotaOf(l.kind, l.percentUsed, l.resetsAt, now))
      .filter((q): q is Quota => q !== null)

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

    const running = all.filter(a => a.endedAt === null)
    const finished = all.filter(a => a.endedAt !== null)
    /** What a sub-agent is doing now: its last call, else its last thought or words. */
    const currentTask = (a: Agent) => {
      const last = [...a.history].reverse().find(entry => entry.kind !== 'result')
      return last ? last.text : 'starting…'
    }
    const kindOf = (a: Agent) => (a.isTeammate ? 'teammate' : a.isBackground ? 'background' : 'sub-agent')

    const section = (title: string) => (
      <Text bold color="claude">
        {title}
      </Text>
    )

    const columns = Math.max(12, e.props.bodyColumns - 2)
    /** Ahead of pace, the overshoot breathes with the clock, once a second. */
    const isBright = Math.floor(now / 1000) % 2 === 0
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
            <Text key={k} color={run.color} bold={run.isPace} dimColor={run.isAhead && q.verdict?.tone !== 'ok' && !isBright}>
              {run.text}
            </Text>
          ))}
        </Text>
      </Box>
    )

    /** Opens or closes a sub-agent, its heading brought to the top of the pane. */
    const toggleAgent = async (key: string) => {
      await update($, expanded, cur => (cur === key ? null : key))
      await $.ui.scroll({ to: { key: `agent:${key}` }, block: 'start' }).catch(() => undefined)
    }

    const card = (a: Agent, isDone: boolean) => {
      const key = a.id ?? a.toolUseId
      const isOpen = open === key
      const history = a.history.slice(isOpen ? -OPEN_HISTORY : -3)
      const earlier = a.history.length - history.length
      const prompt = a.prompt.length > OPEN_PROMPT ? `${a.prompt.slice(0, OPEN_PROMPT - 1)}…` : a.prompt
      const elapsed = duration((a.endedAt ?? now) - a.startedAt)
      return (
        <Box key={key} flexDirection="column" marginBottom={1}>
          <Button
            key={`agent:${key}`}
            label={`${isOpen ? '▾' : '▸'} ${a.description}`}
            plain
            dimColor={isDone}
            onPress={() => toggleAgent(key)}
          />
          <Text dimColor wrap="truncate-end">
            {a.type}
            {a.model ? ` · ${prettyModel(a.model)}` : ''} · {elapsed}
            {a.isBackground ? ' · bg' : ''}
          </Text>
          <Text dimColor={isDone} italic wrap={isOpen ? 'wrap' : 'truncate-end'}>
            {isOpen ? prompt : oneLine(a.prompt, 200)}
          </Text>
          {earlier > 0 && <Text dimColor>… {earlier} earlier</Text>}
          {history.map((entry, index) => (
            <Text
              key={`agent:${key}:${earlier + index}`}
              dimColor={isDone || entry.kind === 'result' || entry.kind === 'think'}
              color={entry.kind === 'error' ? 'error' : undefined}
              wrap={isOpen ? 'wrap' : 'truncate-end'}
            >
              {entry.kind === 'tool' ? '› ' : entry.kind === 'think' ? '∴ ' : entry.kind === 'result' ? '  ⎿ ' : entry.kind === 'error' ? '✗ ' : '“ '}
              {entry.text}
            </Text>
          ))}
          {isOpen && (
            <Button key={`agent:${key}:close`} label="▴ Collapse" plain dimColor onPress={() => toggleAgent(key)} />
          )}
        </Box>
      )
    }

    const pill = (key: string, label: string, color: string, isOn: boolean, onPress: () => unknown) => (
      <Box key={`${key}:pill`} borderStyle="round" borderColor={color} paddingX={1}>
        <Text color={color}>{isOn ? '● ' : '○ '}</Text>
        <Button key={key} label={label} plain onPress={onPress} />
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

    const options =
      picker === 'model'
        ? MODELS.map(m =>
            pill(`model:${m.id}`, prettyModel(m.id), m.color, i.model !== null && modelColor(i.model) === m.color, () =>
              pickModel(m.id),
            ),
          )
        : picker === 'effort'
          ? EFFORTS.map(level =>
              pill(`effort:${level.level}`, effortLabel(level.level), level.color, i.effort === level.level, () =>
                pickEffort(level.level),
              ),
            )
          : null

    const last = done[done.length - 1]
    const current = last && isRunning(last) ? last : null
    const completed = current ? done.slice(0, -1) : done
    const shownSteps = isStepsOpen ? done : [...completed.slice(-DONE_SHOWN), ...(current ? [current] : [])]
    const folded = done.length - shownSteps.length
    const hidden = done.slice(0, folded)
    const foldedIssues = (['refused', 'failed', 'repeat'] as const)
      .map(flag => [flag, hidden.filter(s => s.flag === flag).length] as const)
      .filter(([, n]) => n > 0)
      .map(([flag, n]) => ` · ${n} ${flag === 'repeat' ? 'repeated' : flag}`)
      .join('')

    const issueHref = t.issue && (e.surface === 'terminal' && hasLinearApp && t.issue.appUrl ? t.issue.appUrl : t.issue.url)
    const prColor = t.pr?.state ? PR_COLOR[t.pr.state] : '#a5adce'
    const corner = (
      <Box flexDirection="column" alignItems="flex-end" flexShrink={1}>
        {!t.issue && <Text dimColor>no issue</Text>}
        {!t.pr && <Text dimColor>no pull request</Text>}
        {t.issue && (
          <Text wrap="truncate-end">
            <Text color={ISSUE_ICON[t.issue.platform].color}>{ISSUE_ICON[t.issue.platform].glyph} </Text>
            {issueHref ? (
              <Link href={issueHref} label={t.issue.title ?? t.issue.key} />
            ) : (
              t.issue.title ?? t.issue.key
            )}
          </Text>
        )}
        {t.pr && (
          <Text wrap="truncate-end">
            <Link href={t.pr.url}>
              <Text color={prColor}>
                ⎇ {t.pr.repo.split('/').pop()} #{t.pr.number}
              </Text>
            </Link>
            {t.pr.state && <Text color={prColor}> {t.pr.state}</Text>}
          </Text>
        )}
        {tree ? (
          <Text wrap="truncate-end" color="#81c8be">
            ▣ {tree}
          </Text>
        ) : (
          <Text dimColor>main checkout</Text>
        )}
      </Box>
    )

    /** A handover file by its title, linked, then greyed its length and last change; `none` without one. */
    const handoverFile = (label: string, f: HandoverFile | null) => {
      const meta = f && fileMeta(f.lines, f.modifiedAt)
      return (
        <Text wrap="truncate-end">
          <Text dimColor>{label} </Text>
          {f ? <Link href={`file://${f.path}`} label={f.title ?? f.path.split('/').pop() ?? f.path} /> : <Text dimColor>none</Text>}
          {meta && <Text dimColor> ({meta})</Text>}
        </Text>
      )
    }

    const handoverRows = (() => {
      if (!ho) return [<Text dimColor>Not read yet.</Text>]
      if (!ho.isOn) return [<Text dimColor>The handover plugin is off in this session.</Text>]
      const status = handoverStatus(ho, usage.context.tokens ?? 0)
      const phase = handoverPhase(ho, usage.context.tokens ?? 0)
      const isStopped = ho.written !== null && current === null
      if (ho.written || ho.isWriting) triggered = false
      const isTriggerable = !ho.written && !ho.isWriting && !triggered && !(ho.trigger && (usage.context.tokens ?? 0) >= ho.trigger)
      const launch = async (isSent: boolean, surface: UiCopyArgs['surface']) => {
        if (!ho.written || launched === ho.written.path) return
        launched = ho.written.path
        $.ui.invalidate('ui.render')
        await startNext($, ho.resume, surface, isSent)
      }
      const pillShape = (a: { key: string; emoji: string; color: string }, label: RenderElement) => (
        <Box key={`${a.key}:box`} borderStyle="round" borderColor={a.color} paddingX={1} flexShrink={0}>
          <Text>{a.emoji} </Text>
          {label}
        </Box>
      )
      return [
        phase ? <Text color={PHASES[phase].color}>{phaseLine(phase, now)}</Text> : <Text color={status.color}>✋ {status.text}</Text>,
        ...(ho.written ? [handoverFile('written', ho.written)] : []),
        ...(isStopped
          ? [
              <Box key="handover:next" flexDirection="column" marginTop={1}>
                <Box flexDirection="row" flexWrap="wrap" columnGap={1}>
                  {(ho.resume ? NEXT_ACTIONS : NEXT_ACTIONS.filter(a => !a.isSent)).map(a =>
                    pillShape(
                      a,
                      <Button
                        key={a.key}
                        label={launched === ho.written!.path ? 'Starting…' : a.label}
                        plain
                        autoFocus={a.isSent ? true : undefined}
                        hover={{ color: a.color }}
                        onPress={press => launch(a.isSent, press.surface)}
                      />,
                    ),
                  )}
                </Box>
                {ho.resume && (
                  <Text dimColor italic wrap="wrap">
                    {ho.resume}
                  </Text>
                )}
              </Box>,
            ]
          : []),
        ...(isTriggerable
          ? [
              <Box key="handover:now" flexDirection="row" marginTop={1}>
                {pillShape(
                  TRIGGER_NOW,
                  <Button
                    key={TRIGGER_NOW.key}
                    label={TRIGGER_NOW.label}
                    plain
                    hover={{ color: TRIGGER_NOW.color }}
                    onPress={async () => {
                      triggered = true
                      $.ui.invalidate('ui.render')
                      await $.command.run({ command: 'handover:trigger' })
                    }}
                  />,
                )}
              </Box>,
            ]
          : []),
        <Box key="handover:phases" flexDirection="column" marginTop={1}>
          <Text dimColor>Handover states</Text>
          {(Object.keys(PHASES) as HandoverPhase[]).map(key => (
            <Box key={`phases:${key}`} flexDirection="row" columnGap={1}>
              <Box flexShrink={0} width={30}>
                <Text color={PHASES[key].color}>{phaseLine(key, now)}</Text>
              </Box>
              <Text dimColor wrap="wrap">
                {PHASES[key].does}
              </Text>
            </Box>
          ))}
        </Box>,
      ]
    })()

    const tabPill = (key: Tab, label: string) => (
      <Box key={`tab:${key}:box`} borderStyle="round" borderColor={shownTab === key ? '#8caaee' : '#51576d'} paddingX={1}>
        <Button
          key={`tab:${key}`}
          label={label}
          plain
          dimColor={shownTab !== key}
          onPress={async () => {
            await update($, view, () => 'overview')
            await update($, tab, () => key)
          }}
        />
      </Box>
    )

    const toggleQuotas = () => update($, quotasOpen, cur => !cur)
    /** Each window's use in one pill, in its verdict's colour; a press anywhere but the coloured dots unfolds the bars beneath the top lines. */
    const quotaPill = quotas.length > 0 && (
      <Box key="quotas:box" borderStyle="round" borderColor="#51576d" paddingX={1} flexShrink={0}>
        {quotas.map((q, k) => (
          <Box key={`quotas:${q.label}:row`} flexDirection="row">
            {k > 0 && <Button key={`quotas:${q.label}:divider`} label=" │ " plain dimColor onPress={toggleQuotas} />}
            <Text color={TONE[q.verdict?.tone ?? 'ok']}>● </Text>
            <Button key={`quotas:${q.label}`} label={`${q.label} ${q.used}%`} plain hover={{ color: TONE[q.verdict?.tone ?? 'ok'] }} onPress={toggleQuotas} />
          </Box>
        ))}
        <Button key="quotas:fold" label={isQuotasOpen ? ' 🔼 ' : ' 🔽 '} plain onPress={toggleQuotas} />
      </Box>
    )

    /** The session's title on a line of its own; beneath, the model and effort, the tabs, and a close mark wide enough to click. */
    const header = (
      <Box flexDirection="column" marginBottom={1}>
        <Text bold color="claude" wrap="wrap">
          {title ?? TITLE}
        </Text>
      <Box flexDirection="row" alignItems="center" columnGap={1}>
        {pill('pick:model', i.model ? prettyModel(i.model) : 'model…', modelColor(i.model), picker === 'model', () => toggle('model'))}
        {pill('pick:effort', effortLabel(i.effort), effortColor(i.effort), picker === 'effort', () => toggle('effort'))}
        {tabPill('main', 'Main')}
        {tabPill('misc', 'MISC')}
        {tabPill('help', 'Help')}
        <Box flexGrow={1} />
        {quotaPill}
        <Box key="close:box" borderStyle="round" borderColor="#51576d" paddingX={1} flexShrink={0}>
          <Button
            key="close"
            label=" ✕ "
            plain
            hover={{ color: '#e78284' }}
            onPress={() => $.ui.close({ id: PANE }).catch(() => undefined)}
          />
        </Box>
      </Box>
        {options && (
          <Box flexDirection="row" flexWrap="wrap" columnGap={1}>
            {options}
          </Box>
        )}
        {isQuotasOpen && quotas.length > 0 && (
          <Box flexDirection="row" columnGap={3} marginTop={1}>
            {quotas.map(q => quotaBar(q, Math.floor((columns - 3 * (quotas.length - 1)) / quotas.length)))}
          </Box>
        )}
      </Box>
    )

    if (shown === 'prompts') {
      return (
        <Box flexDirection="column" paddingX={1}>
          {header}
          <Button key="prompts:back" label="← Overview" plain onPress={() => update($, view, () => 'overview')} />
          {section(`Prompts · ${typed.length}`)}
          {typed.map((text, index) => (
            <Box key={`prompt:${index}`} flexDirection="column" marginBottom={1}>
              <Text dimColor>#{index + 1}</Text>
              <Text wrap="wrap">{text}</Text>
            </Box>
          ))}
        </Box>
      )
    }

    const agentLine = (a: Agent, isDone: boolean) => {
      const key = a.id ?? a.toolUseId
      if (open === key) return card(a, isDone)
      return (
        <Box key={key} flexDirection="column">
          <Button
            key={`agent:${key}`}
            label={`▸ ${a.description}`}
            plain
            dimColor={isDone}
            onPress={() => toggleAgent(key)}
          />
          <Text dimColor wrap="truncate-end">
            {'  '}
            {kindOf(a)} · {duration((a.endedAt ?? now) - a.startedAt)} · {isDone ? 'done' : currentTask(a)}
          </Text>
        </Box>
      )
    }

    const mainBody = (
      <Box key="tab:main:body" flexDirection="column">
        <Box flexDirection="row" justifyContent="space-between" columnGap={2} marginBottom={1}>
          <Box flexDirection="column" flexShrink={0}>
            <Text>
              ⌛ <Text dimColor>running </Text>
              {duration(now - usage.startedAt)}
              {'   '}⏳ <Text dimColor>cache </Text>
              <Text color={cache.color}>{cache.text}</Text>
            </Text>
            <Text>
              <Text dimColor>context </Text>
              <Text bold color={context.color} inverse={context.isCompacting}>
                {context.text}
              </Text>
            </Text>
          </Box>
          {corner}
        </Box>


        <Box flexDirection="row">
          {section('Last prompt ')}
          <Button
            key="prompts"
            label={`(${typed.length})`}
            plain
            dimColor
            onPress={() => update($, view, () => 'prompts')}
          />
        </Box>
        <Box marginBottom={1}>
          <Text wrap="wrap">{typed.length ? oneLine(typed[typed.length - 1]!, 360) : '—'}</Text>
        </Box>

        <Box flexDirection="row" columnGap={2}>
          {section('Handover')}
          {ho?.isOn && handoverFile('loaded', ho.loaded)}
        </Box>
        <Box flexDirection="column" marginBottom={1}>
          {handoverRows}
        </Box>

        {section('Notes')}
        <Box flexDirection="column" marginBottom={1}>
          {written.length === 0 && <Text dimColor>None written yet.</Text>}
          {noteGroups(written).map(group => (
            <Box key={`notes:${group.kind}`} flexDirection="column">
              <Text dimColor>{group.kind}</Text>
              {group.notes.map(n =>
                e.surface === 'terminal' ? (
                  <Text wrap="truncate-end">
                    {'  '}
                    <Link href={`file://${n.path}`} label={n.name} />
                  </Text>
                ) : (
                  <Box key={`note:${n.rel}:row`} paddingLeft={2}>
                    <Button key={`note:${n.rel}`} label={n.name} plain onPress={() => $.process.run(['open', n.path])} />
                  </Box>
                ),
              )}
            </Box>
          ))}
        </Box>
      </Box>
    )

    const miscBody = (
      <Box key="tab:misc:body" flexDirection="column">
        <Box flexDirection="row">
          {section('Steps ')}
          {folded > 0 || isStepsOpen ? (
            <Button
              key="steps"
              label={isStepsOpen ? '▾ fold earlier steps' : `▸ ${folded} earlier${foldedIssues}`}
              plain
              dimColor
              onPress={() => update($, stepsOpen, cur => !cur)}
            />
          ) : (
            done.length === 0 && <Text dimColor>none yet</Text>
          )}
        </Box>
        <Box flexDirection="column" marginBottom={1}>
          {shownSteps.map(s => {
            const isCurrent = s === current
            const mark =
              s.flag === 'refused' || s.flag === 'failed'
                ? { glyph: '✗ ', color: '#e78284' }
                : s.flag === 'repeat'
                  ? { glyph: '↻ ', color: '#e5c890' }
                  : isCurrent
                    ? { glyph: '● ', color: '#e5c890' }
                    : { glyph: '✓ ', color: '#a6d189' }
            const isIssue = s.flag !== undefined
            return (
              <Box key={s.id} flexDirection="column">
                <Text wrap="wrap" dimColor={!isCurrent && !isIssue}>
                  <Text color={mark.color}>{mark.glyph}</Text>
                  {s.label}
                  {s.flag === 'repeat' && <Text color="#e5c890"> ×{s.repeats}</Text>}
                </Text>
                {(isStepsOpen || isCurrent) && s.why && (
                  <Text dimColor italic wrap="wrap">
                    {'  ∴ '}
                    {s.why}
                  </Text>
                )}
                {s.note && (
                  <Text wrap="wrap" color="#e78284">
                    {'  '}
                    {s.flag}: {s.note}
                  </Text>
                )}
              </Box>
            )
          })}
        </Box>

        {section(`Sub-agents · ${running.length} running · ${finished.length} done`)}
        <Box flexDirection="column">
          {all.length === 0 && <Text dimColor>None yet.</Text>}
          {running.map(a => agentLine(a, false))}
          {[...finished].reverse().map(a => agentLine(a, true))}
        </Box>
        <Box flexDirection="column" marginTop={1}>
          {section('Git diff')}
          {repos.length === 0 && <Text dimColor>No change.</Text>}
          {repos.map(repo => (
            <Box key={repo.root} flexDirection="column" marginBottom={1}>
              <Text dimColor>
                {repo.root.split('/').pop()} <Text color="#8caaee">⎇ {repo.branch}</Text>{' '}
                <Text color="#a6d189">+{repo.files.reduce((n, f) => n + f.added, 0)}</Text>{' '}
                <Text color="#e78284">−{repo.files.reduce((n, f) => n + f.removed, 0)}</Text>
              </Text>
              {repo.files.length === 0 && <Text dimColor>No change.</Text>}
              {treeRows(repo.files).map(row => (
                <Text wrap="truncate-end">
                  <Text dimColor>{row.indent}</Text>
                  {row.change ? (
                    <Text>
                      <Text color={SIGN_COLOR[row.change.status]}>{SIGN[row.change.status]} </Text>
                      <Text dimColor={row.change.status === 'deleted'} strikethrough={row.change.status === 'deleted'}>
                        {row.name}
                      </Text>{' '}
                      {row.change.added > 0 && <Text color="#a6d189">+{row.change.added} </Text>}
                      {row.change.removed > 0 && <Text color="#e78284">−{row.change.removed}</Text>}
                    </Text>
                  ) : (
                    <Text dimColor>{row.name}</Text>
                  )}
                </Text>
              ))}
              {repo.commits.length > 0 && (
                <Box marginTop={1}>{section('Git History')}</Box>
              )}
              {repo.commits.map(c => {
                const key = `commit:${repo.root}:${c.hash}`
                const isOpen = open === key
                return (
                  <Box key={key} flexDirection="column">
                    <Box flexDirection="row">
                      <Text color={c.isPushed ? '#a6d189' : '#e5c890'}>{c.isPushed ? '● ' : '○ '}</Text>
                      <Button
                        key={key}
                        label={c.subject}
                        plain
                        dimColor={c.isPushed && !isOpen}
                        onPress={() => update($, expanded, cur => (cur === key ? null : key))}
                      />
                    </Box>
                    <Text dimColor wrap="truncate-end">
                      {'  '}
                      {c.hash.slice(0, 7)} · {ago(now - c.at)} · {c.isPushed ? 'pushed' : 'local'}
                    </Text>
                    {isOpen && c.body && (
                      <Box paddingLeft={2}>
                        <Text wrap="wrap">{c.body}</Text>
                      </Box>
                    )}
                  </Box>
                )
              })}
            </Box>
          ))}
        </Box>
      </Box>
    )


    /** An item as the pane draws it, in a fixed column, then greyed what it shows or does. */
    const helpRow = (key: string, example: RenderElement, does: string) => (
      <Box key={`help:${key}`} flexDirection="row" columnGap={1} alignItems="center">
        <Box flexShrink={0} width={HELP_EXAMPLE}>
          {example}
        </Box>
        <Text dimColor wrap="wrap">
          {does}
        </Text>
      </Box>
    )
    /** A pill as drawn in the pane, without its press. */
    const framed = (border: string, content: RenderElement) => (
      <Box borderStyle="round" borderColor={border} paddingX={1} flexShrink={0}>
        {content}
      </Box>
    )
    const sample: Quota = { label: '5h', used: 62, elapsed: 0.5, verdict: { text: '→124%', tone: 'out' }, resetsIn: 9_000_000 }
    const helpBody = (
      <Box key="tab:help:body" flexDirection="column">
        {section('Top lines')}
        <Box flexDirection="column" marginBottom={1}>
          {helpRow('title', <Text bold color="claude">Session panel tabs</Text>, `The session's topic, set by the agent once the task is clear, or taken from the handover it started from. It also names the session in /resume and the terminal tab; "${TITLE}" until then.`)}
          {helpRow('main', framed('#51576d', <Text>Main</Text>), 'The session at a glance: time, cache, context, issue and PR, last prompt, handover, notes.')}
          {helpRow('misc', framed('#51576d', <Text>MISC</Text>), "The agent's steps, its sub-agents, and the git diff with this session's commits.")}
          {helpRow(
            'quotas',
            framed(
              '#51576d',
              <Text>
                <Text color={TONE.ok}>● </Text>5h 42%<Text dimColor> │ </Text>
                <Text color={TONE.tight}>● </Text>7d 81% 🔽
              </Text>,
            ),
            'Use of each rate-limit window, its dot coloured by pace: green on track, yellow tight (90-100% at reset), red runs out before the reset. Press to unfold the bars.',
          )}
          {helpRow(
            'bar',
            <Box flexDirection="column">
              <Text>
                <Text dimColor>5h </Text>
                <Text bold color={TONE.out}>62%</Text>
                <Text color={TONE.out}> →124%</Text>
                <Text dimColor> 🔄 2h30m</Text>
              </Text>
              <Text>
                {barRuns(sample, HELP_EXAMPLE - 2).map((run, k) => (
                  <Text key={k} color={run.color} bold={run.isPace}>
                    {run.text}
                  </Text>
                ))}
              </Text>
            </Box>,
            '→ the use projected at the reset, or "out in" how long it lasts at this pace; 🔄 the time to the reset. ┃ marks where even spending would be by now: fill past it is spent ahead of pace, and blinks once tight.',
          )}
          {helpRow('close', framed('#51576d', <Text> ✕ </Text>), 'Closes the pane; /session-panel reopens it on Main.')}
        </Box>

        {section('Main')}
        <Box flexDirection="column" marginBottom={1}>
          {helpRow(
            'cache',
            <Text>
              ⏳ <Text dimColor>cache </Text>
              <Text color={cacheColor(240_000, 300_000)}>4m</Text>
            </Text>,
            'Time left before the prompt cache expires: green over half its TTL, then yellow, then orange; red "expired" means the next request rereads the whole context at full price.',
          )}
          {helpRow(
            'context',
            <Text>
              <Text dimColor>context </Text>
              <Text bold color="#ffff00">
                96.2k/167k 57%
              </Text>
            </Text>,
            'Tokens against the auto-compact trigger (window minus reserve, in brackets): green to half, yellow to 75%, orange to 90%, then red; "⚠ compacting" once reached.',
          )}
          {helpRow(
            'issue',
            <Text wrap="truncate-end">
              <Text color={ISSUE_ICON.linear.color}>{ISSUE_ICON.linear.glyph} </Text>Fix the login loop
            </Text>,
            'The issue the session works on, linked: ◐ Linear, ◉ GitHub.',
          )}
          {helpRow(
            'pr',
            <Text>
              <Text color={PR_COLOR.draft}>⎇ claude-plugins #21</Text>
              <Text color={PR_COLOR.draft}> draft</Text>
            </Text>,
            'Its pull request, linked, in the colour of its state: draft, open, merged or closed.',
          )}
          {helpRow('worktree', <Text color="#81c8be">▣ session-panel-tabs</Text>, 'The worktree the session works in; "main checkout" otherwise.')}
          {helpRow(
            'prompts',
            <Text>
              <Text bold color="claude">
                Last prompt{' '}
              </Text>
              <Text dimColor>(12)</Text>
            </Text>,
            'Your last typed prompt; press the count to read them all.',
          )}
          {helpRow(
            'loaded',
            <Text>
              <Text bold color="claude">
                Handover
              </Text>
              <Text dimColor>  loaded </Text>
              <Text underline>Ship the panel</Text>
            </Text>,
            'The handover this session started from, linked; "none" for a fresh start.',
          )}
          {helpRow(
            'status',
            <Text color="#e5c890">✋ triggers at 150k · now 141k</Text>,
            'Where the handover plugin winds the session down; yellow once close, "suggested" once a handover is worth doing at the next boundary.',
          )}
          {helpRow(
            'trigger',
            framed(TRIGGER_NOW.color, <Text>{TRIGGER_NOW.emoji} {TRIGGER_NOW.label}</Text>),
            'Starts the wind-down at once (/handover:trigger) instead of waiting for the trigger.',
          )}
          {(Object.keys(PHASES) as HandoverPhase[]).map(key =>
            helpRow(`phase:${key}`, <Text color={PHASES[key].color}>{phaseLine(key, now)}</Text>, PHASES[key].does),
          )}
          {helpRow(
            'written',
            <Text>
              <Text dimColor>written </Text>
              <Text underline>Next steps</Text>
              <Text dimColor> (84 lines · 1m ago)</Text>
            </Text>,
            'The handover just written, linked.',
          )}
          {NEXT_ACTIONS.map(a =>
            helpRow(
              a.key,
              framed(a.color, <Text>{a.emoji} {a.label}</Text>),
              a.isSent
                ? 'Runs /clear, waits for the handover to load, then sends its resume prompt: the next session starts on its own.'
                : 'The same, but leaves the prompt in the input for you to change before sending; alone when the reply gave no prompt.',
            ),
          )}
          {helpRow(
            'notes',
            <Box flexDirection="column">
              <Text dimColor>plans</Text>
              <Text>  <Text underline>26-10-08-help-tab.md</Text></Text>
            </Box>,
            'Documents this session wrote under ~/Notes/claude, by kind; press one to open it.',
          )}
        </Box>

        {section('MISC')}
        <Box flexDirection="column">
          {helpRow(
            'steps',
            <Box flexDirection="column">
              <Text dimColor>
                <Text color="#a6d189">✓ </Text>Read the panel
              </Text>
              <Text>
                <Text color="#e5c890">● </Text>Write the help
              </Text>
              <Text dimColor italic>
                {'  ∴ '}why it does it
              </Text>
            </Box>,
            "The agent's steps, one per intent: ✓ done, ● under way with its reason. The four latest show; press \"▸ n earlier\" for the rest.",
          )}
          {helpRow(
            'flags',
            <Box flexDirection="column">
              <Text>
                <Text color="#e78284">✗ </Text>Push the branch
              </Text>
              <Text>
                <Text color="#e5c890">↻ </Text>Run the tests<Text color="#e5c890"> ×3</Text>
              </Text>
            </Box>,
            '✗ a call refused or failed, with why beneath; ↻ the same call repeated, a sign the agent may be looping.',
          )}
          {helpRow(
            'agent',
            <Box flexDirection="column">
              <Text>▸ Find the hooks</Text>
              <Text dimColor>  sub-agent · 2m · › Read register.tsx</Text>
            </Box>,
            'A sub-agent: its kind, time, and what it does now; greyed once done. Press to open its prompt and latest calls.',
          )}
          {helpRow(
            'diff',
            <Box flexDirection="column">
              <Text dimColor>
                claude-plugins <Text color="#8caaee">⎇ main</Text> <Text color="#a6d189">+12</Text> <Text color="#e78284">−3</Text>
              </Text>
              <Text>
                <Text color={SIGN_COLOR.modified}>{SIGN.modified} </Text>register.tsx <Text color="#a6d189">+12</Text>
              </Text>
            </Box>,
            'Uncommitted changes in each repo the session touched, as a tree: + added, ~ modified, − deleted.',
          )}
          {helpRow(
            'commits',
            <Box flexDirection="column">
              <Text>
                <Text color="#a6d189">● </Text>
                <Text dimColor>Add the help tab</Text>
              </Text>
              <Text>
                <Text color="#e5c890">○ </Text>Fix the quota pill
              </Text>
            </Box>,
            "This session's commits: ● pushed, ○ local only. Press one to read its message.",
          )}
        </Box>
      </Box>
    )

    const pane = (
      <Box flexDirection="column" paddingX={1}>
        {header}
        {shownTab === 'help' ? helpBody : shownTab === 'misc' ? miscBody : mainBody}
      </Box>
    )
    return recolor(pane, scheme)
  })
}
