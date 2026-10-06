export type Ttl = '5m' | '1h'

export type Info = {
  model: string | null
  effort: string | null
  firstPrompt: string | null
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

export type Step = { id: string; label: string; isDone: boolean }

declare module 'claude-code' {
  interface PluginState {
    'session-panel': {
      info: Info
      agents: Agent[]
      steps: Step[]
      expanded: string | null
      stepsOpen: boolean
    }
  }
}
