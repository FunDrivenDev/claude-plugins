import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, ToolCallInput, ToolCallResult } from 'claude-code'

import type { Agent, Entry, FileChange, Info, Picker, RepoChanges, Step, Ttl } from '../types'

import { parseNumstat, parseStatus, treeRows } from './files'

const PANE = 'session-panel'
const TITLE = 'Session'
const HISTORY_CAP = 400
const STEPS_CAP = 300
/** Steps shown while the list is folded: the current action and the one before. */
const STEPS_SHOWN = 2

const info = atom({ plugin: 'session-panel', key: 'info' } as const, {
  model: null,
  effort: null,
  firstPrompt: null,
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
const EDITING_TOOLS = new Set(['Edit', 'MultiEdit', 'Write', 'NotebookEdit', 'Bash'])
const picking = atom({ plugin: 'session-panel', key: 'picking' } as const, null as Picker)

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
    if (files.length) next.push({ root, files })
  }
  await update($, changes, () => next)
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
    ticker = $.clock.every(1000, () => $.ui.invalidate('ui.render'))
    await trackRepo($, e.cwd)
    await refreshFiles($)

    if ((await read($, info)).firstPrompt === null) {
      const first = (await $.session.messages()).find(m => m.role === 'user' && m.text.trim())
      if (first) await update($, info, i => ({ ...i, firstPrompt: first.text.trim() }))
    }

    return next(e)
  })

  on('command.run', { command: 'session-panel' }, async $ => {
    await $.ui.open({ id: PANE, title: TITLE, focus: true })
    return { text: 'Session panel opened.' }
  })

  on('prompt.submit', async ($, e, next) => {
    if ((await read($, info)).firstPrompt === null && e.text.trim()) {
      await update($, info, i => ({ ...i, firstPrompt: e.text.trim() }))
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
    const stream = next(e)
    let item = await stream.next()
    while (!item.done) {
      const chunk = item.value
      if (chunk.kind === 'thinking') thinking.set(chunk.index, (thinking.get(chunk.index) ?? '') + chunk.text)
      if (chunk.kind === 'text') text.set(chunk.index, (text.get(chunk.index) ?? '') + chunk.text)
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
        describeCall(use.name, typeof use.input === 'object' && use.input !== null ? (use.input as Record<string, unknown>) : {}),
      )
      const label =
        (calls.length && calls.join(' · ')) || (thought && headline(thought)) || (said && headline(said)) || 'Answered'
      await update($, info, i => ({ ...i, lastRequestAt: now }))
      await update($, steps, list => list.map(s => (s.id === stepId ? { ...s, label, isDone: true } : s)))
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
    if (EDITING_TOOLS.has(String(e.tool))) {
      const ran = await next(e)
      const path = (e as unknown as { file_path?: unknown; notebook_path?: unknown }).file_path
      if (typeof path === 'string' && path.includes('/')) await trackRepo($, path.slice(0, path.lastIndexOf('/')) || '/')
      refresh?.cancel()
      refresh = $.clock.after(400, () => void refreshFiles($))
      if (agentId) await logCall($, agentId, e, ran)
      return ran
    }
    if (!agentId) return next(e)
    const ran = await next(e)
    await logCall($, agentId, e, ran)
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
    const { Box, Text, Button } = $.ui.resolve(e)
    const [now, i, all, done, open, isStepsOpen, picker, repos] = await Promise.all([
      $.clock.now(),
      read($, info),
      read($, agents),
      read($, steps),
      read($, expanded),
      read($, stepsOpen),
      read($, picking),
      read($, changes),
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
    const teammates = all.filter(a => a.isTeammate)
    const background = all.filter(a => a.isBackground && !a.isTeammate)
    const dedicated =
      teammates.length > 0
        ? `yes, ${teammates.length} teammate session${teammates.length > 1 ? 's' : ''}`
        : all.length === 0
          ? 'none yet'
          : background.length > 0
            ? `no, ${background.length} in background here`
            : 'no, they run inside this session'

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

    const shownSteps = isStepsOpen ? done : done.slice(-STEPS_SHOWN)
    const folded = done.length - shownSteps.length

    return (
      <Box flexDirection="column" paddingX={1}>
        <Box flexDirection="column" marginBottom={1}>
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
          <Text>
            <Text dimColor>sub-agent session </Text>
            {dedicated}
          </Text>
        </Box>

        {section('Prompt')}
        <Box marginBottom={1}>
          <Text wrap="wrap">{i.firstPrompt ? oneLine(i.firstPrompt, 360) : '—'}</Text>
        </Box>

        {section('Steps')}
        <Box flexDirection="column" marginBottom={1}>
          {done.length > STEPS_SHOWN ? (
            <Button
              key="steps"
              label={isStepsOpen ? `▾ fold ${done.length - STEPS_SHOWN} earlier steps` : `▸ ${folded} earlier steps`}
              plain
              dimColor
              onPress={() => update($, stepsOpen, cur => !cur)}
            />
          ) : (
            <Text dimColor>{done.length === 0 ? 'None yet.' : ' '}</Text>
          )}
          {shownSteps.map(s => (
            <Text dimColor={s.isDone} wrap="truncate-end">
              <Text color={s.isDone ? 'success' : 'warning'}>{s.isDone ? '✓ ' : '○ '}</Text>
              {s.label}
            </Text>
          ))}
          {Array.from({ length: Math.max(0, STEPS_SHOWN - shownSteps.length) }, () => (
            <Text> </Text>
          ))}
        </Box>

        <Box flexDirection="row" columnGap={2}>
          <Box flexDirection="column" width="50%">
            {section(`Running · ${running.length}`)}
            {running.length === 0 && <Text dimColor>No sub-agent running.</Text>}
            {running.map(a => card(a, false))}
          </Box>
          <Box flexDirection="column" width="50%">
            <Text bold dimColor>
              Done · {finished.length}
            </Text>
            {finished.length === 0 && <Text dimColor>—</Text>}
            {[...finished].reverse().map(a => card(a, true))}
          </Box>
        </Box>
        <Box flexDirection="column" marginTop={1}>
          {section('Files')}
          {repos.length === 0 && <Text dimColor>No change.</Text>}
          {repos.map(repo => (
            <Box key={repo.root} flexDirection="column">
              <Text dimColor>
                {repo.root.split('/').pop()}{' '}
                <Text color="#a6d189">+{repo.files.reduce((n, f) => n + f.added, 0)}</Text>{' '}
                <Text color="#e78284">−{repo.files.reduce((n, f) => n + f.removed, 0)}</Text>
              </Text>
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
          ))}
        </Box>
      </Box>
    )
  })
}
