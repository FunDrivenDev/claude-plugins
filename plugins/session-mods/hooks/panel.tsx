import { atom, read, update } from 'claude-code'
import type { EngineInterface, Hook, On, RenderElement, ToolCallInput, ToolCallResult, UiCopyArgs } from 'claude-code'

import type { Agent, Config, Doc, Entry, FileChange, Handover, HandoverFile, HandoverThresholds, Prompt, Repo, RepoChanges, Step, Tab, TrackedIssue, TrackedPr } from '../types'

import { LOG_FORMAT, parseLog, parseNumstat, parseStatus, treeRows } from './files'
import { ARTIFACTS, HANDOVER_DIR, PLANS_DIR, artifactOf, type DocContext, docGroups, docOf, docPaths, tilde } from './documents'
import { PR_COLOR, RANK, findRefs, linearOfResult, prState, refKey, refsOfGh, repoOfRemote, titleOfSlug } from './tracker'
import type { GithubRef, LinearRef } from './tracker'

const PANE = 'session-panel'

type StartArgs = Parameters<Hook<'session.start'>>
type StepArgs = Parameters<Hook<'turn.step'>>
const TITLE = 'Session'
/** The dock's opening width in fullscreen: more than any terminal gives, so the engine opens it at its ceiling (45% of the terminal); a width the person dragged or keyed wins. */
const DOCK_COLUMNS = 512
/** The colour an action without its own takes under the pointer: Catppuccin Frappé blue. */
const ACTION = '#8caaee'
const HISTORY_CAP = 400
/** An open sub-agent's latest entries and the head of its task: the whole of either can pass the engine's 100,000 drawn characters. */
const OPEN_HISTORY = 40
const OPEN_PROMPT = 4000
const STEPS_CAP = 300
/** Finished steps shown while the list is folded, above the current one. */
const DONE_SHOWN = 4

const agents = atom({ plugin: 'session-mods', key: 'agents' } as const, [] as Agent[])
const steps = atom({ plugin: 'session-mods', key: 'steps' } as const, [] as Step[])
const expanded = atom({ plugin: 'session-mods', key: 'expanded' } as const, null as string | null)
const stepsOpen = atom({ plugin: 'session-mods', key: 'stepsOpen' } as const, false)
const roots = atom({ plugin: 'session-mods', key: 'roots' } as const, [] as string[])
const changes = atom({ plugin: 'session-mods', key: 'changes' } as const, [] as RepoChanges[])
const UNTRACKED_COUNTED = 30
const COMMITS_SHOWN = 8
const EDITING_TOOLS = new Set(['Edit', 'MultiEdit', 'Write', 'NotebookEdit', 'Bash'])
const prompts = atom({ plugin: 'session-mods', key: 'prompts' } as const, [] as (Prompt | string)[])
const view = atom({ plugin: 'session-mods', key: 'view' } as const, 'overview' as 'overview' | 'prompts')
/** The repositories the session worked on, in the order it first touched them. */
const workedRepos = atom({ plugin: 'session-mods', key: 'repos' } as const, [] as Repo[])
/** A repository as the Git section draws it; `isLocal` false for one known only by a pull request. */
type RepoBlock = { key: string; name: string; pr: TrackedPr | null; worktree: string | null; isLocal: boolean }
const tracker = atom({ plugin: 'session-mods', key: 'tracker' } as const, { issue: null, prs: [], mentioned: [] } as {
  issue: TrackedIssue | null
  prs: TrackedPr[]
  mentioned: string[]
})
const handover = atom({ plugin: 'session-mods', key: 'handover' } as const, null as Handover | null)
const documents = atom({ plugin: 'session-mods', key: 'documents' } as const, [] as Doc[])
const config = atom({ plugin: 'session-mods', key: 'config' } as const, {
  plansDirectory: null,
  handoverDir: null,
} as Config)
const tab = atom({ plugin: 'session-mods', key: 'tab' } as const, 'main' as Tab)
/** The session's overall topic, as the main agent names it with the session_title tool. */
const topic = atom({ plugin: 'session-mods', key: 'topic' } as const, null as string | null)
/** The session whose title is set, and the one reminded to set it: a title carried over through /clear or a reload belongs to another. */
const titled = atom({ plugin: 'session-mods', key: 'titled' } as const, { set: null, reminded: null } as { set: string | null; reminded: string | null })
const WRITING_TOOLS = new Set(['Edit', 'MultiEdit', 'Write', 'NotebookEdit'])
/** Where documents are told apart, for the handover and plans folders it was read with. */
let docContext: { key: string; ctx: DocContext } | null = null
/** Main-loop calls that returned, possibly before the step that made them ended. */
const returned = new Set<string>()
let hasLinearApp = false
const home = atom({ plugin: 'session-mods', key: 'home' } as const, null as string | null)
const LINEAR_ID = /\b[A-Z][A-Z0-9]{1,9}-\d+\b/g
const ISSUE_ICON = { github: { glyph: '◉', color: '#3fb950' }, linear: { glyph: '◐', color: '#5e6ad2' } } as const

export type Scheme = 'dark' | 'light'

/**
 * Each colour the pane draws, as written for a dark background, with its twin
 * for a light one: Catppuccin Latte for Frappé; for GitHub's colours, the
 * nearest tone that reads on white.
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

/** The message the closing reply hands the next session: its code block after `/clear`, on one line, as the handover plugin reads it. */
export const resumeMessage = (reply: string): string | null => {
  const at = reply.search(/\/clear\b/)
  const block = at < 0 ? null : /```[^\n]*\n([\s\S]*?)```/.exec(reply.slice(at))
  return block ? block[1]!.split(/\s+/).filter(Boolean).join(' ') || null : null
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

const isStop = (c: string | undefined) => c === '.' || c === '!' || c === '?'

/**
 * The last whole sentence of a text being streamed, once there is one: the
 * last run of `.!?` followed by a space or the end, with the words before it
 * back to the previous `.!?`. Read from the end: it is asked again for each
 * streamed piece, and a scan of the whole text each time grows quadratic.
 */
export const lastSentence = (text: string): string | null => {
  for (let end = text.length; end > 0; end--) {
    if (!isStop(text[end - 1]) || (end < text.length && !/\s/.test(text[end]!))) continue
    let stop = end - 1
    while (stop > 0 && isStop(text[stop - 1])) stop--
    let start = stop
    while (start > 0 && !isStop(text[start - 1])) start--
    return start < stop ? text.slice(start, end).replace(/\s+/g, ' ').trim() : null
  }
  return null
}

/** A step is current while its answer streams or a call it made has not returned. */
export const isRunning = (s: Step): boolean => !s.isDone || !(s.toolIds ?? []).every(id => s.doneIds?.includes(id))

/** A handover's title: its front matter's `summary`, else its `# Handover:` heading. */
export const handoverTitle = (text: string): string | null => {
  const front = /^---\n([\s\S]*?)\n---/.exec(text)?.[1]
  const summary = front && /^summary:\s*["']?(.+?)["']?\s*$/m.exec(front)?.[1]
  return summary || /^#\s*Hand(?:over|off):\s*(.+)$/m.exec(text)?.[1]?.trim() || null
}

/** The hint beside Last prompt, `11 previous prompts`: how many came before it. */
export const previousPrompts = (n: number): string =>
  n <= 0 ? 'no previous prompt' : `${n} previous ${n === 1 ? 'prompt' : 'prompts'}`

/** When a prompt was submitted, `09:05` in local 24-hour time. */
export const clockTime = (at: number): string => {
  const d = new Date(at)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** A stored prompt; one kept by an earlier version is bare text, without its time. */
const promptOf = (p: Prompt | string): Prompt => (typeof p === 'string' ? { text: p, at: null } : p)

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
  const t = h.thresholds
  if (!t) return { text: `thresholds unknown · ${h.thresholdsError}`, color: '#e78284' }
  const suggested = t.suggest > 0 && tokens >= t.suggest
  if (!t.trigger) return { text: suggested ? 'suggested' : 'trigger off', color: '#a5adce' }
  if (tokens >= t.trigger) return { text: 'wind-down on the next tool call', color: '#ef9f76' }
  return {
    text: `${suggested ? 'suggested · ' : ''}triggers at ${kilo(t.trigger)} · now ${kilo(tokens)}`,
    color: tokens >= t.warnAt ? '#e5c890' : '#a5adce',
  }
}

/** The two ways to start the next session from a written handover, each in its Catppuccin Frappé colour. */
const NEXT_ACTIONS = [
  { key: 'handover:run', emoji: '🚀', label: 'Start with this prompt', color: '#a6d189', isSent: true },
  { key: 'handover:edit', emoji: '✏️', label: 'Edit the prompt first', color: '#8caaee', isSent: false },
] as const

/** The context has reached the wind-down trigger; false when it is off or unknown. */
const isPastTrigger = (h: Handover, tokens: number) => Boolean(h.thresholds?.trigger) && tokens >= (h.thresholds?.trigger ?? 0)

export type HandoverPhase = 'winding' | 'writing' | 'ready'

/** Where a handover under way stands: winding down, being written, or written; null before it starts or once it failed. */
export const handoverPhase = (h: Handover, tokens: number): HandoverPhase | null => {
  if (h.error) return null
  if (h.written) return 'ready'
  if (h.isWriting) return 'writing'
  if (h.isWindingDown || isPastTrigger(h, tokens)) return 'winding'
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
const TRIGGER_NOW = { key: 'handover:trigger', emoji: '⚡', label: 'Hand over now', color: '#e5c890' } as const

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

/** Adds the repository holding `dir` to those the Files and Git sections show, noting the linked worktree it lies in. */
async function trackRepo($: EngineInterface, dir: string) {
  const out = await $.process.run(['git', '-C', dir, 'rev-parse', '--path-format=absolute', '--show-toplevel', '--git-dir', '--git-common-dir'])
  const [root = '', gitDir = '', commonDir = ''] = out.stdout.trim().split('\n')
  if (out.exitCode !== 0 || !root) return
  await update($, roots, list => (list.includes(root) ? list : [...list, root]))
  const common = commonDir || root
  const worktree = gitDir && commonDir && gitDir !== commonDir ? (root.split('/').pop() ?? root) : null
  const known = (await read($, workedRepos)).find(r => r.common === common)
  if (known) {
    if (known.worktree !== worktree) await update($, workedRepos, list => list.map(r => (r.common === common ? { ...r, worktree } : r)))
    return
  }
  const remote = await $.process.run(['git', '-C', root, 'remote', 'get-url', 'origin'])
  const slug = remote.exitCode === 0 ? repoOfRemote(remote.stdout) : null
  const name = slug?.split('/').pop() ?? (common.replace(/\/\.git\/?$/, '').split('/').pop() || root)
  await update($, workedRepos, list => (list.some(r => r.common === common) ? list : [...list, { common, slug, name, worktree }]))
}

/** One repository's changes against HEAD, untracked files included; null when git cannot read it or it has none. */
async function changesOf($: EngineInterface, root: string, since: number): Promise<RepoChanges | null> {
  const git = (...args: string[]) => $.process.run(['git', '-C', root, ...args])
  const status = await git('status', '--porcelain=v1', '-z', '--untracked-files=all')
  if (status.exitCode !== 0) return null
  const kinds = parseStatus(status.stdout)
  // Independent reads, run side by side rather than one after another.
  const [numstat, log, ahead, current] = await Promise.all([
    git('diff', '--numstat', 'HEAD'),
    git('log', `-n${COMMITS_SHOWN}`, `--since=@${since}`, `--format=${LOG_FORMAT}`),
    git('rev-list', '@{u}..HEAD'),
    git('branch', '--show-current'),
  ])
  const counts = parseNumstat(numstat.stdout)
  let untracked = 0
  const files = await Promise.all(
    [...kinds].map(async ([path, kind]): Promise<FileChange> => {
      let count = counts.get(path)
      if (!count && kind === 'added' && untracked++ < UNTRACKED_COUNTED) {
        const diff = await git('diff', '--no-index', '--numstat', '/dev/null', path)
        count = [...parseNumstat(diff.stdout).values()][0]
      }
      return { path, status: kind, added: count?.added ?? 0, removed: count?.removed ?? 0 }
    }),
  )
  const unpushed = ahead.exitCode === 0 ? new Set(ahead.stdout.split('\n').filter(Boolean)) : ('all' as const)
  const commits = log.exitCode === 0 ? parseLog(log.stdout, unpushed) : []
  const branch = current.stdout.trim() || 'detached'
  return files.length || commits.length ? { root, branch, files, commits } : null
}

/** Reads each tracked repository's changes, the repositories side by side, kept in their order. */
async function refreshFiles($: EngineInterface) {
  const since = Math.floor((await $.session.usage()).startedAt / 1000)
  const found = await Promise.all((await read($, roots)).map(root => changesOf($, root, since)))
  const next = found.filter((repo): repo is RepoChanges => repo !== null)
  await update($, changes, () => next)
}

/** Marks a main-loop call as returned, so the step that made it can end. */
async function markReturned($: EngineInterface, toolUseId: string) {
  await update($, steps, list =>
    list.map(s => (s.toolIds?.includes(toolUseId) ? { ...s, doneIds: [...(s.doneIds ?? []), toolUseId] } : s)),
  )
}

/** Keeps the issue seen with the best rank, the first one on a tie. */
async function keep($: EngineInterface, next: TrackedIssue) {
  await update($, tracker, t => {
    const cur = t.issue
    if (cur?.key === next.key) return { ...t, issue: { ...next, rank: Math.min(cur.rank, next.rank) } }
    if (cur && cur.rank <= next.rank) return t
    return { ...t, issue: next }
  })
}

/** Keeps, per repository, the pull request seen with the best rank, the first one on a tie. */
async function keepPr($: EngineInterface, next: TrackedPr) {
  await update($, tracker, t => {
    const prs = t.prs ?? []
    const cur = prs.find(p => p.repo.toLowerCase() === next.repo.toLowerCase())
    if (!cur) return { ...t, prs: [...prs, next] }
    if (cur.number !== next.number && cur.rank <= next.rank) return t
    const kept = cur.number === next.number ? { ...next, rank: Math.min(cur.rank, next.rank) } : next
    return { ...t, prs: prs.map(p => (p === cur ? kept : p)) }
  })
}

/** Reads a GitHub issue or pull request and keeps it in its slot; `seen` skips one already read at that rank. */
async function noteGithub($: EngineInterface, ref: GithubRef, rank: number, seen?: Set<string>) {
  if (seen?.has(`${refKey(ref)}@${rank}`)) return
  seen?.add(`${refKey(ref)}@${rank}`)
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
    await keepPr($, { repo: ref.repo, number: ref.number, title: data?.title ?? null, url, state, rank })
  } else {
    await keep($, { platform: 'github', key: `${ref.repo}#${ref.number}`, title: data?.title ?? null, url, appUrl: null, rank })
  }
}

async function noteLinear($: EngineInterface, ref: LinearRef, title: string | null, rank: number) {
  const mentioned = (await read($, tracker)).mentioned.includes(ref.id)
  const base = ref.workspace ? `linear.app/${ref.workspace}/issue/${ref.id}` : null
  await keep($, {
    platform: 'linear',
    key: ref.id,
    title: title ?? titleOfSlug(ref.slug),
    url: base && `https://${base}${ref.slug ? `/${ref.slug}` : ''}`,
    appUrl: ref.workspace ? `linear://${ref.workspace}/issue/${ref.id}` : null,
    rank: mentioned ? RANK.prompt : rank,
  })
}

/** Looks for the issues and pull requests a prompt names. */
async function scanPrompt($: EngineInterface, text: string, seen?: Set<string>) {
  const ids = text.match(LINEAR_ID) ?? []
  if (ids.length) await update($, tracker, t => ({ ...t, mentioned: [...new Set([...t.mentioned, ...ids])] }))
  for (const ref of findRefs(text, await read($, home))) {
    if (ref.platform === 'github') await noteGithub($, ref, ref.isBare ? RANK.mentioned : RANK.prompt, seen)
    else await noteLinear($, ref, null, RANK.prompt)
  }
}

/** Looks for an issue or pull request a `gh` command or a Linear tool worked on. */
async function scanCall($: EngineInterface, tool: string, input: Record<string, unknown>, ran: ToolCallResult, seen?: Set<string>) {
  if (ran.deny !== undefined || ran.isError) return
  if (tool === 'Bash' && typeof input.command === 'string') {
    const found = refsOfGh(input.command, ran.text ?? '', await read($, home))
    for (const ref of found?.refs ?? []) {
      if (ref.platform === 'github') await noteGithub($, ref, found!.rank, seen)
      else await noteLinear($, ref, null, found!.rank)
    }
  } else if (/linear/i.test(tool) && ran.text) {
    const issue = linearOfResult(ran.text)
    if (issue) await noteLinear($, issue.ref, issue.title, /create/i.test(tool) ? RANK.created : RANK.worked)
  }
}

/**
 * Finds the session's issue and pull request again from its whole transcript,
 * its prompts and calls in order: a plugin loaded mid-session missed the earlier ones.
 */
async function rescanTracker($: EngineInterface) {
  const messages = await $.session.messages()
  await update($, tracker, t => ({ ...t, issue: null, prs: [] }))
  const seen = new Set<string>()
  let lastDir: string | null = null
  for (const m of messages) {
    const text = m.role === 'user' && !m.toolResults?.length ? promptText(m.text) : null
    if (text) await scanPrompt($, text, seen)
    for (const call of m.toolUses) {
      if (call.text !== undefined) await scanCall($, call.tool, call.input, { text: call.text, isError: call.isError } as ToolCallResult, seen)
      const path = call.input.file_path
      const dir = typeof path === 'string' && path.startsWith('/') ? path.slice(0, path.lastIndexOf('/')) || '/' : null
      if (dir && dir !== lastDir && !call.isError) {
        lastDir = dir
        await trackRepo($, dir)
      }
    }
  }
}

/** Reads the shown pull request's state again: it moves on GitHub. */
async function refreshPr($: EngineInterface) {
  for (const pr of (await read($, tracker)).prs ?? []) await noteGithub($, { platform: 'github', repo: pr.repo, number: pr.number, type: 'pull' }, pr.rank)
}

/** `$HOME`, the project's git folder, then the real paths of the temporary folders and of each folder named. */
const DOC_CONTEXT = `printf '%s\\n' "$HOME"
git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || echo
for d in /tmp "\${TMPDIR:-/tmp}" "$@"; do
  case $d in "~/"*) d="$HOME/$(printf %s "$d" | cut -c3-)";; esac
  (cd "$d" 2>/dev/null && pwd -P) || echo "$d"
done`

/** Each file changed since `$1` (epoch seconds): its path as named, its real path, and the git folder of its repository. */
const WRITTEN_SINCE = `start=$1; shift
for f; do
  [ -f "$f" ] || continue
  [ "$(date -r "$f" +%s)" -ge "$start" ] || continue
  d=$(cd "$(dirname "$f")" && pwd -P) || continue
  printf '%s\\n%s/%s\\n%s\\n' "$f" "$d" "$(basename "$f")" "$(cd "$d" && git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
done`

/** Where documents are told apart, read again once the handover or plans folder changes. */
async function contextOfDocs($: EngineInterface): Promise<DocContext> {
  const c = await read($, config)
  const dirs = [c.handoverDir ?? HANDOVER_DIR, c.plansDirectory ?? PLANS_DIR]
  const key = dirs.join('\n')
  if (docContext?.key === key) return docContext.ctx
  const out = await $.process.run(['sh', '-c', DOC_CONTEXT, 'sh', ...dirs])
  const [home = '', project = '', tmp = '', tmpdir = '', handovers = '', plans = ''] = out.stdout.split('\n')
  const ctx = { home, project: project || null, tmp: [...new Set([tmp, tmpdir].filter(Boolean))], handovers, plans }
  if (home) docContext = { key, ctx }
  return ctx
}

/** Adds the Markdown files among `paths` changed since `since` (epoch seconds) that are documents, once each. */
async function keepDocs($: EngineInterface, paths: string[], since = 0) {
  const named = paths.filter(path => /\.md$/i.test(path))
  if (!named.length) return
  const ctx = await contextOfDocs($)
  const out = await $.process.run(['sh', '-c', WRITTEN_SINCE, 'sh', String(since), ...named])
  const lines = out.stdout.split('\n')
  const found: Doc[] = []
  for (let k = 0; k + 2 < lines.length; k += 3) {
    const doc = docOf({ path: lines[k]!, real: lines[k + 1]!, repo: lines[k + 2] || null }, ctx)
    if (doc) found.push(doc)
  }
  if (found.length) await addDocs($, found)
}

/** Adds documents, once each; one already listed takes the newer name (an artifact retitled). */
const addDocs = ($: EngineInterface, found: Doc[]) =>
  update($, documents, list => [...list.map(d => found.find(f => f.id === d.id) ?? d), ...found.filter(f => !list.some(d => d.id === f.id))])

/** The documents a call wrote: an artifact it published, an editing tool's Markdown file, or one a command names that changed since the session began. */
async function scanDocs($: EngineInterface, tool: string, input: Record<string, unknown>, ran: ToolCallResult) {
  if (ran.deny !== undefined || ran.isError) return
  if (tool === 'Artifact') {
    const art = artifactOf(input, ran.result)
    return art ? addDocs($, [art]) : undefined
  }
  const path = input.file_path ?? input.notebook_path
  if (WRITING_TOOLS.has(tool) && typeof path === 'string') return keepDocs($, [path])
  if (tool !== 'Bash' || typeof input.command !== 'string' || !/\.md\b/i.test(input.command)) return
  const named = docPaths(input.command, (await contextOfDocs($)).home)
  if (!named.length) return
  await keepDocs($, named, Math.floor((await $.session.usage()).startedAt / 1000))
}

/** The values the pane reads from Claude Code's settings and the environment, as set. */
async function readConfig($: EngineInterface) {
  const settings = await $.settings.read().catch(() => ({}) as Record<string, unknown>)
  const plans = (settings as Record<string, unknown>).plansDirectory
  const plansDirectory = typeof plans === 'string' && plans.trim() ? plans.trim() : null
  await update($, config, c => ({ ...c, plansDirectory }))
}

const HANDOVER_READ = `d="$HOME/.claude/plugins/data/handover-fundrivendev"
test -d "$d" || d="$HOME/.claude/plugins/data/handover-fundriven"
test -e "$d/live/$1" && echo on
echo "@@"; cat "$d/sessions/$1.json" 2>/dev/null
echo "@@"; cat "$d/options.json" 2>/dev/null || echo "missing $d/options.json"`

/** A handover's first lines, for its title, then its line count and last change (`date -r` works on macOS and GNU). */
const HANDOVER_FILE = `head -n 40 "$1" || exit 1
printf '\\n@@\\n'; wc -l < "$1"; date -r "$1" +%s`

/** The handover plugin's saved thresholds, from its options.json, or why they could not be read: never a default of the pane's own. */
export const readThresholds = (opts: string): { thresholds: HandoverThresholds | null; thresholdsError: string | null } => {
  const failed = (thresholdsError: string) => ({ thresholds: null, thresholdsError })
  const missing = /^missing (.*)/.exec(opts.trim())
  if (missing) return failed(`${missing[1]} not found; the handover plugin writes it at session start`)
  let opt: unknown
  try {
    opt = JSON.parse(opts)
  } catch {
    return failed("the handover plugin's options.json is not valid JSON")
  }
  const saved = (opt as { thresholds?: unknown } | null)?.thresholds
  if (typeof saved !== 'object' || saved === null) {
    return failed("the handover plugin's options.json has no thresholds; handover 0.19.0 and later write them at session start")
  }
  const values: Record<string, unknown> = { ...saved }
  const keys = { suggest: 'suggest_tokens', warnAt: 'warn_at_tokens', trigger: 'trigger_tokens' } as const
  const bad = Object.values(keys).filter(key => typeof values[key] !== 'number')
  if (bad.length) return failed(`in the handover plugin's options.json, not a number: thresholds.${bad.join(', thresholds.')}`)
  return {
    thresholds: { suggest: values.suggest_tokens as number, warnAt: values.warn_at_tokens as number, trigger: values.trigger_tokens as number },
    thresholdsError: null,
  }
}

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
    ...readThresholds(opts),
    isWriting: typeof writer?.since === 'number' && now - writer.since < 660,
    isWindingDown: Boolean(st.wind_down),
    error: typeof st.error === 'string' ? st.error : null,
    resume: said ? resumeMessage(said) : null,
  }
  await update($, handover, () => next)
  const dir = typeof opt.handover_dir === 'string' && opt.handover_dir.trim() ? opt.handover_dir.trim() : null
  if ((await read($, config)).handoverDir !== dir) await update($, config, c => ({ ...c, handoverDir: dir }))
  if (next.written) await keepDocs($, [next.written.path])
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
const TITLE_TOOL_ID = `mcp__session-mods__${TITLE_TOOL}`
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

/** The pane's tick and colour scheme, shared by its session start and its drawing. */
let ticker: { cancel: () => void } | null = null
let scheme: Scheme = 'dark'

/** The pane's work at session start, before `register` lets the chain go on. */
export async function startPanel($: StartArgs[0], e: StartArgs[1]): Promise<void> {
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
    if (ticks % 30 === 0) void readConfig($)
    if (ticks % 60 === 0) void refreshPr($)
    $.ui.invalidate('ui.render')
  })
  const remote = await $.process.run(['git', '-C', e.cwd, 'remote', 'get-url', 'origin'])
  await update($, home, () => (remote.exitCode === 0 ? repoOfRemote(remote.stdout) : null))
  hasLinearApp = (await $.process.run(['test', '-d', '/Applications/Linear.app'])).exitCode === 0
  await readHandover($)
  await titleFromHandover($)
  await readConfig($)
  scheme = await readScheme($)
  await trackRepo($, e.cwd)
  await refreshFiles($)

  if ((await read($, prompts)).length === 0) {
    const typed = (await $.session.messages())
      .filter(m => m.role === 'user' && !m.toolResults?.length)
      .map(m => promptText(m.text))
      .filter((text): text is string => text !== null)
    if (typed.length) await update($, prompts, () => typed.map(text => ({ text, at: null })))
  }
  await rescanTracker($)
}

/** The pane's `turn.step` hook, which `register` wraps in the bar's work. */
export async function* stepPanel($: StepArgs[0], e: StepArgs[1], next: StepArgs[2]) {
  const agentId = e.agentId
  const stepId = `${e.turnId}:${e.index}`
  if (!agentId) {
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
    const calls = result.toolUses.map(use =>
      intentOf(use.name, typeof use.input === 'object' && use.input !== null ? (use.input as Record<string, unknown>) : {}),
    )
    const label =
      (calls.length && calls.map(c => c.what).join(' · ')) || (thought && headline(thought)) || (said && headline(said)) || 'Answered'
    const how = calls.map(c => c.how).filter(Boolean).join(' · ') || undefined
    const why = calls.length && thought ? headline(thought) : undefined
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
}

export const registerPanel = (on: On) => {

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
      const at = await $.clock.now()
      await update($, prompts, list => [...list, { text, at }])
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
    await scanDocs($, tool, input, ran)
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
    const [now, all, done, open, isStepsOpen, repos, stored, shown, t, ho, repoList, written, conf, usage, shownTab, title] = await Promise.all([
      $.clock.now(),
      read($, agents),
      read($, steps),
      read($, expanded),
      read($, stepsOpen),
      read($, changes),
      read($, prompts),
      read($, view),
      read($, tracker),
      read($, handover),
      read($, workedRepos),
      read($, documents),
      read($, config),
      $.session.usage(),
      read($, tab),
      read($, topic),
    ])
    const typed = stored.map(promptOf)
    const lastPrompt = typed.at(-1)
    const running = all.filter(a => a.endedAt === null)
    const finished = all.filter(a => a.endedAt !== null)
    /** What a sub-agent is doing now: its last call, else its last thought or words. */
    const currentTask = (a: Agent) => {
      const last = a.history.findLast(entry => entry.kind !== 'result')
      return last ? last.text : 'starting…'
    }
    const kindOf = (a: Agent) => (a.isTeammate ? 'teammate' : a.isBackground ? 'background' : 'sub-agent')

    /** An action lights in its colour under the pointer; each is its own hover group. */
    const hot = (key: string, color: string = ACTION) => ({ scope: key.slice(-64), color })
    /** A link underlines under the pointer, alone: its Text stands outside any other Text. */
    const link = (key: string, href: string, label: RenderElement | string, color?: string) => (
      <Text key={`link:${key}`} wrap="truncate-end" color={color} hover={{ scope: `link:${key}`.slice(-64), underline: true }}>
        {typeof label === 'string' ? <Link href={href} label={label} /> : <Link href={href}>{label}</Link>}
      </Text>
    )

    const section = (title: string) => (
      <Text bold color="claude">
        {title}
      </Text>
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
            hover={hot(`agent:${key}`)}
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
            <Button key={`agent:${key}:close`} label="▴ Collapse" plain dimColor hover={hot(`agent:${key}:close`)} onPress={() => toggleAgent(key)} />
          )}
        </Box>
      )
    }

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
    const prs = t.prs ?? []
    const sameRepo = (slug: string | null, pr: TrackedPr) => slug !== null && pr.repo.toLowerCase() === slug.toLowerCase()
    /** One block per repository worked on, then one per pull request worked on in a repository not checked out here. */
    const repoBlocks = (): RepoBlock[] => [
      ...repoList.map(r => ({ key: r.common, name: r.name, pr: prs.find(p => sameRepo(r.slug, p)) ?? null, worktree: r.worktree, isLocal: true })),
      ...prs
        .filter(p => !repoList.some(r => sameRepo(r.slug, p)))
        .map(p => ({ key: p.repo, name: p.repo.split('/').pop() ?? p.repo, pr: p, worktree: null, isLocal: false })),
    ]
    /** A repository: its pull request, linked in its state's colour, the state kept whatever the width; beneath, its worktree. */
    const repoBlock = (b: RepoBlock) => {
      const color = b.pr?.state ? PR_COLOR[b.pr.state] : '#a5adce'
      return (
        <Box key={`repo:${b.key}`} flexDirection="column" marginTop={1}>
          <Box flexDirection="row">
            <Box flexShrink={0}>
              <Text>⎇ {b.name} </Text>
            </Box>
            {b.pr ? link(`pr:${b.key}`, b.pr.url, `#${b.pr.number}${b.pr.title ? ` ${b.pr.title}` : ''}`, color) : <Text dimColor> no pull request yet</Text>}
            {b.pr?.state && (
              <Box flexShrink={0}>
                <Text color={color}>  {b.pr.state}</Text>
              </Box>
            )}
          </Box>
          {b.isLocal &&
            (b.worktree ? (
              <Text color="#81c8be" wrap="truncate-end">
                {'  '}▣ {b.worktree}
              </Text>
            ) : (
              <Text dimColor>{'  '}main checkout</Text>
            ))}
        </Box>
      )
    }
    const issueSection = () => (
      <Box flexDirection="row" marginBottom={1}>
        {section('Issue')}
        <Text>  </Text>
        {t.issue ? (
          <Box flexDirection="row" flexShrink={1}>
            <Text color={ISSUE_ICON[t.issue.platform].color}>{ISSUE_ICON[t.issue.platform].glyph} </Text>
            {issueHref ? link('issue', issueHref, t.issue.title ?? t.issue.key) : <Text wrap="truncate-end">{t.issue.title ?? t.issue.key}</Text>}
          </Box>
        ) : (
          <Text dimColor>no issue</Text>
        )}
      </Box>
    )
    const gitSection = (blocks: RepoBlock[]) =>
      blocks.length === 0 ? (
        <Box flexDirection="row" marginBottom={1}>
          {section('Git')}
          <Text dimColor>  no repository yet</Text>
        </Box>
      ) : (
        <Box flexDirection="column" marginBottom={1}>
          {section('Git')}
          {blocks.map(repoBlock)}
        </Box>
      )

    /** A handover file by its title, linked, then greyed its length and last change; `none` without one. */
    const handoverFile = (label: string, f: HandoverFile | null) => {
      const meta = f && fileMeta(f.lines, f.modifiedAt)
      return (
        <Box flexDirection="row">
          <Text dimColor>{label} </Text>
          {f ? link(`handover:${label}`, `file://${f.path}`, f.title ?? f.path.split('/').pop() ?? f.path) : <Text dimColor>none</Text>}
          {meta && <Text dimColor wrap="truncate-end"> ({meta})</Text>}
        </Box>
      )
    }

    const handoverRows = (() => {
      if (!ho) return [<Text dimColor>Not read yet.</Text>]
      if (!ho.isOn) return [<Text dimColor>The handover plugin is off in this session.</Text>]
      const status = handoverStatus(ho, usage.context.tokens ?? 0)
      const phase = handoverPhase(ho, usage.context.tokens ?? 0)
      const isStopped = ho.written !== null && current === null
      if (ho.written || ho.isWriting) triggered = false
      const isTriggerable = !ho.written && !ho.isWriting && !triggered && !isPastTrigger(ho, usage.context.tokens ?? 0)
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
      ]
    })()

    const tabPill = (key: Tab, label: string) => (
      <Box key={`tab:${key}:box`} borderStyle="round" borderColor={shownTab === key ? '#8caaee' : '#51576d'} paddingX={1}>
        <Button
          key={`tab:${key}`}
          label={label}
          plain
          dimColor={shownTab !== key}
          hover={hot(`tab:${key}`)}
          onPress={async () => {
            await update($, view, () => 'overview')
            await update($, tab, () => key)
          }}
        />
      </Box>
    )

    /** The session's title on a line of its own; beneath, the tabs and a close mark wide enough to click. */
    const header = (
      <Box flexDirection="column" marginBottom={1}>
        <Text bold color="claude" wrap="wrap">
          {title ?? TITLE}
        </Text>
        <Box flexDirection="row" alignItems="center" columnGap={1}>
          {tabPill('main', 'Main')}
          {tabPill('misc', 'Misc')}
          {tabPill('config', 'Config')}
          {tabPill('help', 'Help')}
          <Box flexGrow={1} />
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
      </Box>
    )

    if (shown === 'prompts') {
      return (
        <Box flexDirection="column" paddingX={1}>
          {header}
          <Button key="prompts:back" label="← Overview" plain hover={hot('prompts:back')} onPress={() => update($, view, () => 'overview')} />
          {section(`Prompts · ${typed.length}`)}
          {typed.map((p, index) => (
            <Box key={`prompt:${index}`} flexDirection="column" marginBottom={1}>
              <Text dimColor>
                #{index + 1}
                {p.at !== null ? ` · ${clockTime(p.at)}` : ''}
              </Text>
              <Text wrap="wrap">{p.text}</Text>
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
            hover={hot(`agent:${key}`)}
            onPress={() => toggleAgent(key)}
          />
          <Text dimColor wrap="truncate-end">
            {'  '}
            {kindOf(a)} · {duration((a.endedAt ?? now) - a.startedAt)} · {isDone ? 'done' : currentTask(a)}
          </Text>
        </Box>
      )
    }

    /** Each tab's body, drawn only for the tab shown: the ticker redraws the pane every second. */
    const mainBody = () => (
      <Box key="tab:main:body" flexDirection="column">
        {issueSection()}
        {gitSection(repoBlocks())}

        {section('Documents')}
        <Box flexDirection="column" marginBottom={1}>
          {written.length === 0 && <Text dimColor>None written yet.</Text>}
          {docGroups(written).map(group => (
            <Box key={`docs:${group.kind}`} flexDirection="column">
              <Text dimColor>{group.kind}</Text>
              {group.docs.map(d =>
                e.surface === 'terminal' ? (
                  <Box key={`doc:${d.id}:row`} paddingLeft={2}>
                    {link(`doc:${d.id}`, d.kind === ARTIFACTS ? d.path : `file://${d.path}`, d.name)}
                  </Box>
                ) : (
                  <Box key={`doc:${d.id}:row`} paddingLeft={2}>
                    <Button key={`doc:${d.id}`} label={d.name} plain hover={{ scope: `doc:${d.id}`.slice(-64), underline: true }} onPress={() => $.process.run(['open', d.path])} />
                  </Box>
                ),
              )}
            </Box>
          ))}
        </Box>

        {section('Handover')}
        <Box flexDirection="column" marginTop={1} marginBottom={1}>
          {ho?.isOn && <Box marginBottom={1}>{handoverFile('loaded', ho.loaded)}</Box>}
          {handoverRows}
        </Box>

        <Box flexDirection="row">
          {section('Last prompt ')}
          {lastPrompt?.at != null && <Text dimColor>{clockTime(lastPrompt.at)} </Text>}
          <Button
            key="prompts"
            label={`(${previousPrompts(typed.length - 1)})`}
            plain
            dimColor
            hover={hot('prompts')}
            onPress={() => update($, view, () => 'prompts')}
          />
        </Box>
        <Text wrap="wrap">{lastPrompt ? oneLine(lastPrompt.text, 360) : '—'}</Text>
      </Box>
    )

    const miscBody = () => (
      <Box key="tab:misc:body" flexDirection="column">
        <Box flexDirection="row">
          {section('Steps ')}
          {folded > 0 || isStepsOpen ? (
            <Button
              key="steps"
              label={isStepsOpen ? '▾ fold earlier steps' : `▸ ${folded} earlier${foldedIssues}`}
              plain
              dimColor
              hover={hot('steps')}
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
                        hover={hot(key)}
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


    const docHome = docContext?.ctx.home ?? ''
    /** An item as the pane draws it, in a fixed column, then greyed what it shows or does. */
    const helpRow = (key: string, example: RenderElement, does: string) => (
      <Box key={`help:${key}`} flexDirection="row" columnGap={1} alignItems="center" marginBottom={1}>
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
    const helpBody = () => (
      <Box key="tab:help:body" flexDirection="column">
        {section('Top lines')}
        <Box flexDirection="column">
          {helpRow('close', framed('#51576d', <Text> ✕ </Text>), 'Closes the pane; /session-panel reopens it on Main.')}
          {helpRow(
            'hover',
            <Text>
              <Text color={ACTION}>▸ Find hooks</Text>
              {'   '}
              <Text underline>session-panel guide</Text>
            </Text>,
            'Under the pointer, an action (a tab, a pill, a fold, a sub-agent, a commit) lights in its colour, blue when it has none; a link (an issue, a pull request, a document, a handover) underlines.',
          )}
        </Box>

        {section('Main')}
        <Box flexDirection="column">
          {helpRow(
            'issue',
            <Box flexDirection="row">
              {section('Issue')}
              <Text>  </Text>
              <Text color={ISSUE_ICON.linear.color}>{ISSUE_ICON.linear.glyph} </Text>
              {link('help:issue', 'https://linear.app', 'Fix the login loop')}
            </Box>,
            'The issue the session works on, linked (◐ Linear, ◉ GitHub): the one a prompt names, else the one it opened, else one it worked on; "no issue" until then.',
          )}
          {helpRow(
            'git',
            <Box flexDirection="row">
              {section('Git')}
              <Text dimColor>  no repository yet</Text>
            </Box>,
            'One block per repository the session worked on, in the order it first touched them, a blank line apart; "no repository yet" outside any.',
          )}
          {helpRow(
            'git:pr',
            repoBlock({
              key: 'help:pr',
              name: 'claude-plugins',
              pr: { repo: 'FunDrivenDev/claude-plugins', number: 21, title: 'session-panel 0.8.0', url: 'https://github.com/FunDrivenDev/claude-plugins/pull/21', state: 'draft', rank: 0 },
              worktree: 'session-panel-tabs',
              isLocal: true,
            }),
            "The repository, then its pull request, linked in its state's colour (draft, open, merged, closed); beneath, the linked worktree the session last edited in.",
          )}
          {helpRow(
            'git:none',
            repoBlock({ key: 'help:none', name: 'dotfiles', pr: null, worktree: null, isLocal: true }),
            'No pull request named, opened or worked on yet in this repository; "main checkout" when the session edits outside a linked worktree.',
          )}
          {helpRow('docs', section('Documents'), "What the session wrote that lasts, grouped by kind; 'None written yet.' until then.")}
          {helpRow(
            'docs:artifacts',
            <Box flexDirection="column">
              <Text dimColor>{ARTIFACTS}</Text>
              <Text>
                {'  '}
                <Text underline>Session panel guide</Text>
              </Text>
            </Box>,
            'First the artifacts it published, linked to claude.ai; press a document to open it.',
          )}
          {helpRow(
            'docs:handovers',
            <Box flexDirection="column">
              <Text dimColor>Agent handovers</Text>
              <Text>
                {'  '}
                <Text underline>21h57-session-panel</Text>
              </Text>
            </Box>,
            `The handovers written for the next session, in the handover plugin's handover_dir: ${tilde(conf.handoverDir ?? HANDOVER_DIR, docHome)}.`,
          )}
          {helpRow(
            'docs:plans',
            <Box flexDirection="column">
              <Text dimColor>Plans</Text>
              <Text>
                {'  '}
                <Text underline>quiet-river</Text>
              </Text>
            </Box>,
            `The plans, in Claude Code's plansDirectory setting: ${tilde(conf.plansDirectory ?? PLANS_DIR, docHome)}.`,
          )}
          {helpRow(
            'docs:other',
            <Box flexDirection="column">
              <Text dimColor>Reports</Text>
              <Text>
                {'  '}
                <Text underline>26-10-08-help-tab</Text>
              </Text>
            </Box>,
            "Any other Markdown file the agent wrote outside this project's repository, temporary and hidden folders, under its folder's name.",
          )}
          {helpRow('handover', section('Handover'), 'What the handover plugin does in this session: the handover it loaded, where it stands, and the one it wrote.')}
          {helpRow(
            'loaded',
            <Text>
              <Text dimColor>loaded </Text>
              <Text underline>Ship the panel</Text>
              <Text dimColor> (142 lines · 2026-10-07 09:32)</Text>
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
            'prompts',
            <Text>
              <Text bold color="claude">
                Last prompt{' '}
              </Text>
              <Text dimColor>14:32 (11 previous prompts)</Text>
            </Text>,
            'Your last typed prompt and when you sent it; press the count beside it to read every prompt of the session, each numbered with its time.',
          )}
        </Box>

        {section('Misc')}
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

    /** A value the pane reads: its name and value as in effect, then greyed what it does and its default. */
    const configRow = (key: string, name: string, value: string | null, fallback: string, does: string) =>
      helpRow(
        `config:${key}`,
        <Box flexDirection="column">
          <Text bold>{name}</Text>
          <Text wrap="truncate-end" color={value === null ? undefined : '#8caaee'} dimColor={value === null}>
            {value ?? `${fallback} (default)`}
          </Text>
        </Box>,
        `${does} Default: ${fallback}.`,
      )
    /** A token threshold as the handover plugin resolved it, defaults included, or why it is unknown. */
    const thresholdRow = (key: string, name: string, value: number | undefined, does: string) =>
      helpRow(
        `config:${key}`,
        <Box flexDirection="column">
          <Text bold>{name}</Text>
          <Text wrap="truncate-end" color={value === undefined ? '#e78284' : '#8caaee'}>
            {value !== undefined ? kilo(value) : `unknown · ${ho ? ho.thresholdsError : 'not read yet'}`}
          </Text>
        </Box>,
        does,
      )
    const whereSet = (text: string) => (
      <Box marginBottom={1}>
        <Text dimColor italic wrap="wrap">
          {text}
        </Text>
      </Box>
    )
    const configBody = () => (
      <Box key="tab:config:body" flexDirection="column">
        {section('Claude Code')}
        {whereSet('Settings: settings.json, or /config.')}
        {configRow('plans', 'plansDirectory', conf.plansDirectory && tilde(conf.plansDirectory, docHome), PLANS_DIR, 'Where Claude Code writes its plans: listed under Plans in Documents.')}

        {section('handover plugin')}
        {whereSet('Its options: pluginConfigs["handover@fundrivendev"].options in settings.json.')}
        {configRow('handover-dir', 'handover_dir', conf.handoverDir && tilde(conf.handoverDir, docHome), HANDOVER_DIR, 'Where handovers are written: listed under Agent handovers in Documents.')}
        {thresholdRow('suggest', 'suggest_tokens', ho?.thresholds?.suggest, 'Context size from which a handover is suggested at the next boundary.')}
        {thresholdRow('warn', 'thresholds.warn_at_tokens', ho?.thresholds?.warnAt, 'Context size at which the Handover line turns yellow, computed by the handover plugin.')}
        {thresholdRow('trigger', 'trigger_tokens', ho?.thresholds?.trigger, 'Context size at which the session winds down and hands over; 0 turns it off.')}
      </Box>
    )

    const pane = (
      <Box flexDirection="column" paddingX={1}>
        {header}
        {shownTab === 'help' ? helpBody() : shownTab === 'config' ? configBody() : shownTab === 'misc' ? miscBody() : mainBody()}
      </Box>
    )
    return recolor(pane, scheme)
  })
}
