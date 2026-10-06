import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, ToolCallInput, ToolCallResult } from 'claude-code'

import type { Agent, Entry, FileChange, Handover, Info, Picker, RepoChanges, Step, TrackedIssue, TrackedPr, Ttl } from '../types'

import { LOG_FORMAT, parseLog, parseNumstat, parseStatus, treeRows } from './files'
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
const picking = atom({ plugin: 'session-panel', key: 'picking' } as const, null as Picker)
const tracker = atom({ plugin: 'session-panel', key: 'tracker' } as const, { issue: null, pr: null, mentioned: [] } as {
  issue: TrackedIssue | null
  pr: TrackedPr | null
  mentioned: string[]
})
const handover = atom({ plugin: 'session-panel', key: 'handover' } as const, null as Handover | null)
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
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`
  if (m > 0) return `${m}m ${String(sec).padStart(2, '0')}s`
  return `${sec}s`
}

const oneLine = (text: string, max = 160): string => {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat
}

/** The first sentence of a block of thinking or text: a step's headline. */
export const headline = (text: string): string => {
  const flat = text.replace(/\s+/g, ' ').trim()
  const end = flat.search(/[.!?](\s|$)/)
  return oneLine(end > 0 ? flat.slice(0, end + 1) : flat, 90)
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
  return sentences?.length ? oneLine(sentences[sentences.length - 1]!.trim(), 200) : null
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
  for (const root of await read($, roots)) {
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
    const log = await $.process.run(['git', '-C', root, 'log', `-n${COMMITS_SHOWN}`, `--format=${LOG_FORMAT}`])
    const ahead = await $.process.run(['git', '-C', root, 'rev-list', '@{u}..HEAD'])
    const unpushed = ahead.exitCode === 0 ? new Set(ahead.stdout.split('\n').filter(Boolean)) : ('all' as const)
    const commits = log.exitCode === 0 ? parseLog(log.stdout, unpushed) : []
    const branch = (await $.process.run(['git', '-C', root, 'branch', '--show-current'])).stdout.trim() || 'detached'
    if (files.length || commits.length) next.push({ root, branch, files, commits })
  }
  await update($, changes, () => next)
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
  }
  await update($, handover, () => next)
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

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'session-panel', description: 'Open the session overview pane' })
    void $.ui.open({ id: PANE, title: TITLE })
    ticker?.cancel()
    let ticks = 0
    ticker = $.clock.every(1000, () => {
      ticks++
      if (ticks % 5 === 0) void readHandover($)
      if (ticks % 60 === 0) void refreshPr($)
      $.ui.invalidate('ui.render')
    })
    const remote = await $.process.run(['git', '-C', e.cwd, 'remote', 'get-url', 'origin'])
    await update($, home, () => (remote.exitCode === 0 ? repoOfRemote(remote.stdout) : null))
    hasLinearApp = (await $.process.run(['test', '-d', '/Applications/Linear.app'])).exitCode === 0
    await readHandover($)
    await trackRepo($, e.cwd)
    await refreshFiles($)

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
    const usage = await $.session.usage()

    const ttl = i.ttl ?? defaultTtl
    const cache =
      i.lastRequestAt === null
        ? { text: 'no request yet', color: undefined }
        : (() => {
            const left = i.lastRequestAt + ttlMs(ttl) - now
            if (left <= 0) return { text: `expired ${duration(-left)} ago`, color: 'warning' as const }
            return { text: `${duration(left)} left`, color: left < 60_000 ? ('warning' as const) : ('success' as const) }
          })()

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
      return [
        <Text color={status.color}>✋ {status.text}</Text>,
        file('loaded', ho.loaded),
        ...(ho.written ? [file('written', ho.written)] : []),
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
              <Text dimColor>running </Text>
              {duration(now - usage.startedAt)}
              <Text dimColor>   cache </Text>
              <Text color={cache.color}>{cache.text}</Text>
              <Text dimColor> ({ttl})</Text>
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

        {section('Handover')}
        <Box flexDirection="column" marginBottom={1}>
          {handoverRows}
        </Box>

        {section('Steps')}
        <Box flexDirection="column" marginBottom={1}>
          {folded > 0 || isStepsOpen ? (
            <Button
              key="steps"
              label={isStepsOpen ? '▾ fold earlier steps' : `▸ ${folded} earlier steps${foldedIssues}`}
              plain
              dimColor
              onPress={() => update($, stepsOpen, cur => !cur)}
            />
          ) : (
            done.length === 0 && <Text dimColor>None yet.</Text>
          )}
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
                {(s.note || s.how) && (
                  <Text dimColor wrap="wrap" color={s.note ? '#e78284' : undefined}>
                    {'  '}
                    {s.note ? `${s.flag}: ${s.note}` : s.how}
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
          {section('Files and history')}
          {repos.length === 0 && <Text dimColor>No change.</Text>}
          {repos.map(repo => (
            <Box key={repo.root} flexDirection="column" marginBottom={1}>
              <Text dimColor>
                {repo.root.split('/').pop()} <Text color="#8caaee">⎇ {repo.branch}</Text>{' '}
                <Text color="#a6d189">+{repo.files.reduce((n, f) => n + f.added, 0)}</Text>{' '}
                <Text color="#e78284">−{repo.files.reduce((n, f) => n + f.removed, 0)}</Text>
              </Text>
              <Box flexDirection="row" columnGap={2}>
                <Box flexDirection="column" width="50%">
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
                </Box>
                <Box flexDirection="column" width="50%">
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
                          {c.hash.slice(0, 7)} · {duration(now - c.at)} ago · {c.isPushed ? 'pushed' : 'local'}
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
              </Box>
            </Box>
          ))}
        </Box>
      </Box>
    )
  })
}
