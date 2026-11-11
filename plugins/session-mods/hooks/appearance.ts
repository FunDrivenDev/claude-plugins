/**
 * How both mods look: the light twin of each colour they draw, and the names
 * they share. `register.tsx` reads the OS appearance they draw with.
 */

export type Scheme = 'dark' | 'light'

/**
 * Each colour the pane and the bar draw, as written for a dark background, with
 * its twin for a light one: Catppuccin Latte for Frappé; for GitHub's and
 * Linear's colours, the status line's bright grading and `/effort`'s colours,
 * the nearest tone that reads on white.
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
  '#3fb950': '#1a7f37',
  '#f85149': '#cf222e',
  '#a371f7': '#8250df',
  '#5e6ad2': '#4c55b8',
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

/** A mod's tree for the OS appearance: on a light one, every colour swapped for its twin (LIGHT). */
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
