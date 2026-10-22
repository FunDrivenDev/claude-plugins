export type Ttl = '5m' | '1h'

export type Info = {
  model: string | null
  effort: string | null
  lastRequestAt: number | null
  ttl: Ttl | null
}

export type Picker = 'model' | 'effort' | null

export type Quota = {
  label: string
  used: number
  /** Share of the window elapsed, 0 to 1; null while the reset time is unknown. */
  elapsed: number | null
  /** Where the average burn lands at the reset, or when the limit runs out. */
  verdict: { text: string; tone: 'ok' | 'tight' | 'out' } | null
  /** Milliseconds until the window resets. */
  resetsIn: number | null
}

declare module 'claude-code' {
  interface PluginState {
    'session-bar': { info: Info; picking: Picker; quotasOpen: boolean }
  }
}
