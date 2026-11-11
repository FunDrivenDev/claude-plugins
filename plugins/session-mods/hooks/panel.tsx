import type { FileChange, Handover, Prompt, Step } from '../types'

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

export const oneLine = (text: string, max = 160): string => {
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

export const SIGN: Record<FileChange['status'], string> = { added: '+', modified: '~', deleted: '−' }
export const SIGN_COLOR: Record<FileChange['status'], string> = { added: '#a6d189', modified: '#e5c890', deleted: '#e78284' }

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

/** The hint beside Last prompt, `11 previous prompts`: how many came before it. */
export const previousPrompts = (n: number): string =>
  n <= 0 ? 'no previous prompt' : `${n} previous ${n === 1 ? 'prompt' : 'prompts'}`

/** When a prompt was submitted, `09:05` in local 24-hour time. */
export const clockTime = (at: number): string => {
  const d = new Date(at)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** A stored prompt; one kept by an earlier version is bare text, without its time. */
export const promptOf = (p: Prompt | string): Prompt => (typeof p === 'string' ? { text: p, at: null } : p)

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

export const kilo = (n: number) => (n < 1000 ? String(n) : n < 10_000 ? `${(n / 1000).toFixed(1)}k` : `${Math.floor(n / 1000)}k`)

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
export const NEXT_ACTIONS = [
  { key: 'handover:run', emoji: '🚀', label: 'Start with this prompt', color: '#a6d189', isSent: true },
  { key: 'handover:edit', emoji: '✏️', label: 'Edit the prompt first', color: '#8caaee', isSent: false },
] as const

/** The context has reached the wind-down trigger; false when it is off or unknown. */
export const isPastTrigger = (h: Handover, tokens: number) => Boolean(h.thresholds?.trigger) && tokens >= (h.thresholds?.trigger ?? 0)

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
export const PHASES: Record<HandoverPhase, { frames: readonly string[]; label: string; color: string; does: string }> = {
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
export const HELP_EXAMPLE = 34

/** Starts the handover's wind-down at once, as `/handover:trigger` does. */
export const TRIGGER_NOW = { key: 'handover:trigger', emoji: '⚡', label: 'Hand over now', color: '#e5c890' } as const
/** A title as given: its first line, without a label, quotes or a final period; null when empty. */
export const cleanTitle = (text: string): string | null => {
  const line = text.split('\n').map(l => l.trim()).find(Boolean)
  const title = line?.replace(/^title:\s*/i, '').replace(/^["'“«*`]+|["'”»*`.]+$/g, '').trim()
  return title ? oneLine(title, 80) : null
}
