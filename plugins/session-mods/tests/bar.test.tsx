import { describe, expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

import { barRuns, cacheColor, contextOf, duration, effortColor, kfmt, minutesLeft, modelColor, modelId, prettyModel, quotaOf, recolor, span } from '../hooks/bar'

const BAR = {
  plugin: 'session-mods',
  component: 'PromptHint',
  props: { isDraft: false, isWorking: false, hint: '? for shortcuts' },
} as const

/** Stands for the engine's own hint line, which the bar draws above itself. */
const engineHint = (on: On) =>
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>? for shortcuts</Text>
  })

const ok = (stdout: string, stderr = '', exitCode = 0) => ({ value: { exitCode, stdout, stderr, isStdoutTruncated: false, isStderrTruncated: false } })

describe('helpers', () => {
  test('names models and durations calmly', () => {
    expect(prettyModel('claude-opus-5-5')).toBe('Opus 5.5')
    expect(prettyModel('claude-haiku-4-5-20251001')).toBe('Haiku 4.5')
    expect(duration(3_725_000)).toBe('1h02m')
    expect(duration(65_000)).toBe('1m05s')
    expect(modelColor('claude-opus-5-5[1m]')).toBe('#ef9f76')
    expect(effortColor('high')).toBe('#b1b9f9')
    expect(modelId('opus[1m]')).toBe('claude-opus-5-5')
    expect(modelId('claude-sonnet-5-5')).toBe('claude-sonnet-5-5')
    expect(minutesLeft(2_399_000)).toBe('39m')
    expect(minutesLeft(59_000)).toBe('<1m')
    expect([cacheColor(1_800_000, 3_600_000), cacheColor(720_000, 3_600_000), cacheColor(700_000, 3_600_000)]).toEqual(['#5fff00', '#ffff00', '#ffaf00'])
  })

  test('count the context against the auto-compact trigger, graded as the status line', () => {
    expect(kfmt(78_234)).toBe('78.2k')
    expect(kfmt(934)).toBe('934')
    const window = { limit: 167_000, window: 200_000 }
    expect(contextOf(undefined, window)).toEqual({ text: '0/167k (200k − 33k)', color: '#8a8a8a', isCompacting: false })
    expect(contextOf(78_234, window)).toEqual({ text: '78.2k/167k (200k − 33k) 46%', color: '#5fff00', isCompacting: false })
    expect(contextOf(100_000, window).color).toBe('#ffff00')
    expect(contextOf(140_000, window).color).toBe('#ffaf00')
    expect(contextOf(160_000, window).color).toBe('#ff0000')
    expect(contextOf(170_000, window)).toEqual({ text: '170.0k/167k (200k − 33k) 101% ⚠ compacting', color: '#ff0000', isCompacting: true })
    expect(contextOf(78_234, { limit: 200_000, window: 200_000 }).text).toBe('78.2k/200k 39%')
    const set = { limit: 217_000, window: 250_000 }
    expect(contextOf(108_000, set).color).toBe('#5fff00')
    expect(contextOf(109_000, set).color).toBe('#ffff00')
    expect(contextOf(163_000, set).color).toBe('#ffaf00')
    expect(contextOf(196_000, set).color).toBe('#ff0000')
  })

  test('swap each colour for its light twin on a light appearance, and leave the dark one alone', () => {
    const tree = { type: 'Box', props: { borderColor: '#a6d189' }, children: [{ type: 'Text', props: { color: '#ffff00', bold: true }, hover: { color: '#e78284' }, children: ['#ffff00'] }] }
    expect(recolor(tree, 'dark')).toBe(tree)
    expect(recolor(tree, 'light')).toEqual({
      type: 'Box',
      props: { borderColor: '#40a02b' },
      children: [{ type: 'Text', props: { color: '#9a6700', bold: true }, hover: { color: '#d20f39' }, children: ['#ffff00'] }],
    })
  })
})

describe('quotas', () => {
  const now = Date.parse('2026-10-06T12:00:00Z')
  const at = (ms: number) => new Date(now + ms).toISOString()

  test('judge the pace as the status line does', () => {
    expect(quotaOf('five_hour', 30, at(9_000_000), now)?.verdict).toEqual({ text: '→60%', tone: 'ok' })
    expect(quotaOf('five_hour', 46, at(9_000_000), now)?.verdict?.tone).toBe('tight')
    expect(quotaOf('five_hour', 60, at(9_000_000), now)?.verdict).toEqual({ text: 'out in 1h40m', tone: 'out' })
    expect(quotaOf('seven_day', 5, at(600_000_000), now)?.verdict).toBeNull()
    expect(quotaOf('spend_limit', 5, undefined, now)).toBeNull()
    expect(span(2 * 86_400_000 + 7 * 3_600_000)).toBe('2d07h')
    expect(span(2 * 3_600_000 + 35 * 60_000)).toBe('2h35m')
  })

  test('draw a bar green to the pace tick, the overshoot in the verdict colour', () => {
    const q = quotaOf('five_hour', 60, at(9_000_000), now)!
    const runs = barRuns(q, 10)
    expect(runs.map(r => r.text).join('')).toBe('━━━━━┃────')
    expect(runs.find(r => r.isPace)?.text).toBe('┃')
    expect(runs[0]!.color).toBe('#a6d189')
    const ahead = barRuns(quotaOf('five_hour', 85, at(9_000_000), now)!, 10).find(r => r.isAhead)
    expect(ahead).toEqual({ text: '━━╸', color: '#e78284', isAhead: true })
  })
})

test('the bar shows the running time, cache and context, and the model and effort the session starts with', async ($, on) => {
  mock.clock(on, { now: 3_725_000 })
  on('session.usage', () => ({ value: { startedAt: 0, context: { tokens: 50_000 } as never, rateLimits: [] } }))
  on('session.model', () => ({ value: 'opus' }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('env.get', () => ({ value: undefined }))
  on('settings.read', () => ({ value: { effortLevel: 'medium' } }))
  on('process.run', () => ok('Dark'))

  engineHint(on)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ text: /running 1h02m/ })).toBeDefined()
  expect(await ui.find({ text: /no request yet/ })).toBeDefined()
  expect(await ui.find({ text: /50\.0k\/167k \(200k − 33k\) 29%/ })).toBeDefined()
  expect((await ui.find({ key: 'pick:model' }))?.props.label).toBe('Opus 5.5')
  expect((await ui.find({ key: 'pick:effort' }))?.props.label).toBe('medium')
  await ui.unmount()
})

test('the model and effort chips open a coloured picker that switches them', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits: [] } }))
  const ran: string[] = []
  on('command.run', (_, e) => {
    ran.push(`/${e.command} ${e.args}`)
    return { text: '' }
  })

  engineHint(on)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ key: 'model:claude-sonnet-5-5' })).toBeUndefined()
  await ui.press({ key: 'pick:model' })
  await ui.press({ key: 'model:claude-sonnet-5-5' })
  expect((await ui.find({ key: 'pick:model' }))?.props.label).toBe('Sonnet 5.5')
  expect(await ui.find({ key: 'model:claude-opus-5-5' })).toBeUndefined()

  await ui.press({ key: 'pick:effort' })
  await ui.press({ key: 'effort:xhigh' })
  expect((await ui.find({ key: 'pick:effort' }))?.props.label).toBe('xhigh')
  expect(ran).toEqual(['/model claude-sonnet-5-5', '/effort xhigh'])
  await ui.unmount()
})

test('the quota chips show both windows and unfold their bars side by side', async ($, on) => {
  const now = Date.parse('2026-10-06T12:00:00Z')
  mock.clock(on, { now })
  const rateLimits = [
    { kind: 'five_hour', percentUsed: 30, resetsAt: new Date(now + 9_000_000).toISOString() },
    { kind: 'seven_day', percentUsed: 71, resetsAt: new Date(now + 200_000_000).toISOString() },
  ]
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits } }))

  engineHint(on)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect((await ui.find({ key: 'quotas:5h' }))?.props.label).toBe('5h 30%')
  expect((await ui.find({ key: 'quotas:7d' }))?.props.label).toBe('7d 71%')
  expect(await ui.find({ text: /→60%/ })).toBeUndefined()
  await ui.press({ key: 'quotas:7d' })
  expect(await ui.find({ text: /→60%/ })).toBeDefined()
  expect(await ui.find({ text: /out in/ })).toBeDefined()
  await ui.press({ key: 'quotas:fold' })
  expect(await ui.find({ text: /→60%/ })).toBeUndefined()
  await ui.unmount()
})

test('the context counter shows the engine trigger, in light colours on a light macOS', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  const breakdown = { autoCompactThreshold: 217_000, rawMaxTokens: 250_000, isAutoCompactEnabled: true }
  on('session.usage', () => ({ value: { startedAt: 0, context: { tokens: 120_000, window: 1_000_000, breakdown } as never, rateLimits: [] } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.model', () => ({ value: 'opus' }))
  on('env.get', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  on('process.run', (_, e) =>
    ok('', e.argv[0] === 'defaults' ? 'The domain/default pair of (kCFPreferencesAnyApplication, AppleInterfaceStyle) does not exist' : '', 1),
  )

  engineHint(on)
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  const bar = JSON.stringify(await ui.find({ text: /context/ }))
  expect(bar).toContain('"color":"#9a6700","inverse":false},"children":["120.0k/217k (250k − 33k) 55%"]')
  await ui.unmount()
})

test('the bar sits beneath the engine\'s hint line, kept as drawn', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits: [] } }))
  engineHint(on)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ text: /\? for shortcuts/ })).toBeDefined()
  expect(await ui.find({ text: /running/ })).toBeDefined()
  await ui.unmount()
})
