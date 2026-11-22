import { expect, test } from 'claude-code/testing'

import {
  frontMatterOf,
  fromNotes,
  isTopic,
  mergePlanOf,
  notesOf,
  notesPathsIn,
  prLiveOf,
  proposedOf,
  questionsOf,
  rexSessionLabelled,
  rexSessionOf,
  staleOf,
  workerOf,
} from '../hooks/situation'
import type { MergeRow, PrLive } from '../types'

const PLAN = `---
status: doing
kind: plan
topic: mise-lockfiles
---

# Merge plan: mise-lockfiles

Refreshed: 2026-11-16 (after the renovate-config worker).

| Wave | PR | Status | Note |
|---|---|---|---|
| 1 | [guest-environment#253](https://github.com/Guest-Suite/guest-environment/pull/253), [#131](https://github.com/Guest-Suite/competitive-analysis/pull/131) | 👤 | checks green: ready and merge (a) |
| 2 | [pdf-renderer#5](https://github.com/Guest-Suite/pdf-renderer/pull/5) | ⚠️ 👤 | Q1, [mise-lockfiles:D02](/r.md) lock mode |

(a) One line per PR.
`

const QUESTIONS = `---
status: todo
topic: mise-lockfiles
---

# Open questions: mise-lockfiles

## Q1 — pdf-renderer: lock mode in \`mise.toml\`?

Held PR: pdf-renderer#5.

## Q2 — Drop the sidecars?

**Decided** (Raphaël, 2026-11-16): keep them.
`

const REGISTER = `---
status: doing
kind: decision-register
topic: mise-lockfiles
---

- **D01** \`decided\` — Every mise config has its lockfiles versioned.
  Why: x.
- **D02** \`proposed\` — pdf-renderer sets \`locked = true\` in \`mise.toml\`.
  Why: y.
`

test("a proposed decision keeps its whole text and its Why: clause, without the By: and Src: that follow", () => {
  const long = 'Keep the `gh pr ready` guard as it is, read gh\'s stdout once per call and cache the verdict for the rest of the turn, so that a stacked PR\'s parent is only asked once.'
  const register = `- **D07** \`proposed\` — ${long}
  Why: one read of gh per turn keeps the guard fast. By: Claude, 2026-11-18. Src: brief § 1. Also in: —
- **D08** \`proposed\` — No why here.
- **D09** \`decided\` — Done.
  Why: z.
`
  expect(proposedOf(register)).toEqual([
    { id: 'D07', text: long, why: 'one read of gh per turn keeps the guard fast.' },
    { id: 'D08', text: 'No why here.', why: null },
  ])
  // A superseded entry's Why: never lands under the proposed entry above it; CRLF and a Why: without By: read too.
  const struck = '- **D09** `proposed` — New.\r\n- ~~**D10** `proposed` — old.~~ superseded by D11\r\n  Why: belongs to D10. By: C, x.\r\n- **D11** `proposed` — Newer.\r\n  Why: no author.\r\n'
  expect(proposedOf(struck)).toEqual([
    { id: 'D09', text: 'New.', why: null },
    { id: 'D11', text: 'Newer.', why: 'no author.' },
  ])
})

test('a topic slug is the only thing put in a pattern', () => {
  expect(isTopic('session-panel-journal')).toBe(true)
  expect(isTopic('BIM-4544')).toBe(true)
  expect(isTopic('a b')).toBe(false)
  expect(isTopic('x"; rm -rf ~')).toBe(false)
  expect(isTopic(null)).toBe(false)
  expect(isTopic('')).toBe(false)
})

test('the notes a topic names split by file, with their last change', () => {
  const out = `\x1e/n/plans/a-merge-plan.md\t1700000000\n${PLAN}\x1e/n/decisions-register/r.md\t\n${REGISTER}`
  const notes = notesOf(out)
  expect(notes.map(n => [n.path, n.modifiedAt])).toEqual([
    ['/n/plans/a-merge-plan.md', 1_700_000_000_000],
    ['/n/decisions-register/r.md', null],
  ])
  expect(notes[0]!.text).toBe(PLAN)
  expect(notesOf('')).toEqual([])
})

test('front matter reads its keys, quotes dropped; none without a leading block', () => {
  expect(frontMatterOf('---\ntopic: "x-y"\nstatus: todo\n---\n# T')).toEqual({ topic: 'x-y', status: 'todo' })
  expect(frontMatterOf('# no front matter\ntopic: x')).toEqual({})
})

test('a call names notes documents by ~, $HOME or an absolute path', () => {
  expect(notesPathsIn('cat ~/Notes/claude/plans/a.md "$HOME/Notes/claude/b.md" /Users/me/Notes/claude/reports/c.md')).toEqual([
    '~/Notes/claude/plans/a.md',
    '$HOME/Notes/claude/b.md',
    '/Users/me/Notes/claude/reports/c.md',
  ])
  expect(notesPathsIn('/Users/me/Code/repo/README.md')).toEqual([])
})

test('a merge plan reads its rows, pull requests linked, and its Refreshed line', () => {
  const plan = mergePlanOf(PLAN)!
  expect(plan.refreshed).toBe('2026-11-16 (after the renovate-config worker).')
  expect(plan.rows).toEqual([
    {
      wave: '1',
      status: '👤',
      note: 'checks green: ready and merge (a)',
      prs: [
        { label: 'guest-environment#253', url: 'https://github.com/Guest-Suite/guest-environment/pull/253', repo: 'Guest-Suite/guest-environment', number: 253 },
        { label: '#131', url: 'https://github.com/Guest-Suite/competitive-analysis/pull/131', repo: 'Guest-Suite/competitive-analysis', number: 131 },
      ],
    },
    {
      wave: '2',
      status: '⚠️ 👤',
      note: 'Q1, mise-lockfiles:D02 lock mode',
      prs: [{ label: 'pdf-renderer#5', url: 'https://github.com/Guest-Suite/pdf-renderer/pull/5', repo: 'Guest-Suite/pdf-renderer', number: 5 }],
    },
  ])
  expect(mergePlanOf('# Merge plan\n\nNo table yet.')).toBeNull()
})

test('open questions leave out those already decided; proposed decisions leave out the decided ones', () => {
  expect(questionsOf(QUESTIONS)).toEqual([{ id: 'Q1', title: 'pdf-renderer: lock mode in `mise.toml`?' }])
  expect(proposedOf(REGISTER)).toEqual([{ id: 'D02', text: 'pdf-renderer sets `locked = true` in `mise.toml`.', why: 'y.' }])
})

test('the notes give the latest open merge plan, the open questions of open plans, and the register', () => {
  const note = (path: string, text: string) => ({ path, modifiedAt: 5, text })
  const done = PLAN.replace('status: doing', 'status: done').replace('guest-environment#253', 'old#1')
  const found = fromNotes([
    note('/n/plans/26-11-16-x-merge-plan.md', PLAN),
    note('/n/plans/26-11-17-x-merge-plan.md', done),
    note('/n/plans/26-11-16-x-open-questions.md', QUESTIONS),
    note('/n/plans/26-11-15-x-open-questions.md', QUESTIONS.replace('status: todo', 'status: done')),
    note('/n/decisions-register/26-11-16-x.md', REGISTER),
  ])
  expect(found.mergePlan?.path).toBe('/n/plans/26-11-16-x-merge-plan.md')
  expect(found.mergePlan?.modifiedAt).toBe(5)
  expect(found.questions).toEqual([{ id: 'Q1', title: 'pdf-renderer: lock mode in `mise.toml`?' }])
  expect(found.proposed.map(d => d.id)).toEqual(['D02'])
  expect(found.register).toBe('/n/decisions-register/26-11-16-x.md')
  expect(fromNotes([])).toEqual({ mergePlan: null, questions: [], proposed: [], register: null })
})

test("factory's merge plan, titled for its topic, wins over an older notes one; a done one only when no other is open", () => {
  const note = (path: string, text: string) => ({ path, modifiedAt: 5, text })
  const factory = (id: string, state: string, created: string) =>
    PLAN.replace(/^---\n[\s\S]*?\n---/, `---\nid: ${id}\nkind: plan\ntitle: Merge plan: x\nstate: ${state}\ncreated: ${created}\n---`)
  const older = note('/n/plans/26-11-16-x-merge-plan.md', PLAN.replace('status: doing', 'status: done'))
  const open = note('/log/documents/2026/11/D-ZZZZ-merge-plan-x.md', factory('D-ZZZZ', 'doing', '2026-11-22T10:00:00.000Z'))
  const done = note('/log/documents/2026/11/D-AAAA-merge-plan-x.md', factory('D-AAAA', 'done', '2026-11-23T10:00:00.000Z'))
  expect(fromNotes([open, older, done]).mergePlan?.path).toBe(open.path)
  expect(fromNotes([older, done]).mergePlan?.path).toBe(done.path)
  const register = note(
    '/log/documents/registers/26-11-16-x.md',
    '---\nkind: decision-register\ntopic: x\n---\n\n- <a id="d15"></a> **D15** `proposed` — Pin it.\n  Why: y.\n- <a id="d16"></a> **D16** `approved` — Other.\n',
  )
  expect(fromNotes([register]).register).toBe(register.path)
  expect(fromNotes([register]).proposed).toEqual([{ id: 'D15', text: 'Pin it.', why: 'y.' }])
  const imported = note('/log/documents/2026/11/D-P3N6-x-merge-plan.md', factory('D-P3N6', 'doing', '2026-11-01T00:00:00.000Z').replace('title: Merge plan: x', 'title: x (merge plan)'))
  expect(fromNotes([imported]).mergePlan?.path).toBe(imported.path)
})

test('Rex answers its sessions, windows and their blocks; anything else reads as none', () => {
  const ls = JSON.stringify({
    session_id: 'session:1',
    label: 'session-panel-journal',
    windows: [
      { window_id: 'window:a', label: 'watch', focused_block_id: 'block:a', layers: [{ blocks: [{ block_id: 'block:a' }] }] },
      { window_id: 'window:b', label: 'work', focused_block_id: 'block:b', layers: [{ blocks: [{ block_id: 'block:b' }, { block_id: 'block:c' }] }] },
    ],
  })
  expect(rexSessionOf(ls)).toEqual({
    session_id: 'session:1',
    label: 'session-panel-journal',
    windows: [
      { id: 'window:a', label: 'watch', block: 'block:a', blocks: ['block:a'] },
      { id: 'window:b', label: 'work', block: 'block:b', blocks: ['block:b', 'block:c'] },
    ],
  })
  expect(rexSessionOf('error: no server')).toBeNull()
  expect(rexSessionLabelled(JSON.stringify({ sessions: [{ session_id: 's:1', label: 'a' }, { session_id: 's:2', label: 'b' }] }), 'b')).toBe('s:2')
  expect(rexSessionLabelled('{}', 'b')).toBeNull()
  expect(rexSessionLabelled('nope', 'b')).toBeNull()
})

test("a tab's foot tells a running, waiting, idle, done or blocked Claude session from a shell", () => {
  const claude = (body: string, foot: string) => `⏺ Reading the diff.\n${body}\n❯ \n────\n  ${foot}\n  ⌛ running 2m`
  expect(workerOf('review', claude('', '⏵⏵ bypass permissions on · esc to interrupt'))).toEqual({ label: 'review', state: 'running', last: 'Reading the diff.' })
  expect(workerOf('fix', claude(' Do you want to proceed?\n ❯ 1. Yes', 'Esc to cancel')).state).toBe('waiting')
  expect(workerOf('fix', claude('⏺ All set.', '? for shortcuts'))).toEqual({ label: 'fix', state: 'idle', last: 'All set.' })
  expect(workerOf('w', claude('⏺ AFK done: https://github.com/o/r/pull/9, merged', '? for shortcuts'))).toEqual({ label: 'w', state: 'done', last: 'AFK done: https://github.com/o/r/pull/9, merged' })
  expect(workerOf('w', claude('⏺ AFK blocked: which name?', '? for shortcuts')).state).toBe('blocked')
  expect(workerOf('logs', '$ tail -f x.log\nline 1\nline 2\n')).toEqual({ label: 'logs', state: 'shell', last: 'line 2' })
  expect(workerOf('empty', '')).toEqual({ label: 'empty', state: 'shell', last: null })
})

test("a pull request's live state and red checks, from gh's cut answer", () => {
  expect(prLiveOf('{"state":"OPEN","isDraft":true,"red":0}')).toEqual({ state: 'draft', isRed: false })
  expect(prLiveOf('{"state":"OPEN","isDraft":false,"red":2}')).toEqual({ state: 'open', isRed: true })
  expect(prLiveOf('{"state":"MERGED","isDraft":false,"red":0}')).toEqual({ state: 'merged', isRed: false })
  expect(prLiveOf('{"state":"CLOSED"}')).toEqual({ state: 'closed', isRed: false })
  expect(prLiveOf('')).toBeNull()
  expect(prLiveOf('{"message":"Not Found"}')).toBeNull()
})

test("a merge-plan row is stale when its status emoji disagrees with gh's live state", () => {
  const A = 'https://github.com/o/r/pull/1'
  const B = 'https://github.com/o/r/pull/2'
  const row = (status: string, ...urls: string[]): MergeRow => ({ wave: '1', status, note: '', prs: urls.map((url, i) => ({ label: `r#${i + 1}`, url, repo: 'o/r', number: i + 1 })) })
  const gh = (a: PrLive['state'], b?: PrLive['state'], isRed = false): Record<string, PrLive> => ({ [A]: { state: a, isRed }, ...(b ? { [B]: { state: b, isRed } } : {}) })

  // ✅: stale while a PR is open (draft too) or closed unmerged.
  expect(staleOf(row('✅', A, B), gh('merged', 'merged'))).toBeNull()
  expect(staleOf(row('✅', A, B), gh('merged', 'open'))).toBe('stale: open')
  expect(staleOf(row('✅', A), gh('draft'))).toBe('stale: open')
  expect(staleOf(row('✅', A, B), gh('merged', 'closed'))).toBe('stale: closed')

  // 🔧, ⏳, 👤, ⚠️: stale once every PR is merged or closed.
  for (const status of ['🔧', '⏳', '👤', '⚠️', '🔧 👤', '🔧 ⚠️']) {
    expect(staleOf(row(status, A, B), gh('merged', 'open'))).toBeNull()
    expect(staleOf(row(status, A, B), gh('draft', 'draft'))).toBeNull()
    expect(staleOf(row(status, A, B), gh('merged', 'merged'))).toBe('stale: merged')
    expect(staleOf(row(status, A, B), gh('merged', 'closed'))).toBe('stale: merged')
    expect(staleOf(row(status, A), gh('closed'))).toBe('stale: closed')
  }

  // ⚠️ with green checks: gh's answer does not tell a conflict, so the row stays fresh.
  expect(staleOf(row('⚠️', A), gh('open', undefined, false))).toBeNull()
  expect(staleOf(row('⚠', A), gh('open', undefined, true))).toBeNull()

  // 🗑️: stale once its PR merged (it was to close), or closed (the row goes then).
  expect(staleOf(row('🗑️', A), gh('open'))).toBeNull()
  expect(staleOf(row('🗑️', A), gh('merged'))).toBe('stale: merged')
  expect(staleOf(row('🗑️', A), gh('closed'))).toBe('stale: closed')

  // ❓, no PR, or a PR gh could not read: never stale.
  expect(staleOf(row('❓', A), gh('merged'))).toBeNull()
  expect(staleOf(row('✅'), {})).toBeNull()
  expect(staleOf(row('✅', A, B), gh('open'))).toBeNull()
  expect(staleOf(row('🔧', A), {})).toBeNull()
})
