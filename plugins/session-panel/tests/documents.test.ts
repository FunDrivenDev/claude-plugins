import { expect, test } from 'claude-code/testing'

import { artifactOf, docGroups, docOf, docPaths } from '../hooks/documents'

const ctx = {
  home: '/Users/me',
  tmp: ['/private/tmp', '/private/var/folders/x/T'],
  project: '/Users/me/Code/repo/.git',
  handovers: '/Users/me/Code/notes/claude/agent-handovers',
  plans: '/Users/me/.claude/plans',
}
const at = (real: string, repo: string | null = null) => ({ path: real, real, repo })

test('a Markdown file the agent wrote is a document of its folder, unless temporary, hidden or in the project', () => {
  expect(docOf(at('/Users/me/Code/notes/claude/reports/26-10-06-wrap-up.md', '/Users/me/Code/notes/.git'), ctx)).toEqual({
    id: '/Users/me/Code/notes/claude/reports/26-10-06-wrap-up.md',
    path: '/Users/me/Code/notes/claude/reports/26-10-06-wrap-up.md',
    kind: 'Reports',
    name: '26-10-06-wrap-up',
  })
  expect(docOf(at('/Users/me/Code/notes/claude/agent-handovers/2026/10/07/09h32-panel.md'), ctx)).toMatchObject({ kind: 'Agent handovers', name: '09h32-panel' })
  expect(docOf(at('/Users/me/.claude/plans/quiet-river.md'), ctx)?.kind).toBe('Plans')
  expect(docOf(at('/Users/me/voice-ideas/idea.md'), ctx)?.kind).toBe('Voice ideas')
  expect(docOf(at('/Users/me/Code/repo/README.md', '/Users/me/Code/repo/.git'), ctx)).toBeNull()
  expect(docOf(at('/private/tmp/scratch.md'), ctx)).toBeNull()
  expect(docOf(at('/Users/me/.claude/jobs/1/tmp/x.md'), ctx)).toBeNull()
  expect(docOf(at('/Users/me/notes/x.txt'), ctx)).toBeNull()
})

test('a command names its Markdown files with ~ and $HOME expanded', () => {
  expect(docPaths('cat > ~/Notes/claude/plans/a.md <<EOF\nx\nEOF', '/Users/me')).toEqual(['/Users/me/Notes/claude/plans/a.md'])
  expect(docPaths('sed -i "" s/x/y/ "$HOME/Notes/b.md"; cat docs/c.md', '/Users/me')).toEqual(['/Users/me/Notes/b.md'])
})

test('a published artifact is a document by its link and title', () => {
  expect(artifactOf({ file_path: '/w/help.html' }, { url: 'https://claude.ai/artifact/1', path: '/w/help.html' })).toEqual({
    id: 'https://claude.ai/artifact/1',
    path: 'https://claude.ai/artifact/1',
    kind: 'Artifacts',
    name: 'help',
  })
  expect(artifactOf({ title: 'Panel help' }, { url: 'https://claude.ai/artifact/2', title: 'Panel guide' })?.name).toBe('Panel guide')
  expect(artifactOf({ action: 'list' }, { url: 'https://claude.ai/artifact/3' })).toBeNull()
})

test('documents group as artifacts, handovers and plans first, then the other folders', () => {
  const docs = ['/Users/me/k/x.md', '/Users/me/.claude/plans/p.md', '/Users/me/Code/notes/claude/agent-handovers/h.md'].map(p => docOf(at(p), ctx)!)
  const art = artifactOf({}, { url: 'https://claude.ai/artifact/1', title: 'A' })!
  expect(docGroups([...docs, art]).map(g => g.kind)).toEqual(['Artifacts', 'Agent handovers', 'Plans', 'K'])
})
