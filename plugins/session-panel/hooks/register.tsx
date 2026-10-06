import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, ToolCallInput, ToolCallResult } from 'claude-code'

import type { Agent, Entry, FileChange, Handover, Info, Note, NotesRoot, Picker, Quota, QuotaLayout, RepoChanges, Step, TrackedIssue, TrackedPr, Ttl } from '../types'

import { LOG_FORMAT, parseLog, parseNumstat, parseStatus, treeRows } from './files'
import { noteGroups, noteOf, notePaths } from './notes'
import { PR_COLOR, RANK, findRefs, linearOfResult, prState, refsOfGh, repoOfRemote, titleOfSlug } from './tracker'
import type { GithubRef, LinearRef } from './tracker'

const PANE = 'session-panel'
const TITLE = 'Session'
const HISTORY_CAP = 400
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
const quotaLayout = atom({ plugin: 'session-panel', key: 'quotaLayout' } as const, 'side' as QuotaLayout)
const picking = atom({ plugin: 'session-panel', key: 'picking' } as const, null as Picker)
const tracker = atom({ plugin: 'session-panel', key: 'tracker' } as const, { issue: null, pr: null, mentioned: [] } as {
  issue: TrackedIssue | null
  pr: TrackedPr | null
  mentioned: string[]
})
const handover = atom({ plugin: 'session-panel', key: 'handover' } as const, null as Handover | null)
const notes = atom({ plugin: 'session-panel', key: 'notes' } as const, [] as Note[])
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

/** `78234` → `78.2k`, `934` → `934`, as the status line counts tokens. */
export const kfmt = (n: number): string => (n < 1000 ? String(n) : `${Math.floor(n / 1000)}.${Math.floor((n % 1000) / 100)}k`)

/**
 * The context counter as the status line draws it: tokens against the
 * auto-compact trigger, green to half of it, yellow to three quarters, orange
 * to nine tenths, then red, and compacting once reached.
 */
export const contextOf = (tokens: number | undefined, limit: number): { text: string; color: string; isCompacting: boolean } => {
  const cap = limit % 1000 === 0 ? `${limit / 1000}k` : kfmt(limit)
  if (tokens === undefined) return { text: `0/${cap}`, color: '#8a8a8a', isCompacting: false }
  const text = `${kfmt(tokens)}/${cap} ${Math.floor((tokens * 100) / limit)}%`
  if (tokens >= limit) return { text: `${text} ⚠ compacting`, color: '#ff0000', isCompacting: true }
  const stage = STAGES.findIndex(share => tokens <= limit * share)
  return { text, color: ['#5fff00', '#ffff00', '#ffaf00'][stage] ?? '#ff0000', isCompacting: false }
}

/** The auto-compact trigger, as the status line reckons it: CC_TOKEN_LIMIT, else `autoCompactWindow`, else 200k; less CC_TOKEN_RESERVE. */
async function readLimit($: EngineInterface): Promise<number> {
  const whole = (value: unknown) => {
    const n = typeof value === 'string' && /^\d{1,12}$/.test(value) ? Number(value) : value
    return typeof n === 'number' && Number.isInteger(n) && n > 0 ? n : null
  }
  const window = whole(await $.env.get('CC_TOKEN_LIMIT')) ?? whole((await $.settings.read()).autoCompactWindow) ?? WINDOW
  const limit = window - (whole(await $.env.get('CC_TOKEN_RESERVE')) ?? RESERVE)
  return limit > 0 ? limit : window
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

const HANDOVER_READ = `d="$HOME/.claude/plugins/data/handover-fundriven"
test -e "$d/live/$1" && echo on
echo "@@"; cat "$d/sessions/$1.json" 2>/dev/null
echo "@@"; cat "$d/options.json" 2>/dev/null`

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
  const titled = async (path: unknown) => {
    if (typeof path !== 'string' || !path) return null
    const head = await $.process.run(['head', '-n', '40', path])
    return { path, title: head.exitCode === 0 ? handoverTitle(head.stdout) : null }
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
    error: typeof st.error === 'string' ? st.error : null,
    resume: said ? resumeMessage(said) : null,
  }
  await update($, handover, () => next)
  if (next.written) await keepNotes($, [next.written.path])
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
  let limit = WINDOW - RESERVE

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'session-panel', description: 'Open the session overview pane' })
    void $.ui.open({ id: PANE, title: TITLE })
    ticker?.cancel()
    let ticks = 0
    ticker = $.clock.every(1000, () => {
      ticks++
      if (ticks % 5 === 0) void readHandover($)
      if (ticks % 30 === 0) void readLimit($).then(n => (limit = n))
      if (ticks % 60 === 0) void refreshPr($)
      $.ui.invalidate('ui.render')
    })
    const remote = await $.process.run(['git', '-C', e.cwd, 'remote', 'get-url', 'origin'])
    await update($, home, () => (remote.exitCode === 0 ? repoOfRemote(remote.stdout) : null))
    hasLinearApp = (await $.process.run(['test', '-d', '/Applications/Linear.app'])).exitCode === 0
    await readHandover($)
    limit = await readLimit($)
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
    await $.ui.open({ id: PANE, title: TITLE, focus: true })
    return { text: 'Session panel opened.' }
  })

  on('prompt.submit', async ($, e, next) => {
    const text = e.origin.kind === 'composer' ? promptText(e.text) : null
    if (text) {
      await update($, prompts, list => [...list, text])
      await scanPrompt($, text)
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

  on('turn.complete', async ($, e, next) => {
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
    const layout = await read($, quotaLayout)
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

    const card = (a: Agent, isDone: boolean) => {
      const key = a.id ?? a.toolUseId
      const isOpen = open === key
      const history = isOpen ? a.history : a.history.slice(-3)
      const elapsed = duration((a.endedAt ?? now) - a.startedAt)
      return (
        <Box key={key} flexDirection="column" marginBottom={1}>
          <Button
            key={`agent:${key}`}
            label={`${isOpen ? '▾' : '▸'} ${a.description}`}
            plain
            dimColor={isDone}
            onPress={() => update($, expanded, cur => (cur === key ? null : key))}
          />
          <Text dimColor wrap="truncate-end">
            {a.type}
            {a.model ? ` · ${prettyModel(a.model)}` : ''} · {elapsed}
            {a.isBackground ? ' · bg' : ''}
          </Text>
          <Text dimColor={isDone} italic wrap={isOpen ? 'wrap' : 'truncate-end'}>
            {isOpen ? a.prompt : oneLine(a.prompt, 200)}
          </Text>
          {!isOpen && a.history.length > 3 && <Text dimColor>… {a.history.length - 3} earlier</Text>}
          {history.map(entry => (
            <Text
              dimColor={isDone || entry.kind === 'result' || entry.kind === 'think'}
              color={entry.kind === 'error' ? 'error' : undefined}
              wrap={isOpen ? 'wrap' : 'truncate-end'}
            >
              {entry.kind === 'tool' ? '› ' : entry.kind === 'think' ? '∴ ' : entry.kind === 'result' ? '  ⎿ ' : entry.kind === 'error' ? '✗ ' : '“ '}
              {entry.text}
            </Text>
          ))}
        </Box>
      )
    }

    const pill = (key: string, label: string, color: string, isOn: boolean, onPress: () => unknown) => (
      <Box key={`${key}:pill`} borderStyle="round" borderColor={color} paddingX={1}>
        <Text color={color}>{isOn ? '● ' : '○ '}</Text>
        <Button key={key} label={label} plain onPress={onPress} />
      </Box>
    )

    /** Copies the resume message, clears the session (the handover plugin loads the handover into the next one), and leaves the message in the prompt box to send. */
    const startNext = async (resume: string | null, surface: typeof e.surface) => {
      if (resume) await $.ui.copy({ text: resume, surface })
      await $.command.run({ command: 'clear' })
      if (resume) await $.prompt.fill({ text: resume })
    }

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
            {t.pr.state && <Text dimColor> {t.pr.state}</Text>}
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

    const handoverRows = (() => {
      if (!ho) return [<Text dimColor>Not read yet.</Text>]
      if (!ho.isOn) return [<Text dimColor>The handover plugin is off in this session.</Text>]
      const status = handoverStatus(ho, usage.context.tokens ?? 0)
      const file = (label: string, f: { path: string; title: string | null } | null) => (
        <Text wrap="truncate-end">
          <Text dimColor>{label} </Text>
          {f ? <Link href={`file://${f.path}`} label={f.title ?? f.path.split('/').pop() ?? f.path} /> : <Text dimColor>none</Text>}
        </Text>
      )
      const isStopped = ho.written !== null && current === null
      return [
        <Text color={status.color}>✋ {status.text}</Text>,
        file('loaded', ho.loaded),
        ...(ho.written ? [file('written', ho.written)] : []),
        ...(isStopped
          ? [
              <Box key="handover:next" flexDirection="column" marginTop={1}>
                <Button
                  key="handover:clear"
                  label={ho.resume ? '⏭  /clear and paste the resume message' : '⏭  /clear and start the next session'}
                  variant="primary"
                  autoFocus
                  onPress={press => startNext(ho.resume, press.surface)}
                />
                {ho.resume && (
                  <Text dimColor italic wrap="wrap">
                    {ho.resume}
                  </Text>
                )}
              </Box>,
            ]
          : []),
      ]
    })()

    if (shown === 'prompts') {
      return (
        <Box flexDirection="column" paddingX={1}>
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
            onPress={() => update($, expanded, cur => (cur === key ? null : key))}
          />
          <Text dimColor wrap="truncate-end">
            {'  '}
            {kindOf(a)} · {duration((a.endedAt ?? now) - a.startedAt)} · {isDone ? 'done' : currentTask(a)}
          </Text>
        </Box>
      )
    }

    return (
      <Box flexDirection="column" paddingX={1}>
        <Box flexDirection="row" justifyContent="space-between" columnGap={2} marginBottom={1}>
          <Box flexDirection="column" flexShrink={0}>
            <Box flexDirection="row" columnGap={1}>
              {pill('pick:model', i.model ? prettyModel(i.model) : 'model…', modelColor(i.model), picker === 'model', () =>
                toggle('model'),
              )}
              {pill('pick:effort', effortLabel(i.effort), effortColor(i.effort), picker === 'effort', () =>
                toggle('effort'),
              )}
            </Box>
            {options && (
              <Box flexDirection="row" flexWrap="wrap" columnGap={1}>
                {options}
              </Box>
            )}
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

        {quotas.length > 0 && (
          <Box flexDirection="column" marginBottom={1}>
            <Box flexDirection="row">
              {section('Quotas ')}
              <Button
                key="quotas:layout"
                label={layout === 'side' ? '⇄ one per line' : '⇄ side by side'}
                plain
                dimColor
                onPress={() => update($, quotaLayout, cur => (cur === 'side' ? 'stacked' : 'side'))}
              />
            </Box>
            <Box flexDirection={layout === 'side' ? 'row' : 'column'} columnGap={3}>
              {quotas.map(q => quotaBar(q, layout === 'side' ? Math.floor((columns - 3 * (quotas.length - 1)) / quotas.length) : columns))}
            </Box>
          </Box>
        )}

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

        {section('Handover')}
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
  })
}
