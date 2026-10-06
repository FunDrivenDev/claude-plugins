import type { FileChange } from '../types'

/** `git status --porcelain=v1 -z` → each changed path and how it changed. */
export const parseStatus = (out: string): Map<string, FileChange['status']> => {
  const changes = new Map<string, FileChange['status']>()
  const parts = out.split('\0')
  for (let k = 0; k < parts.length; k++) {
    const entry = parts[k]!
    if (entry.length < 4) continue
    const xy = entry.slice(0, 2)
    const path = entry.slice(3)
    if (xy.includes('R') || xy.includes('C')) k++ // the source path follows
    changes.set(
      path,
      xy === '??' || xy.includes('A') ? 'added' : xy.includes('D') ? 'deleted' : 'modified',
    )
  }
  return changes
}

/** `git diff --numstat` → lines added and removed per path (binary: 0). */
export const parseNumstat = (out: string): Map<string, { added: number; removed: number }> => {
  const counts = new Map<string, { added: number; removed: number }>()
  for (const line of out.split('\n')) {
    const [added, removed, ...path] = line.split('\t')
    if (!path.length) continue
    const name = path.join('\t').replace(/^(.*)\{.* => (.*)\}(.*)$/, (_, pre, to, rest) => `${pre}${to}${rest}`)
    counts.set(name.includes(' => ') ? name.split(' => ')[1]! : name, {
      added: Number(added) || 0,
      removed: Number(removed) || 0,
    })
  }
  return counts
}

export type TreeRow = { indent: string; name: string; change?: FileChange }

/**
 * The changes as a tree following the hierarchy, a directory holding one
 * directory and nothing else folded into it (`src/hooks/`), as an IDE does.
 */
export const treeRows = (changes: readonly FileChange[]): TreeRow[] => {
  type Node = { dirs: Map<string, Node>; files: FileChange[] }
  const root: Node = { dirs: new Map(), files: [] }
  for (const change of changes) {
    const parts = change.path.split('/')
    let node = root
    for (const dir of parts.slice(0, -1)) {
      if (!node.dirs.has(dir)) node.dirs.set(dir, { dirs: new Map(), files: [] })
      node = node.dirs.get(dir)!
    }
    node.files.push(change)
  }

  const rows: TreeRow[] = []
  const walk = (node: Node, indent: string) => {
    const dirs = [...node.dirs.entries()].sort(([a], [b]) => a.localeCompare(b))
    const files = [...node.files].sort((a, b) => a.path.localeCompare(b.path))
    const count = dirs.length + files.length
    let index = 0
    for (const [name, child] of dirs) {
      let label = name
      let deep = child
      while (deep.files.length === 0 && deep.dirs.size === 1) {
        const [next, inner] = [...deep.dirs.entries()][0]!
        label += `/${next}`
        deep = inner
      }
      const isLast = ++index === count
      rows.push({ indent: indent + (isLast ? '└ ' : '├ '), name: `${label}/` })
      walk(deep, indent + (isLast ? '  ' : '│ '))
    }
    for (const file of files) {
      const isLast = ++index === count
      rows.push({ indent: indent + (isLast ? '└ ' : '├ '), name: file.path.split('/').pop()!, change: file })
    }
  }
  walk(root, '')
  return rows
}
