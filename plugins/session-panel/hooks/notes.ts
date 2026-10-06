import type { Note, NotesRoot } from '../types'

/** The `~/Notes/claude` inboxes, in the order the pane lists them, by their folder. */
const KINDS: Record<string, string> = {
  reports: 'Reports',
  plans: 'Plans',
  handoffs: 'Handoffs',
  'agent-handovers': 'Agent handovers',
  'agent-handoffs': 'Agent handovers',
}

const titleOf = (folder: string): string => {
  const words = folder.replace(/[-_]+/g, ' ').trim()
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Notes'
}

/**
 * A file under the notes folder (`~/Notes` or the folder it links to) → its
 * kind and its name without `.md`; null elsewhere. The kind is its inbox under
 * `claude/` (`reports`, `agent-handovers`), else its top folder.
 */
export const noteOf = (path: string, root: NotesRoot): Note | null => {
  const base = [`${root.home}/Notes/`, root.real ? `${root.real}/` : null].find(prefix => prefix && path.startsWith(prefix))
  if (!base) return null
  const parts = path.slice(base.length).split('/').filter(Boolean)
  const file = parts.pop()
  if (!file) return null
  const folder = parts[0] === 'claude' && parts.length > 1 ? parts[1]! : (parts[0] ?? '')
  return { path, rel: [...parts, file].join('/'), kind: KINDS[folder] ?? titleOf(folder), name: file.replace(/\.md$/, '') }
}

/** The paths under `~/Notes` a shell command names, `~` and `$HOME` expanded. */
export const notePaths = (command: string, root: NotesRoot): string[] => {
  const prefixes = ['~/Notes/', '$HOME/Notes/', `\${HOME}/Notes/`, `${root.home}/Notes/`, ...(root.real ? [`${root.real}/`] : [])]
  const found = new Set<string>()
  for (const token of command.split(/[\s'"<>|;&()=]+/)) {
    const prefix = prefixes.find(p => token.startsWith(p))
    if (!prefix || token.length === prefix.length) continue
    found.add(token.replace(/^(~|\$HOME|\$\{HOME\})\//, `${root.home}/`))
  }
  return [...found]
}

/** Notes grouped by kind: the inboxes first, in their order, then the other folders as first written. */
export const noteGroups = (notes: Note[]): { kind: string; notes: Note[] }[] => {
  const order = [...new Set(Object.values(KINDS))]
  const kinds = [...new Set(notes.map(n => n.kind))].sort((a, b) => {
    const ia = order.indexOf(a)
    const ib = order.indexOf(b)
    return (ia < 0 ? order.length : ia) - (ib < 0 ? order.length : ib)
  })
  return kinds.map(kind => ({ kind, notes: notes.filter(n => n.kind === kind) }))
}
