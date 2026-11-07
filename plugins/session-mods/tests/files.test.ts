import { expect, test } from 'claude-code/testing'

import { changesOf, type GitRun, parseLog, parseNumstat, parseStatus, treeRows } from '../hooks/files'

test('git status and numstat read into changes', async () => {
  const kinds = parseStatus(' M src/a.ts\0?? src/new.ts\0 D old.md\0R  b.ts\0a.ts\0')
  expect([...kinds]).toEqual([
    ['src/a.ts', 'modified'],
    ['src/new.ts', 'added'],
    ['old.md', 'deleted'],
    ['b.ts', 'modified'],
  ])
  const counts = parseNumstat('3\t1\tsrc/a.ts\n-\t-\timg.png\n2\t0\tsrc/{x => y}/c.ts\n')
  expect(counts.get('src/a.ts')).toEqual({ added: 3, removed: 1 })
  expect(counts.get('img.png')).toEqual({ added: 0, removed: 0 })
  expect(counts.get('src/y/c.ts')).toEqual({ added: 2, removed: 0 })
})

test('changes draw as a tree, single-child directories folded', async () => {
  const file = (path: string) => ({ path, status: 'modified' as const, added: 1, removed: 0 })
  const rows = treeRows([file('plugins/panel/hooks/a.ts'), file('plugins/panel/hooks/b.ts'), file('README.md')])
  expect(rows.map(r => `${r.indent}${r.name}`)).toEqual([
    '├ plugins/panel/hooks/',
    '│ ├ a.ts',
    '│ └ b.ts',
    '└ README.md',
  ])
})

test('git log reads into commits, pushed unless the upstream lacks them, all unpushed without an upstream', () => {
  const out = 'aaa\x1f1700000000\x1fFirst\x1fBody line\n\x1e\nbbb\x1f1700000060\x1fSecond\x1f\x1e\n'
  expect(parseLog(out, new Set(['bbb']))).toEqual([
    { hash: 'aaa', subject: 'First', body: 'Body line', at: 1_700_000_000_000, isPushed: true },
    { hash: 'bbb', subject: 'Second', body: '', at: 1_700_000_060_000, isPushed: false },
  ])
  expect(parseLog(out, 'all').map(c => c.isPushed)).toEqual([false, false])
  expect(parseLog('', new Set())).toEqual([])
})

test('git log keeps a multi-line body and skips a stray record', () => {
  const out = 'ccc\x1f1700000000\x1fThird\x1fLine one\n\nLine two\n\n\x1e\nnoise\x1e'
  expect(parseLog(out, new Set())).toEqual([{ hash: 'ccc', subject: 'Third', body: 'Line one\n\nLine two', at: 1_700_000_000_000, isPushed: true }])
})

const ok = (stdout = '') => ({ exitCode: 0, stdout })
const failed = { exitCode: 128, stdout: '' }

/** A git that answers each subcommand from `answers`, and records the calls. */
const fakeGit = (answers: Record<string, { exitCode: number; stdout: string }>) => {
  const calls: string[][] = []
  const run: GitRun = async args => {
    calls.push(args)
    const key = args[0] === 'diff' && args[1] === '--no-index' ? 'untracked' : args[0]!
    return answers[key] ?? ok()
  }
  return { run, calls }
}

const LOG = 'aaa\x1f1700000000\x1fFirst\x1f\x1e'

test('changesOf reads files, counts and commits of one repository', async () => {
  const { run } = fakeGit({
    status: ok(' M a.ts\0?? new.ts\0'),
    diff: ok('3\t1\ta.ts\n'),
    untracked: ok('5\t0\tnew.ts\n'),
    log: ok(LOG),
    'rev-list': ok('aaa\n'),
    branch: ok('main\n'),
  })
  expect(await changesOf(run, '/r', 0)).toEqual({
    root: '/r',
    branch: 'main',
    files: [
      { path: 'a.ts', status: 'modified', added: 3, removed: 1 },
      { path: 'new.ts', status: 'added', added: 5, removed: 0 },
    ],
    commits: [{ hash: 'aaa', subject: 'First', body: '', at: 1_700_000_000_000, isPushed: false }],
  })
})

test('changesOf is null where git cannot read the repository, or it has no change', async () => {
  expect(await changesOf(fakeGit({ status: failed }).run, '/r', 0)).toBeNull()
  expect(await changesOf(fakeGit({ log: ok('') }).run, '/r', 0)).toBeNull()
})

test('changesOf without an upstream counts every commit unpushed, and names a detached HEAD', async () => {
  const repo = await changesOf(fakeGit({ log: ok(LOG), 'rev-list': failed, branch: ok('') }).run, '/r', 0)
  expect(repo?.branch).toBe('detached')
  expect(repo?.commits.map(c => c.isPushed)).toEqual([false])
})

test('changesOf shows the files when git log fails', async () => {
  const repo = await changesOf(fakeGit({ status: ok(' M a.ts\0'), log: failed }).run, '/r', 0)
  expect(repo?.commits).toEqual([])
  expect(repo?.files.map(f => f.path)).toEqual(['a.ts'])
})

test('changesOf counts the lines of at most 30 untracked files', async () => {
  const status = Array.from({ length: 32 }, (_, k) => `?? f${k}.ts`).join('\0')
  const { run, calls } = fakeGit({ status: ok(`${status}\0`), untracked: ok('1\t0\tx\n') })
  const repo = await changesOf(run, '/r', 0)
  expect(calls.filter(c => c[1] === '--no-index')).toHaveLength(30)
  expect(repo?.files.filter(f => f.added === 1)).toHaveLength(30)
  expect(repo?.files).toHaveLength(32)
})
