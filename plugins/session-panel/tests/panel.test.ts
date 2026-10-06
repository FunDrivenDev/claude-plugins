import { describe, expect, mock, test } from 'claude-code/testing'

import { ago, cacheColor, describeCall, duration, effortColor, handoverStatus, handoverTitle, headline, lastSentence, minutesLeft, modelColor, modelId, prettyModel, promptText } from '../hooks/register'

const PANE = {
  component: 'Pane',
  requestId: 'session-panel',
  props: {
    title: 'Session',
    isFocused: false,
    bodyColumns: 60,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as const

const typed = (text: string) => ({ text, wait: false, origin: { kind: 'composer' } as const })

describe('helpers', () => {
  test('names models and durations calmly', async () => {
    expect(prettyModel('claude-opus-5-5')).toBe('Opus 5.5')
    expect(prettyModel('claude-haiku-4-5-20251001')).toBe('Haiku 4.5')
    expect(duration(3_725_000)).toBe('1h 02m')
    expect(duration(65_000)).toBe('1m 05s')
    expect(ago(125_000)).toBe('2 min ago')
    expect(ago(2 * 3_600_000 + 600_000)).toBe('2 hours ago')
    expect(headline('Read the pane example first. Then write it.')).toBe('Read the pane example first.')
    expect(describeCall('Bash', { command: 'ls -la' })).toBe('Bash: ls -la')
    expect(modelColor('claude-opus-5-5[1m]')).toBe('#ef9f76')
    expect(effortColor('high')).toBe('#b1b9f9')
    expect(modelId('opus[1m]')).toBe('claude-opus-5-5')
    expect(modelId('claude-sonnet-5-5')).toBe('claude-sonnet-5-5')
    expect(minutesLeft(2_399_000)).toBe('39m')
    expect(minutesLeft(59_000)).toBe('<1m')
    expect([cacheColor(1_800_000, 3_600_000), cacheColor(720_000, 3_600_000), cacheColor(700_000, 3_600_000)]).toEqual(['#5fff00', '#ffff00', '#ffaf00'])
    expect(lastSentence('Read the types. Then search engine types for link supp')).toBe('Read the types.')
    expect(handoverTitle('---\nstatus: done\nsummary: "panel corner"\n---\n# Handover: x')).toBe('panel corner')
    expect(handoverTitle('# Handover: session-panel tracker\n')).toBe('session-panel tracker')
    const ho = { isOn: true, loaded: null, written: null, suggest: 150_000, trigger: 185_000, warn: 20_000, isWriting: false, error: null }
    expect(handoverStatus(ho, 92_000).text).toBe('triggers at 185k · now 92k')
    expect(handoverStatus(ho, 170_000).color).toBe('#e5c890')
    expect(promptText('<command-name>/login</command-name>')).toBeNull()
    expect(promptText('<system-reminder>x</system-reminder>\n<pasted_content id="1">Build a mod</pasted_content id="1">')).toBe('Build a mod')
  })
})

test('the pane shows the first prompt and moves a finished sub-agent to the done column', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('prompt.submit', ($, e) => ({ text: e.text }))
  on('turn.complete', ($, e) => ({ text: e.answer }))
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits: [] } }))

  await $.prompt.submit(typed('Build a calm side panel'))
  await $.prompt.submit(typed('and another prompt'))
  await $.agent.spawn({
    tool_use_id: 'tu1',
    prompt: 'Find the hooks',
    description: 'Find hooks',
    subagentType: 'Explore',
    provider: { plugin: 'engine', tier: 'core' },
    parentModel: 'claude-opus-5-5',
    background: false,
    fork: false,
  })

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'session-panel', surface, ...PANE })
    expect(await ui.find({ text: /and another prompt/ })).toBeDefined()
    expect(await ui.find({ text: /Build a calm side panel/ })).toBeUndefined()
    expect((await ui.find({ key: 'prompts' }))?.props.label).toBe('(2)')
    expect(await ui.find({ text: /1 running · 0 done/ })).toBeDefined()
    expect(await ui.find({ text: /no pull request/ })).toBeDefined()
    expect((await ui.find({ key: 'agent:a1' }))?.props.label).toContain('Find hooks')
    await ui.unmount()
  }

  await $.turn.complete({ answer: 'Found them', durationMs: 5, isAborted: false, turnId: 't', agentId: 'a1', reason: 'answer' })

  const ui = await $.ui.mount({ plugin: 'session-panel', surface: 'terminal', ...PANE })
  expect(await ui.find({ text: /0 running · 1 done/ })).toBeDefined()
  await ui.press({ key: 'agent:a1' })
  expect(await ui.find({ text: /Found them/ })).toBeDefined()
  await ui.press({ key: 'prompts' })
  expect(await ui.find({ text: /Build a calm side panel/ })).toBeDefined()
  expect(await ui.find({ text: /and another prompt/ })).toBeDefined()
  await ui.press({ key: 'prompts:back' })
  expect(await ui.find({ key: 'prompts' })).toBeDefined()
  await ui.unmount()
})

test('a step shows the command it ran, and only the four latest stay unfolded', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits: [] } }))
  on('turn.step', async function* ($, e) {
    const command = e.index === 6 ? 'echo 5' : `echo ${e.index}`
    return {
      turnId: e.turnId,
      index: e.index,
      answer: '',
      toolUses: [{ name: 'Bash', input: { command, description: `Say ${command}` } }],
      stopReason: 'tool_use' as const,
      usage: null,
    }
  })

  for (const index of [0, 1, 2, 3, 4, 5, 6]) {
    for await (const _ of $.turn.step({ turnId: 't1', index, model: 'claude-opus-5-5', effort: 'high', messageCount: 1 })) {
      // drained
    }
  }

  const ui = await $.ui.mount({ plugin: 'session-panel', surface: 'terminal', ...PANE })
  expect(await ui.find({ text: /Say echo 5 ×2/ })).toBeDefined()
  expect(await ui.find({ text: /^\s*echo 5$/ })).toBeUndefined()
  expect(await ui.find({ text: /Say echo 3/ })).toBeDefined()
  expect(await ui.find({ text: /Say echo 2/ })).toBeUndefined()
  expect((await ui.find({ key: 'steps' }))?.props.label).toContain('3 earlier')
  expect(await ui.find({ text: /Opus 5\.5/ })).toBeDefined()
  await ui.press({ key: 'steps' })
  expect(await ui.find({ text: /Say echo 0/ })).toBeDefined()
  await ui.unmount()
})

test('the model and effort pills open a coloured picker that switches them', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits: [] } }))
  const ran: string[] = []
  on('command.run', ($, e) => {
    ran.push(`/${e.command} ${e.args}`)
    return { text: '' }
  })

  const ui = await $.ui.mount({ plugin: 'session-panel', surface: 'terminal', ...PANE })
  expect(await ui.find({ key: 'model:claude-sonnet-5-5' })).toBeUndefined()
  await ui.press({ key: 'pick:model' })
  await ui.press({ key: 'model:claude-sonnet-5-5' })
  expect((await ui.find({ key: 'pick:model' }))?.props.label).toBe('Sonnet 5.5')
  expect(await ui.find({ key: 'model:claude-opus-5-5' })).toBeUndefined()

  await ui.press({ key: 'pick:effort' })
  await ui.press({ key: 'effort:xhigh' })
  expect((await ui.find({ key: 'pick:effort' }))?.props.label).toBe('xhigh 4/5')
  expect(ran).toEqual(['/model claude-sonnet-5-5', '/effort xhigh'])
  await ui.unmount()
})

test('the corner shows the prompted pull request in its GitHub colour, linked', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 0, context: { tokens: 1000, window: 200_000 }, rateLimits: [] } }))
  on('prompt.submit', ($, e) => ({ text: e.text }))
  on('process.run', ($, e) => {
    if (e.argv[0] === 'gh' && e.argv[2] === 'repos/FunDrivenDev/claude-plugins/issues/7') {
      const pr = { title: 'Publish', state: 'open', url: 'https://github.com/FunDrivenDev/claude-plugins/pull/7', isPr: true, merged: false, draft: true }
      return { value: { exitCode: 0, stdout: JSON.stringify(pr), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    }
    return { value: { exitCode: 1, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })

  await $.prompt.submit(typed('push it to FunDrivenDev/claude-plugins#7'))
  const ui = await $.ui.mount({ plugin: 'session-panel', surface: 'terminal', ...PANE })
  expect(await ui.find({ text: /claude-plugins #7/ })).toBeDefined()
  expect(await ui.find({ text: /draft/ })).toBeDefined()
  await ui.unmount()
})

test('a new session selects its model and saved effort, and lists only the commits made since it began', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 1_700_000_000_000, context: {} as never, rateLimits: [] } }))
  on('session.model', () => ({ value: 'opus' }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('command.register', () => ({ value: undefined }))
  on('session.messages', () => ({ value: [] }))
  on('session.id', () => ({ value: 's1' }))
  on('ui.open', () => ({ value: undefined }))
  on('env.get', () => ({ value: undefined }))
  on('settings.read', () => ({ value: { effortLevel: 'medium' } }))
  const logs: string[][] = []
  on('process.run', ($, e) => {
    const ok = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
    if (e.argv.includes('--show-toplevel')) return ok('/repo\n')
    if (e.argv.includes('log')) {
      logs.push([...e.argv])
      return ok('')
    }
    return ok('')
  })

  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  expect(logs[0]).toContain('--since=@1700000000')

  const ui = await $.ui.mount({ plugin: 'session-panel', surface: 'terminal', ...PANE })
  expect((await ui.find({ key: 'pick:model' }))?.props.label).toBe('Opus 5.5')
  expect((await ui.find({ key: 'pick:effort' }))?.props.label).toBe('medium 2/5')
  await ui.unmount()
})
