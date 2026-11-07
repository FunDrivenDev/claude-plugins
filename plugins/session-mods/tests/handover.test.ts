import { expect, test } from 'claude-code/testing'

import { handoverOf, type StateRun } from '../hooks/handover'

/** A runner answering `stdout` with `exitCode`, recording the sessions it was asked about. */
const runner = (exitCode: number, stdout: string, asked: string[] = []): StateRun => async sid => {
  asked.push(sid)
  return { exitCode, stdout }
}

const STATE = {
  on: true,
  phase: 'winding_down',
  wound_down: true,
  writing: true,
  error: 'the writer timed out',
  written: { path: '/h/written.md', title: 'panel corner', lines: 42, modified_at: 1_700_000_000 },
  loaded: { path: '/h/loaded.md', title: null, lines: null, modified_at: null },
  thresholds: { suggest: 150_000, warn_at: 180_000, trigger: 200_000 },
  thresholds_error: null,
  pending: { trigger: 120_000 },
  resume: 'Resume the pane: open the PR.',
}

test('the handover plugin\'s state renders as it gives it', async () => {
  const asked: string[] = []
  expect(await handoverOf(runner(0, JSON.stringify(STATE), asked), 's1')).toEqual({
    isOn: true,
    unknown: null,
    loaded: { path: '/h/loaded.md', title: null, lines: null, modifiedAt: null },
    written: { path: '/h/written.md', title: 'panel corner', lines: 42, modifiedAt: 1_700_000_000_000 },
    thresholds: { suggest: 150_000, warnAt: 180_000, trigger: 200_000 },
    thresholdsError: null,
    pending: { trigger: 120_000 },
    isWriting: true,
    isWindingDown: true,
    error: 'the writer timed out',
    resume: 'Resume the pane: open the PR.',
  })
  expect(asked).toEqual(['s1'])
})

test('a session the plugin does not run in is off', async () => {
  const ho = await handoverOf(runner(0, JSON.stringify({ ...STATE, on: false })), 's1')
  expect(ho.isOn).toBe(false)
  expect(ho.unknown).toBeNull()
})

test('thresholds the plugin cannot give carry its reason, and no pending ones', async () => {
  const ho = await handoverOf(runner(0, JSON.stringify({ ...STATE, thresholds: null, thresholds_error: 'older than 0.20.0' })), 's1')
  expect([ho.thresholds, ho.thresholdsError, ho.pending]).toEqual([null, 'older than 0.20.0', null])
  const bare = await handoverOf(runner(0, '{"on": true}'), 's1')
  expect(bare.thresholdsError).toBe('the handover state gives no thresholds')
  expect([bare.written, bare.loaded, bare.resume, bare.isWriting, bare.isWindingDown]).toEqual([null, null, null, false, false])
})

test('without an answer, the handover section is unknown, never a crash', async () => {
  const cases: [StateRun, RegExp][] = [
    [runner(3, ''), /not installed/],
    // A plugin older than the command: argparse refuses `state`.
    [runner(2, ''), /older than 0\.29\.0/],
    [runner(0, 'not json'), /no JSON/],
    [runner(0, '[1, 2]'), /no JSON/],
    [async () => Promise.reject(new Error('spawn failed')), /did not run: Error: spawn failed/],
  ]
  for (const [run, why] of cases) {
    const ho = await handoverOf(run, 's1')
    expect(ho.unknown).toMatch(why)
    expect([ho.isOn, ho.written, ho.thresholds, ho.isWriting]).toEqual([true, null, null, false])
  }
})
