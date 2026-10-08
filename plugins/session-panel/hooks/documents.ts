import type { Doc } from '../types'

export const ARTIFACTS = 'Artifacts'
export const HANDOVERS = 'Agent handovers'
export const PLANS = 'Plans'
/** The handover plugin's default `handover_dir`, and Claude Code's default `plansDirectory`. */
export const HANDOVER_DIR = '~/Notes/claude/agent-handovers'
export const PLANS_DIR = '~/.claude/plans'

/** Where documents are told apart, as real paths: `$HOME`, the temporary folders, the project's git folder, and the handover and plans folders. */
export type DocContext = { home: string; tmp: string[]; project: string | null; handovers: string; plans: string }

/** A file as read on disk: its real path, and the git folder of the repository it lies in (null outside one). */
export type Spot = { path: string; real: string; repo: string | null }

const titleOf = (folder: string): string => {
  const words = folder.replace(/[-_]+/g, ' ').trim()
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Documents'
}

const nameOf = (path: string): string => (path.split('/').pop() ?? path).replace(/\.md$/i, '')

/** `/Users/me/x` → `~/x`. */
export const tilde = (path: string, home: string): string => (home && path.startsWith(`${home}/`) ? `~${path.slice(home.length)}` : path)

/**
 * A Markdown file the agent wrote → the document it is, or null where it is
 * none: temporary, in a hidden folder, or part of the project's repository
 * (its git diff shows it). The handover and plans folders give their kind,
 * hidden or not; any other file takes its folder's name.
 */
export const docOf = (spot: Spot, ctx: DocContext): Doc | null => {
  if (!/\.md$/i.test(spot.real)) return null
  const under = (dir: string) => Boolean(dir) && spot.real.startsWith(`${dir}/`)
  const doc = (kind: string): Doc => ({ id: spot.real, path: spot.path, kind, name: nameOf(spot.real) })
  if (under(ctx.handovers)) return doc(HANDOVERS)
  if (under(ctx.plans)) return doc(PLANS)
  if (ctx.tmp.some(under)) return null
  if (ctx.project && spot.repo === ctx.project) return null
  const parts = spot.real.split('/').filter(Boolean)
  if (parts.some(part => part.startsWith('.'))) return null
  return doc(titleOf(parts[parts.length - 2] ?? ''))
}

/** The absolute Markdown paths a shell command names, `~` and `$HOME` expanded. */
export const docPaths = (command: string, home: string): string[] => {
  const found = new Set<string>()
  for (const token of command.split(/[\s'"<>|;&()=]+/)) {
    if (!/\.md$/i.test(token)) continue
    const path = token.replace(/^(~|\$HOME|\$\{HOME\})\//, `${home}/`)
    if (path.startsWith('/')) found.add(path)
  }
  return [...found]
}

/** An Artifact call that published a page → the artifact, by its claude.ai link; null for any other call. */
export const artifactOf = (input: Record<string, unknown>, result: unknown): Doc | null => {
  if ((input.action ?? 'publish') !== 'publish' || !result || typeof result !== 'object') return null
  const r = result as Record<string, unknown>
  if (typeof r.url !== 'string') return null
  const named = [r.title, input.title, typeof input.file_path === 'string' ? input.file_path.split('/').pop()?.replace(/\.[^.]+$/, '') : null]
  const name = named.find((n): n is string => typeof n === 'string' && n.trim() !== '') ?? r.url
  return { id: r.url, path: r.url, kind: ARTIFACTS, name }
}

/** Documents grouped by kind: artifacts, handovers and plans first, then the other folders as first written. */
export const docGroups = (docs: Doc[]): { kind: string; docs: Doc[] }[] => {
  const order = [ARTIFACTS, HANDOVERS, PLANS]
  const kinds = [...new Set(docs.map(d => d.kind))].sort((a, b) => {
    const ia = order.indexOf(a)
    const ib = order.indexOf(b)
    return (ia < 0 ? order.length : ia) - (ib < 0 ? order.length : ib)
  })
  return kinds.map(kind => ({ kind, docs: docs.filter(d => d.kind === kind) }))
}
