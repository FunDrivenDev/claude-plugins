import type { Handover, HandoverFile, HandoverThresholds } from '../types'

/** Runs the installed handover plugin's `state` command for a session. */
export type StateRun = (sid: string) => Promise<{ exitCode: number; stdout: string; stderr?: string }>

/** The exit code of HANDOVER_STATE when no handover plugin is installed. */
const NOT_INSTALLED = 3

/**
 * Runs `handover.py state --session <sid> --json` from where Claude Code installed the handover plugin, under the
 * marketplace's name or its former one (`$1`: the session id). The plugin derives its data folder from that path:
 * a CLAUDE_PLUGIN_DATA in the environment would be another plugin's.
 */
export const HANDOVER_STATE = `f="\${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/installed_plugins.json"
p=$(python3 -c 'import json, sys
plugins = json.load(open(sys.argv[1])).get("plugins") or {}
for k in ("handover@fundrivendev", "handover@fundriven"):
    if plugins.get(k):
        print(plugins[k][0]["installPath"])
        break' "$f" 2>/dev/null)
test -n "$p" || exit ${NOT_INSTALLED}
exec env -u CLAUDE_PLUGIN_DATA python3 "$p/scripts/handover.py" state --session "$1" --json`

/** The handover section when the handover plugin gives no state: `why`, shown in place of the section. */
export const unknownHandover = (why: string): Handover => ({
  isOn: true,
  unknown: why,
  loaded: null,
  written: null,
  thresholds: null,
  thresholdsError: why,
  pending: null,
  isWriting: false,
  isWindingDown: false,
  error: null,
  resume: null,
})

const num = (n: unknown): number | null => (typeof n === 'number' && Number.isFinite(n) ? n : null)
const text = (s: unknown): string | null => (typeof s === 'string' && s ? s : null)
const record = (v: unknown): Record<string, unknown> | null => (typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : null)

/** A handover document as the state gives it, its last change in epoch seconds. */
const fileOf = (v: unknown): HandoverFile | null => {
  const f = record(v)
  if (!f || !text(f.path)) return null
  const at = num(f.modified_at)
  return { path: f.path as string, title: text(f.title), lines: num(f.lines), modifiedAt: at === null ? null : at * 1000 }
}

const thresholdsOf = (v: unknown): HandoverThresholds | null => {
  const t = record(v)
  const [suggest, warnAt, trigger] = [num(t?.suggest), num(t?.warn_at), num(t?.trigger)]
  return suggest === null || warnAt === null || trigger === null ? null : { suggest, warnAt, trigger }
}

const pendingOf = (v: unknown): Partial<HandoverThresholds> | null => {
  const p = record(v)
  const pending: Partial<HandoverThresholds> = {}
  for (const name of ['suggest', 'trigger'] as const) {
    const n = num(p?.[name])
    if (n !== null) pending[name] = n
  }
  return Object.keys(pending).length ? pending : null
}

/** The handover section of session `sid`, from the handover plugin's own answer; unknown, with why, without one. */
export async function handoverOf(run: StateRun, sid: string): Promise<Handover> {
  const out = await run(sid).catch((e: unknown) => ({ exitCode: -1, stdout: '', failure: String(e) }))
  if ('failure' in out) return unknownHandover(`the handover state command did not run: ${out.failure}`)
  if (out.exitCode === NOT_INSTALLED) return unknownHandover('the handover plugin is not installed')
  if (out.exitCode !== 0) {
    const stderr = out.stderr ?? ''
    // argparse refuses a command it does not know: the installed plugin predates `state`.
    if (/invalid choice: 'state'/.test(stderr)) return unknownHandover('the installed handover plugin predates its state command: it is older than 0.29.0')
    const last = stderr.trim().split('\n').pop()?.trim()
    return unknownHandover(`the handover state command failed (exit ${out.exitCode})${last ? `: ${last.slice(0, 200)}` : ''}`)
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(out.stdout)
  } catch {
    parsed = null
  }
  const st = record(parsed)
  if (!st) return unknownHandover('the handover plugin answered no JSON state')
  const thresholds = thresholdsOf(st.thresholds)
  return {
    isOn: st.on === true,
    unknown: null,
    loaded: fileOf(st.loaded),
    written: fileOf(st.written),
    thresholds,
    thresholdsError: thresholds ? null : (text(st.thresholds_error) ?? 'the handover state gives no thresholds'),
    pending: thresholds && pendingOf(st.pending),
    isWriting: st.writing === true,
    isWindingDown: st.wound_down === true,
    error: text(st.error),
    resume: text(st.resume),
  }
}
