/**
 * Finds the tracker issue and the pull request a session is about, in the
 * prompts it was given and the commands it ran.
 */

/**
 * Where a reference was seen: the lower, the more it is the session's own. A
 * bare `#N` in a prompt (`#1, #2, #3` numbering a list) counts least.
 */
export const RANK = { prompt: 0, created: 1, worked: 2, mentioned: 3 } as const

/** `isBare` marks a `#N` written without its repository. */
export type GithubRef = { platform: 'github'; repo: string; number: number; type: 'issue' | 'pull' | null; isBare?: true }
export type LinearRef = { platform: 'linear'; id: string; workspace: string | null; slug: string | null }
export type Ref = GithubRef | LinearRef

const GITHUB_URL = /https:\/\/github\.com\/([\w.-]+\/[\w.-]+)\/(issues|pull)\/(\d+)/g
const GITHUB_SHORT = /(?<![\w/#])(?:([\w.-]+)\/)?([A-Za-z][\w.-]*)?#(\d+)\b/g
const LINEAR_URL = /https:\/\/linear\.app\/([\w-]+)\/issue\/([A-Z][A-Z0-9]+-\d+)(?:\/([\w-]+))?/g
/** The same, for the first match alone: `exec` on a non-global pattern keeps no state between calls. */
const LINEAR_URL_FIRST = new RegExp(LINEAR_URL.source)

/** `owner/repo` from a remote URL, ssh or https. */
export const repoOfRemote = (remote: string): string | null =>
  /github\.com[:/]([\w.-]+\/[\w.-]+?)(?:\.git)?\/?$/.exec(remote.trim())?.[1] ?? null

/**
 * The issues and pull requests a text names: GitHub and Linear URLs, and
 * `owner/repo#N`, `repo#N` or `#N` read against `home`, the session's repository.
 */
export const findRefs = (text: string, home: string | null): Ref[] => {
  const refs: Ref[] = []
  const add = (ref: Ref) => {
    if (!refs.some(r => refKey(r) === refKey(ref))) refs.push(ref)
  }
  const bare = text.replace(GITHUB_URL, (_, repo: string, kind: string, n: string) => {
    add({ platform: 'github', repo, number: Number(n), type: kind === 'pull' ? 'pull' : 'issue' })
    return ' '
  })
  for (const m of bare.matchAll(GITHUB_SHORT)) {
    const [, owner, name, n] = m
    const homeOwner = home?.split('/')[0]
    const repo = owner && name ? `${owner}/${name}` : name ? (homeOwner ? `${homeOwner}/${name}` : null) : home
    if (repo) add({ platform: 'github', repo, number: Number(n), type: null, ...(name ? {} : { isBare: true as const }) })
  }
  for (const m of text.matchAll(LINEAR_URL)) add({ platform: 'linear', workspace: m[1]!, id: m[2]!, slug: m[3] ?? null })
  return refs
}

export const refKey = (ref: Ref): string => (ref.platform === 'github' ? `${ref.repo}#${ref.number}` : ref.id)

/**
 * The references a `gh` command works on, `created` when it opened one: the
 * URL `gh issue create` or `gh pr create` prints, or the number or URL it names.
 */
export const refsOfGh = (
  command: string,
  output: string,
  home: string | null,
): { refs: Ref[]; rank: number } | null => {
  const m = /\bgh\s+(issue|pr)\s+([a-z-]+)(.*)/s.exec(command)
  if (!m) return null
  const [, noun, verb, rest] = m
  const type = noun === 'pr' ? 'pull' : 'issue'
  if (verb === 'create') {
    const refs = findRefs(output, home).filter(r => r.platform === 'github' && r.type === type)
    return { refs, rank: RANK.created }
  }
  if (verb === 'list' || verb === 'status') return null
  const repo = /(?:-R|--repo)[\s=]+([\w.-]+\/[\w.-]+)/.exec(rest!)?.[1] ?? home
  const target = /(?:^|\s)(\d+|https:\/\/github\.com\/\S+)(?=\s|$)/.exec(rest!.replace(/(?:-R|--repo)[\s=]+\S+/, ''))?.[1]
  if (!target) return { refs: [], rank: RANK.worked }
  if (/^\d+$/.test(target)) return repo ? { refs: [{ platform: 'github', repo, number: Number(target), type }], rank: RANK.worked } : null
  return { refs: findRefs(target, home), rank: RANK.worked }
}

/** A Linear issue an MCP result describes: its identifier, title and URL. */
export const linearOfResult = (text: string): { ref: LinearRef; title: string | null } | null => {
  const url = LINEAR_URL_FIRST.exec(text)
  if (!url) return null
  let title: string | null = null
  try {
    const data = JSON.parse(text) as { title?: unknown; identifier?: unknown }
    if (typeof data.title === 'string') title = data.title
  } catch {
    title = /"title"\s*:\s*"((?:[^"\\]|\\.)*)"/.exec(text)?.[1] ?? null
  }
  return { ref: { platform: 'linear', workspace: url[1]!, id: url[2]!, slug: url[3] ?? null }, title }
}

/** `fix-the-login-bug` → `Fix the login bug`. */
export const titleOfSlug = (slug: string | null): string | null =>
  slug ? slug.charAt(0).toUpperCase() + slug.slice(1).replace(/-/g, ' ') : null

/** GitHub's own colours for a pull request's state. */
export const PR_COLOR = { draft: '#babbf1', open: '#3fb950', closed: '#f85149', merged: '#a371f7' } as const

/** A pull request's state from the issues API: draft, open, closed or merged. */
export const prState = (data: { state?: string; draft?: boolean; merged?: boolean }): keyof typeof PR_COLOR =>
  data.merged ? 'merged' : data.state === 'closed' ? 'closed' : data.draft ? 'draft' : 'open'
