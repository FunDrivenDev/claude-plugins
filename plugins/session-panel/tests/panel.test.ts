import { describe, expect, mock, test } from 'claude-code/testing'

import { ago, barRuns, cacheColor, contextOf, describeCall, duration, effortColor, handoverStatus, handoverTitle, headline, kfmt, lastSentence, minutesLeft, modelColor, modelId, prettyModel, promptText, quotaOf, resumeMessage, span } from '../hooks/register'

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
    expect(duration(3_725_000)).toBe('1h02m')
    expect(duration(65_000)).toBe('1m05s')
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
    const ho = { isOn: true, loaded: null, written: null, suggest: 150_000, trigger: 185_000, warn: 20_000, isWriting: false, error: null, resume: null }
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
    if (e.argv.includes('--git-common-dir')) return ok('/main/.git/worktrees/repo\n/main/.git\n')
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
  expect(await ui.find({ text: /▣ repo/ })).toBeDefined()
  expect(await ui.find({ text: /▣ repo/ })).toBeDefined()
  await ui.unmount()
})

describe('quotas', () => {
  const now = Date.parse('2026-10-06T12:00:00Z')
  const at = (ms: number) => new Date(now + ms).toISOString()

  test('count the context against the auto-compact trigger, graded as the status line', () => {
    expect(kfmt(78_234)).toBe('78.2k')
    expect(kfmt(934)).toBe('934')
    expect(contextOf(undefined, 167_000)).toEqual({ text: '0/167k', color: '#8a8a8a', isCompacting: false })
    expect(contextOf(78_234, 167_000)).toEqual({ text: '78.2k/167k 46%', color: '#5fff00', isCompacting: false })
    expect(contextOf(100_000, 167_000).color).toBe('#ffff00')
    expect(contextOf(140_000, 167_000).color).toBe('#ffaf00')
    expect(contextOf(160_000, 167_000).color).toBe('#ff0000')
    expect(contextOf(170_000, 167_000)).toEqual({ text: '170.0k/167k 101% ⚠ compacting', color: '#ff0000', isCompacting: true })
  })

  test('read the resume message the closing reply ends on', () => {
    const reply = 'Done.\n\nRun `/clear`, then send:\n\n```\nResume the session-panel work:\n  open the PR.\n```\n'
    expect(resumeMessage(reply)).toBe('Resume the session-panel work: open the PR.')
    expect(resumeMessage('```\nno clear before\n```')).toBeNull()
    expect(resumeMessage('Run /clear.')).toBeNull()
  })

  test('judge the pace as the status line does', () => {
    // 5h window, 2h30 elapsed: 30% lands at 60%
    expect(quotaOf('five_hour', 30, at(9_000_000), now)?.verdict).toEqual({ text: '→60%', tone: 'ok' })
    // 46% at half-time lands at 92%
    expect(quotaOf('five_hour', 46, at(9_000_000), now)?.verdict?.tone).toBe('tight')
    // 60% at half-time runs out with 1h40m of the window left to go
    expect(quotaOf('five_hour', 60, at(9_000_000), now)?.verdict).toEqual({ text: 'out in 1h40m', tone: 'out' })
    // too early in the window to judge
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

test('the quota bars sit side by side or one per line', async ($, on) => {
  const now = Date.parse('2026-10-06T12:00:00Z')
  mock.clock(on, { now })
  const rateLimits = [
    { kind: 'five_hour', percentUsed: 30, resetsAt: new Date(now + 9_000_000).toISOString() },
    { kind: 'seven_day', percentUsed: 71, resetsAt: new Date(now + 200_000_000).toISOString() },
  ]
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits } }))

  const ui = await $.ui.mount({ plugin: 'session-panel', surface: 'terminal', ...PANE })
  expect(await ui.find({ text: /→60%/ })).toBeDefined()
  expect(await ui.find({ text: /out in/ })).toBeDefined()
  expect((await ui.find({ key: 'quotas:layout' }))?.props.label).toBe('⇄ one per line')
  await ui.press({ key: 'quotas:layout' })
  expect((await ui.find({ key: 'quotas:layout' }))?.props.label).toBe('⇄ side by side')
  await ui.unmount()
})

test('the notes the session writes list under their kind, linked, by name', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits: [] } }))
  on('tool.call', () => ({ result: {} as never }))
  const opened: string[] = []
  on('process.run', ($, e) => {
    const ok = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
    if (e.argv[0] === 'open') opened.push(e.argv[1]!)
    if (e.argv[2]?.includes('pwd -P')) return ok('/Users/me\n/Users/me/Code/notes/personal\n')
    if (e.argv[2]?.includes('date -r')) return ok(`${e.argv.slice(5).join('\n')}\n`)
    return ok('')
  })

  const ui = await $.ui.mount({ plugin: 'session-panel', surface: 'terminal', ...PANE })
  expect(await ui.find({ text: /None written yet\./ })).toBeDefined()
  await ui.unmount()

  await $.tool.call({ tool: 'Write', file_path: '/Users/me/Notes/claude/reports/26-10-06-ci-ok-wrap-up.md', content: 'x' })
  await $.tool.call({ tool: 'Bash', command: 'cat > ~/Notes/claude/plans/26-10-06-ci-ok-open-questions.md <<EOF\nx\nEOF' })
  await $.tool.call({ tool: 'Write', file_path: '/Users/me/Code/repo/README.md', content: 'x' })

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'session-panel', surface, ...PANE })
    expect(await ui.find({ text: /None written yet/ })).toBeUndefined()
    expect(await ui.find({ text: /^Reports$/ })).toBeDefined()
    expect(await ui.find({ text: /^Plans$/ })).toBeDefined()
    if (surface === 'terminal') {
      const link = await ui.find({ type: 'Link', text: /26-10-06-ci-ok-wrap-up/ })
      expect(link?.props.href).toBe('file:///Users/me/Notes/claude/reports/26-10-06-ci-ok-wrap-up.md')
    } else {
      await ui.press({ key: 'note:claude/reports/26-10-06-ci-ok-wrap-up.md' })
      expect(opened).toEqual(['/Users/me/Notes/claude/reports/26-10-06-ci-ok-wrap-up.md'])
    }
    expect(await ui.find({ text: /26-10-06-ci-ok-open-questions/ })).toBeDefined()
    expect(await ui.find({ text: /README/ })).toBeUndefined()
    expect(await ui.find({ text: /\.md/ })).toBeUndefined()
    await ui.unmount()
  }
})
