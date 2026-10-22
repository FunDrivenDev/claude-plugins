import { expect, test } from 'claude-code/testing'

import { parseNumstat, parseStatus, treeRows } from '../hooks/files'

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
