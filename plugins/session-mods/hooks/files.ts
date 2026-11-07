import type { Commit, FileChange, RepoChanges } from '../types'

const UNTRACKED_COUNTED = 30
const COMMITS_SHOWN = 8

/** Runs git in one repository, its arguments after `git -C <root>`. */
export type GitRun = (args: string[]) => Promise<{ exitCode: number; stdout: string }>

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

/** The `git log` format `parseLog` reads: hash, time, subject and body, unit-separated. */
export const LOG_FORMAT = '%H%x1f%ct%x1f%s%x1f%b%x1e'

/** `git log --format=LOG_FORMAT` → commits, pushed unless `unpushed` holds them. */
export const parseLog = (out: string, unpushed: ReadonlySet<string> | 'all'): Commit[] =>
  out
    .split('\x1e')
    .map(record => record.replace(/^\n/, ''))
    .filter(record => record.includes('\x1f'))
    .map(record => {
      const [hash = '', at = '0', subject = '', body = ''] = record.split('\x1f')
      return { hash, subject, body: body.trim(), at: Number(at) * 1000, isPushed: unpushed !== 'all' && !unpushed.has(hash) }
    })

/** One repository's changes against HEAD, untracked files included; null when git cannot read it or it has none. */
export async function changesOf(run: GitRun, root: string, since: number): Promise<RepoChanges | null> {
  const git = (...args: string[]) => run(args)
  const status = await git('status', '--porcelain=v1', '-z', '--untracked-files=all')
  if (status.exitCode !== 0) return null
  const kinds = parseStatus(status.stdout)
  // Independent reads, run side by side rather than one after another.
  const [numstat, log, ahead, current] = await Promise.all([
    git('diff', '--numstat', 'HEAD'),
    git('log', `-n${COMMITS_SHOWN}`, `--since=@${since}`, `--format=${LOG_FORMAT}`),
    git('rev-list', '@{u}..HEAD'),
    git('branch', '--show-current'),
  ])
  const counts = parseNumstat(numstat.stdout)
  let untracked = 0
  const files = await Promise.all(
    [...kinds].map(async ([path, kind]): Promise<FileChange> => {
      let count = counts.get(path)
      if (!count && kind === 'added' && untracked++ < UNTRACKED_COUNTED) {
        const diff = await git('diff', '--no-index', '--numstat', '/dev/null', path)
        count = [...parseNumstat(diff.stdout).values()][0]
      }
      return { path, status: kind, added: count?.added ?? 0, removed: count?.removed ?? 0 }
    }),
  )
  const unpushed = ahead.exitCode === 0 ? new Set(ahead.stdout.split('\n').filter(Boolean)) : ('all' as const)
  const commits = log.exitCode === 0 ? parseLog(log.stdout, unpushed) : []
  const branch = current.stdout.trim() || 'detached'
  return files.length || commits.length ? { root, branch, files, commits } : null
}
