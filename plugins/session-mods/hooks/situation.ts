import type { MergePlan, MergeRow, PrLive, Proposed, Question, SituationPr, Worker } from '../types'

/** Runs a command, as `$.process.run` does. */
export type Run = (argv: string[]) => Promise<{ exitCode: number; stdout: string; stderr?: string }>

/** Where the notes live: the topic's plans and its decision register. */
export const NOTES_DIR = '~/Notes/claude'

/** A topic slug as the notes write it; anything else is never put in a pattern. */
export const isTopic = (s: string | null | undefined): s is string => typeof s === 'string' && /^[A-Za-z0-9][\w.-]{0,79}$/.test(s)

/**
 * Prints each plan and register whose front matter names topic `$1`: a `\x1e` line holding its path, a tab and its
 * last change (epoch seconds), then the file. Exits 1 when none does.
 */
export const TOPIC_NOTES = `d="$HOME/Notes/claude"; found=1; t=$(printf '%s' "$1" | sed 's/[.]/[.]/g')
for f in "$d"/plans/*.md "$d"/decisions-register/*.md; do
  [ -f "$f" ] || continue
  head -20 "$f" | grep -qxE "topic: *[\\"']?$t[\\"']? *" || continue
  printf '\\036%s\\t%s\\n' "$f" "$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f")"; cat "$f"; found=0
done
exit $found`

/** Prints the head of notes document `$1`, its front matter: a leading `~/` or a literal `$HOME/` stands for `$HOME/`. */
export const NOTE_HEAD = `case $1 in "~/"*) set -- "$HOME/\${1#??}";; '$HOME/'*) set -- "$HOME/\${1#??????}";; esac; head -20 "$1"`

export type Note = { path: string; modifiedAt: number | null; text: string }

/** TOPIC_NOTES's output → one note per file. */
export const notesOf = (stdout: string): Note[] =>
  stdout
    .split('\x1e')
    .slice(1)
    .map(chunk => {
      const nl = chunk.indexOf('\n')
      const [path = '', at = ''] = (nl < 0 ? chunk : chunk.slice(0, nl)).split('\t')
      const seconds = Number(at)
      return { path, modifiedAt: at && Number.isFinite(seconds) ? seconds * 1000 : null, text: nl < 0 ? '' : chunk.slice(nl + 1) }
    })
    .filter(n => n.path)

/** The leading `---` block's `key: value` lines, quotes dropped. */
export const frontMatterOf = (text: string): Record<string, string> => {
  const m = /^---\n([\s\S]*?)\n---/.exec(text)
  const out: Record<string, string> = {}
  for (const line of m?.[1]?.split('\n') ?? []) {
    const kv = /^([\w-]+):\s*(.*)$/.exec(line)
    if (kv) out[kv[1]!] = kv[2]!.trim().replace(/^["']|["']$/g, '')
  }
  return out
}

const NOTES_PATH = /(?:~|\$HOME|\/Users\/[^/\s]+|\/home\/[^/\s]+)\/Notes\/claude\/[^\s'"`)]+\.md/g

/** The notes documents a path or a command names, in order, `~` and `$HOME` kept as written. */
export const notesPathsIn = (text: string): string[] => text.match(NOTES_PATH) ?? []

const PR_LINK = /\[([^\]]+)\]\((https:\/\/github\.com\/([\w.-]+\/[\w.-]+)\/pull\/(\d+))[^)]*\)/g

const prsIn = (cell: string): SituationPr[] =>
  [...cell.matchAll(PR_LINK)].map(m => ({ label: m[1]!, url: m[2]!, repo: m[3]!, number: Number(m[4]) }))

const cells = (line: string) => line.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim())

/** A merge plan's table (`| Wave | PR | Status | Note |`), one row per line; null when the text holds none. */
export const mergePlanOf = (text: string): Omit<MergePlan, 'path' | 'modifiedAt'> | null => {
  const lines = text.split('\n')
  const head = lines.findIndex(l => /^\s*\|/.test(l) && /\bWave\b/i.test(l) && /\bPR\b/.test(l))
  if (head < 0) return null
  const names = cells(lines[head]!).map(c => c.toLowerCase())
  const at = (name: string) => names.findIndex(n => n.startsWith(name))
  const [wave, pr, status, note] = [at('wave'), at('pr'), at('status'), at('note')]
  const rows: MergeRow[] = []
  for (const line of lines.slice(head + 1)) {
    if (!/^\s*\|/.test(line)) break
    const c = cells(line)
    if (c.every(x => /^:?-+:?$/.test(x))) continue
    rows.push({ wave: c[wave] ?? '', prs: prsIn(c[pr] ?? ''), status: c[status] ?? '', note: (c[note] ?? '').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1') })
  }
  const refreshed = /^Refreshed:\s*(.+)$/m.exec(text)?.[1]?.trim() ?? null
  return { refreshed, rows }
}

/** An open-questions plan's `## Qn — title` headings, without those its `**Decided**` line answers. */
export const questionsOf = (text: string): Question[] =>
  text
    .split(/^(?=## )/m)
    .flatMap(part => {
      const m = /^## (Q\d+)\s*[—–:-]\s*(.+)$/m.exec(part)
      return m && !/\*\*Decided\*\*/.test(part) ? [{ id: m[1]!, title: m[2]!.trim() }] : []
    })

/** A decision register's entries still `proposed`: the ones awaiting Raphaël, each with its `Why:` clause. */
export const proposedOf = (text: string): Proposed[] =>
  text.split(/^(?=- \*\*D\d+\*\*)/m).flatMap(entry => {
    const m = /^- \*\*(D\d+)\*\* `proposed` —\s*(.+)$/m.exec(entry)
    if (!m) return []
    const why = /^\s+Why:\s*(.+?)(?:\s+By:.*)?$/m.exec(entry)?.[1]?.trim() ?? null
    return [{ id: m[1]!, text: m[2]!.trim(), why }]
  })

const isOpen = (n: Note) => !/^(done|cancelled|canceled)$/i.test(frontMatterOf(n.text).status ?? '')
const byPath = (a: Note, b: Note) => a.path.localeCompare(b.path)

/** What the topic's notes say: its latest open merge plan, its open questions, its `proposed` decisions. */
export const fromNotes = (notes: Note[]) => {
  const plans = notes.filter(n => /-merge-plan\.md$/.test(n.path)).sort(byPath)
  const planNote = plans.filter(isOpen).at(-1) ?? plans.at(-1) ?? null
  const plan = planNote && mergePlanOf(planNote.text)
  const registers = notes.filter(n => frontMatterOf(n.text).kind === 'decision-register' || n.path.includes('/decisions-register/')).sort(byPath)
  return {
    mergePlan: planNote && plan ? { ...plan, path: planNote.path, modifiedAt: planNote.modifiedAt } : null,
    questions: notes.filter(n => /-open-questions\.md$/.test(n.path) && isOpen(n)).sort(byPath).flatMap(n => questionsOf(n.text)),
    proposed: registers.flatMap(n => proposedOf(n.text)),
    register: registers.at(-1)?.path ?? null,
  }
}

type RexWindow = { window_id?: string; label?: string; focused_block_id?: string; layers?: { blocks?: { block_id?: string }[] }[] }
export type RexSession = { session_id: string; label: string | null; windows: { id: string; label: string; block: string | null; blocks: string[] }[] }

/** `rex window ls -s <session> --json` → the session, its label and its windows; null when not JSON. */
export const rexSessionOf = (stdout: string): RexSession | null => {
  try {
    const j = JSON.parse(stdout) as { session_id?: string; label?: string; windows?: RexWindow[] }
    if (!j.session_id) return null
    return {
      session_id: j.session_id,
      label: j.label || null,
      windows: (j.windows ?? []).map(w => ({
        id: w.window_id ?? '',
        label: w.label ?? '',
        block: w.focused_block_id ?? null,
        blocks: (w.layers ?? []).flatMap(l => (l.blocks ?? []).map(b => b.block_id ?? '')).filter(Boolean),
      })),
    }
  } catch {
    return null
  }
}

/** `rex ls --json` → the id of the session labelled `label`, else null. */
export const rexSessionLabelled = (stdout: string, label: string): string | null => {
  try {
    const j = JSON.parse(stdout) as { sessions?: { session_id?: string; label?: string }[] }
    return j.sessions?.find(s => s.label === label)?.session_id ?? null
  } catch {
    return null
  }
}

/** What a tab shows at its foot: a Claude session running, waiting on a prompt, idle, done or blocked on its AFK line, else a shell. */
export const workerOf = (label: string, screen: string): Worker => {
  const lines = screen.split('\n').map(l => l.trimEnd())
  const tail = lines.slice(-12).join('\n')
  const said = lines.findLast(l => /^⏺ /.test(l))?.slice(2).trim() ?? null
  const afk = lines.slice(-60).findLast(l => /AFK (done|blocked):/.test(l))
  const isClaude = lines.some(l => /^❯/.test(l)) || said !== null
  const state: Worker['state'] = /esc to interrupt/.test(tail)
    ? 'running'
    : /Do you want to|Esc to cancel|Enter to confirm/.test(tail)
      ? 'waiting'
      : afk
        ? (/AFK blocked:/.test(afk) ? 'blocked' : 'done')
        : isClaude
          ? 'idle'
          : 'shell'
  const last = afk && (state === 'done' || state === 'blocked') ? afk.replace(/^.*?AFK/, 'AFK').trim() : isClaude ? said : (lines.findLast(l => l.trim()) ?? null)
  return { label, state, last: last?.trim() || null }
}

/** `gh pr view --json state,isDraft,statusCheckRollup` cut by PR_JQ → the PR's state and whether a check is red. */
export const PR_JQ = '{state,isDraft,red:([.statusCheckRollup[]?|(.conclusion // .state // "")|select(.=="FAILURE" or .=="ERROR" or .=="TIMED_OUT" or .=="CANCELLED")]|length)}'

export const prLiveOf = (stdout: string): PrLive | null => {
  try {
    const j = JSON.parse(stdout) as { state?: string; isDraft?: boolean; red?: number }
    const state = j.state === 'MERGED' ? 'merged' : j.state === 'CLOSED' ? 'closed' : j.isDraft ? 'draft' : j.state === 'OPEN' ? 'open' : null
    return state ? { state, isRed: (j.red ?? 0) > 0 } : null
  } catch {
    return null
  }
}

/** Each worker state's glyph and Catppuccin Frappé colour. */
export const WORKER_LOOK: Record<Worker['state'], { glyph: string; color: string; word: string }> = {
  running: { glyph: '●', color: '#a6d189', word: 'running' },
  waiting: { glyph: '◆', color: '#e5c890', word: 'waiting for you' },
  idle: { glyph: '○', color: '#a5adce', word: 'idle' },
  done: { glyph: '✓', color: '#8caaee', word: 'done' },
  blocked: { glyph: '✗', color: '#e78284', word: 'blocked' },
  shell: { glyph: '›', color: '#a5adce', word: 'shell' },
}

/** A merge plan older than this shows its age in yellow. */
export const STALE_MS = 60 * 60_000

/**
 * Why a merge-plan row's status disagrees with GitHub's live state of its pull requests (`stale: merged`), else null.
 * Never stale: a ❓ row, a row without pull requests, a row with one gh could not read. A ⚠️ row whose checks are
 * green is not stale either: gh's answer does not say whether it conflicts with its base.
 */
export const staleOf = (row: MergeRow, prs: Record<string, PrLive>): string | null => {
  const s = row.status
  if (s.includes('❓') || !row.prs.length) return null
  const live = row.prs.map(p => prs[p.url])
  if (live.some(l => !l)) return null
  const states = live.map(l => l!.state)
  const done = (st: PrLive['state']) => st === 'merged' || st === 'closed'
  if (s.includes('✅')) {
    if (states.some(st => st === 'open' || st === 'draft')) return 'stale: open'
    if (states.includes('closed')) return 'stale: closed'
  }
  if (/[🔧⏳👤⚠]/u.test(s) && states.every(done)) return states.includes('merged') ? 'stale: merged' : 'stale: closed'
  if (s.includes('🗑')) {
    if (states.includes('merged')) return 'stale: merged'
    if (states.every(st => st === 'closed')) return 'stale: closed'
  }
  return null
}
