export type Ttl = '5m' | '1h'

export type Info = {
  model: string | null
  effort: string | null
  lastRequestAt: number | null
  ttl: Ttl | null
}

export type Entry = { kind: 'think' | 'say' | 'tool' | 'result' | 'error'; text: string }

export type Agent = {
  id: string | null
  toolUseId: string
  description: string
  type: string
  prompt: string
  model: string | null
  isBackground: boolean
  isTeammate: boolean
  startedAt: number
  endedAt: number | null
  history: Entry[]
}

export type FileChange = {
  path: string
  status: 'added' | 'modified' | 'deleted'
  added: number
  removed: number
}

export type Commit = { hash: string; subject: string; body: string; at: number; isPushed: boolean }

export type RepoChanges = { root: string; branch: string; files: FileChange[]; commits: Commit[] }

export type Picker = 'model' | 'effort' | null

export type Step = {
  id: string
  /** What the step did, in the agent's own words (a Bash call's description). */
  label: string
  /** How: the command, path or pattern. */
  how?: string
  /** Why: the first sentence of the thinking before it. */
  why?: string
  toolIds?: string[]
  /** The calls of `toolIds` that have returned. */
  doneIds?: string[]
  /** The model's answer has streamed in full. */
  isDone: boolean
  /** Refused or failed calls, and the same action taken again. */
  flag?: 'refused' | 'failed' | 'repeat'
  note?: string
  repeats?: number
}

export type TrackedIssue = {
  platform: 'github' | 'linear'
  /** `owner/repo#N` or `KEY-N`. */
  key: string
  title: string | null
  url: string | null
  /** Linear's desktop link, opened instead of `url` where the app is installed. */
  appUrl: string | null
  rank: number
}

export type TrackedPr = {
  repo: string
  number: number
  title: string | null
  url: string
  state: 'draft' | 'open' | 'closed' | 'merged' | null
  rank: number
}

export type Tracker = {
  issue: TrackedIssue | null
  pr: TrackedPr | null
  /** Bare `KEY-N` identifiers the prompts named, matched once a Linear tool shows one. */
  mentioned: string[]
}

export type Handover = {
  /** The handover plugin runs in this session. */
  isOn: boolean
  /** The handover this session started from, and the one it wrote. */
  loaded: { path: string; title: string | null } | null
  written: { path: string; title: string | null } | null
  suggest: number
  trigger: number
  warn: number
  isWriting: boolean
  error: string | null
}

declare module 'claude-code' {
  interface PluginState {
    'session-panel': {
      info: Info
      agents: Agent[]
      steps: Step[]
      expanded: string | null
      stepsOpen: boolean
      picking: Picker
      prompts: string[]
      view: 'overview' | 'prompts'
      roots: string[]
      changes: RepoChanges[]
      tracker: Tracker
      home: string | null
      handover: Handover | null
    }
  }
}
