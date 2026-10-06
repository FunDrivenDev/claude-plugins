import { expect, test } from 'claude-code/testing'

import { noteGroups, noteOf, notePaths } from '../hooks/notes'

const root = { home: '/Users/me', real: '/Users/me/Code/notes/personal' }

test('a file under ~/Notes, through its link or not, is a note of its inbox or folder', () => {
  expect(noteOf('/Users/me/Notes/claude/reports/26-10-06-ci-ok-wrap-up.md', root)).toEqual({
    path: '/Users/me/Notes/claude/reports/26-10-06-ci-ok-wrap-up.md',
    rel: 'claude/reports/26-10-06-ci-ok-wrap-up.md',
    kind: 'Reports',
    name: '26-10-06-ci-ok-wrap-up',
  })
  expect(noteOf('/Users/me/Code/notes/personal/claude/agent-handovers/x.md', root)?.kind).toBe('Agent handovers')
  expect(noteOf('/Users/me/Notes/voice-ideas/idea.md', root)?.kind).toBe('Voice ideas')
  expect(noteOf('/Users/me/Code/repo/README.md', root)).toBeNull()
})

test('a command names its notes with ~ and $HOME expanded', () => {
  expect(notePaths('cat > ~/Notes/claude/plans/a.md <<EOF\nx\nEOF', root)).toEqual(['/Users/me/Notes/claude/plans/a.md'])
  expect(notePaths('sed -i "" s/x/y/ "$HOME/Notes/claude/reports/b.md"; ls ~/Code', root)).toEqual(['/Users/me/Notes/claude/reports/b.md'])
  expect(notePaths('mkdir -p ~/Notes/', root)).toEqual([])
})

test('notes group by kind, the inboxes first', () => {
  const groups = noteGroups(
    ['/Users/me/Notes/knowledge/k.md', '/Users/me/Notes/claude/plans/p.md', '/Users/me/Notes/claude/reports/r.md'].map(p => noteOf(p, root)!),
  )
  expect(groups.map(g => g.kind)).toEqual(['Reports', 'Plans', 'Knowledge'])
})
