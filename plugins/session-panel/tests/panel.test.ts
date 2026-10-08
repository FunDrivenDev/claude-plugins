import { describe, expect, mock, test } from 'claude-code/testing'

import { ago, barRuns, cacheColor, cleanTitle, handoverPhase, phaseLine, contextOf, describeCall, duration, effortColor, fileMeta, handoverStatus, handoverTitle, headline, kfmt, lastSentence, minutesLeft, modelColor, modelId, prettyModel, promptText, quotaOf, recolor, resumeMessage, span } from '../hooks/register'

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
    expect(fileMeta(142, new Date(2026, 9, 7, 9, 32).getTime())).toBe('142 lines · 2026-10-07 09:32')
    expect(fileMeta(1, null)).toBe('1 line')
    expect(fileMeta(null, null)).toBeNull()
    const ho = { isOn: true, loaded: null, written: null, suggest: 150_000, trigger: 185_000, warn: 20_000, isWriting: false, isWindingDown: false, error: null, resume: null }
    expect(handoverStatus(ho, 92_000).text).toBe('triggers at 185k · now 92k')
    expect(handoverStatus(ho, 170_000).color).toBe('#e5c890')
    expect(handoverPhase(ho, 92_000)).toBeNull()
    expect(handoverPhase({ ...ho, isWindingDown: true }, 92_000)).toBe('winding')
    expect(handoverPhase(ho, 190_000)).toBe('winding')
    expect(handoverPhase({ ...ho, isWriting: true }, 190_000)).toBe('writing')
    expect(phaseLine('winding', 1_000)).toBe('◓ Winding down')
    expect(phaseLine('winding', 2_000)).toBe('◑ Winding down')
    expect(cleanTitle('Title: "Session panel tabs."\nmore')).toBe('Session panel tabs')
    expect(cleanTitle('  \n')).toBeNull()
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
    expect(await ui.find({ text: /no pull request/ })).toBeDefined()
    await ui.press({ key: 'tab:misc' })
    expect(await ui.find({ text: /1 running · 0 done/ })).toBeDefined()
    expect((await ui.find({ key: 'agent:a1' }))?.props.label).toContain('Find hooks')
    await ui.press({ key: 'tab:main' })
    await ui.unmount()
  }

  await $.turn.complete({ answer: 'Found them', durationMs: 5, isAborted: false, turnId: 't', agentId: 'a1', reason: 'answer' })

  const ui = await $.ui.mount({ plugin: 'session-panel', surface: 'terminal', ...PANE })
  await ui.press({ key: 'tab:misc' })
  expect(await ui.find({ text: /0 running · 1 done/ })).toBeDefined()
  await ui.press({ key: 'agent:a1' })
  expect(await ui.find({ text: /Found them/ })).toBeDefined()
  await ui.press({ key: 'tab:main' })
  await ui.press({ key: 'prompts' })
  expect(await ui.find({ text: /Build a calm side panel/ })).toBeDefined()
  expect(await ui.find({ text: /and another prompt/ })).toBeDefined()
  await ui.press({ key: 'prompts:back' })
  expect(await ui.find({ key: 'prompts' })).toBeDefined()
  await ui.unmount()
})

test('an open sub-agent shows its latest entries only and collapses from its foot', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits: [] } }))
  on('tool.call', () => ({ result: {} as never, text: 'y'.repeat(300) }) as never)
  on('process.run', () => ({ value: { exitCode: 1, stdout: '', stderr: '' } }) as never)
  on('ui.open', () => ({ value: undefined }))
  await $.agent.spawn({
    tool_use_id: 'tu1',
    prompt: 'P'.repeat(9000),
    description: 'Review the branch',
    subagentType: 'general-purpose',
    provider: { plugin: 'engine', tier: 'core' },
    parentModel: 'claude-opus-5-5',
    background: true,
    fork: false,
  })
  for (let k = 0; k < 200; k++) await $.tool.call({ tool: 'Bash', command: `echo step-${k}`, agentId: 'a1' } as never)

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'session-panel', surface, ...PANE })
    await ui.press({ key: 'tab:misc' })
    await ui.press({ key: 'agent:a1' })
    expect(await ui.find({ text: /echo step-199/ })).toBeDefined()
    expect(await ui.find({ text: /echo step-150/ })).toBeUndefined()
    expect(await ui.find({ text: /… 360 earlier/ })).toBeDefined()
    expect(await ui.find({ text: /P{3999}…/ })).toBeDefined()
    await ui.press({ key: 'agent:a1:close' })
    expect(await ui.find({ key: 'agent:a1:close' })).toBeUndefined()
    expect((await ui.find({ key: 'agent:a1' }))?.props.label).toBe('▸ Review the branch')
    await ui.unmount()
  }

  const ui = await $.ui.mount({ plugin: 'session-panel', surface: 'terminal', ...PANE })
  await ui.press({ key: 'tab:misc' })
  await ui.press({ key: 'agent:a1' })
  expect(await ui.find({ key: 'agent:a1:close' })).toBeDefined()
  await $.command.run({ command: 'session-panel' } as never)
  expect(await ui.find({ key: 'agent:a1:close' })).toBeUndefined()
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
  expect(await ui.find({ text: /Opus 5\.5/ })).toBeDefined()
  expect(await ui.find({ text: /Say echo 5/ })).toBeUndefined()
  await ui.press({ key: 'tab:misc' })
  expect(await ui.find({ text: /Say echo 5 ×2/ })).toBeDefined()
  expect(await ui.find({ text: /^\s*echo 5$/ })).toBeUndefined()
  expect(await ui.find({ text: /Say echo 3/ })).toBeDefined()
  expect(await ui.find({ text: /Say echo 2/ })).toBeUndefined()
  expect((await ui.find({ key: 'steps' }))?.props.label).toContain('3 earlier')
  await ui.press({ key: 'steps' })
  expect(await ui.find({ text: /Say echo 0/ })).toBeDefined()
  await ui.unmount()
})

test('the model and effort pills open a coloured picker that switches them', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits: [] } }))
  const ran: string[] = []
  on('ui.toast', ($, e) => {
    ran.push(JSON.stringify(e))
    return { value: undefined } as never
  })
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
    const window = { limit: 167_000, window: 200_000 }
    expect(contextOf(undefined, window)).toEqual({ text: '0/167k (200k − 33k)', color: '#8a8a8a', isCompacting: false })
    expect(contextOf(78_234, window)).toEqual({ text: '78.2k/167k (200k − 33k) 46%', color: '#5fff00', isCompacting: false })
    expect(contextOf(100_000, window).color).toBe('#ffff00')
    expect(contextOf(140_000, window).color).toBe('#ffaf00')
    expect(contextOf(160_000, window).color).toBe('#ff0000')
    expect(contextOf(170_000, window)).toEqual({ text: '170.0k/167k (200k − 33k) 101% ⚠ compacting', color: '#ff0000', isCompacting: true })
    expect(contextOf(78_234, { limit: 200_000, window: 200_000 }).text).toBe('78.2k/200k 39%')
  })

  test('grade the context on the trigger the person set, whatever its size', () => {
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

test('the quota pill shows both windows and unfolds their bars side by side', async ($, on) => {
  const now = Date.parse('2026-10-06T12:00:00Z')
  mock.clock(on, { now })
  const rateLimits = [
    { kind: 'five_hour', percentUsed: 30, resetsAt: new Date(now + 9_000_000).toISOString() },
    { kind: 'seven_day', percentUsed: 71, resetsAt: new Date(now + 200_000_000).toISOString() },
  ]
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits } }))

  const ui = await $.ui.mount({ plugin: 'session-panel', surface: 'terminal', ...PANE })
  expect((await ui.find({ key: 'quotas:5h' }))?.props.label).toBe('5h 30%')
  expect((await ui.find({ key: 'quotas:7d' }))?.props.label).toBe('7d 71%')
  expect(await ui.find({ text: /→60%/ })).toBeUndefined()
  await ui.press({ key: 'quotas:7d' })
  expect(await ui.find({ text: /→60%/ })).toBeDefined()
  expect(await ui.find({ text: /out in/ })).toBeDefined()
  await ui.press({ key: 'quotas:5h' })
  expect(await ui.find({ text: /→60%/ })).toBeUndefined()
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

test('the context counter shows the engine trigger and its reckoning, in light colours on a light macOS', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  const breakdown = { autoCompactThreshold: 217_000, rawMaxTokens: 250_000, isAutoCompactEnabled: true }
  on('session.usage', () => ({ value: { startedAt: 0, context: { tokens: 120_000, window: 1_000_000, breakdown } as never, rateLimits: [] } }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('session.model', () => ({ value: 'opus' }))
  on('command.register', () => ({ value: undefined }))
  on('session.messages', () => ({ value: [] }))
  on('session.id', () => ({ value: 's1' }))
  on('ui.open', () => ({ value: undefined }))
  on('env.get', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  on('process.run', ($, e) => {
    const isAppearance = e.argv[0] === 'defaults'
    const stderr = isAppearance ? 'The domain/default pair of (kCFPreferencesAnyApplication, AppleInterfaceStyle) does not exist' : ''
    return { value: { exitCode: 1, stdout: '', stderr, isStdoutTruncated: false, isStderrTruncated: false } }
  })

  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ plugin: 'session-panel', surface: 'terminal', ...PANE })
  const pane = JSON.stringify(await ui.find({ text: /context/ }))
  expect(pane).toContain('"color":"#9a6700","inverse":false},"children":["120.0k/217k (250k − 33k) 55%"]')
  expect(pane).toContain('"borderColor":"#fe640b"')
  await ui.unmount()
})

test('the top line shows the title the main agent sets, switches tabs and closes the pane', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.id', () => ({ value: 's1' }) as never)
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits: [] } }))
  const ran: string[] = []
  on('command.list', () => ({ value: [{ name: 'rename' }] }) as never)
  on('turn.complete', ($, e) => ({ text: e.answer }))
  on('command.run', ($, e) => {
    ran.push(`${e.command} ${e.args}`)
    return { text: '' } as never
  })
  let closed = ''
  on('ui.close', ($, e) => {
    closed = e.id
    return { value: undefined } as never
  })

  let ui = await $.ui.mount({ plugin: 'session-panel', surface: 'terminal', ...PANE })
  expect(await ui.find({ text: /^Session$/ })).toBeDefined()
  await ui.unmount()

  const set = await $.tool.call({ tool: 'mcp__session-panel__session_title', title: '"Session panel tabs."' } as never)
  expect(set.text).toBe('Session title set: Session panel tabs')
  expect(ran).toEqual([])
  await $.turn.complete({ answer: 'Done', durationMs: 5, isAborted: false, turnId: 't', reason: 'answer' } as never)
  for (let k = 0; k < 50 && !ran.length; k++) await $.ui.mount({ plugin: 'session-panel', surface: 'terminal', ...PANE }).then(m => m.unmount())
  expect(ran).toEqual(['rename Session panel tabs'])
  const empty = await $.tool.call({ tool: 'mcp__session-panel__session_title', title: ' ' } as never)
  expect(empty.deny).toContain('empty title')

  ui = await $.ui.mount({ plugin: 'session-panel', surface: 'terminal', ...PANE })
  expect(await ui.find({ text: /^Session panel tabs$/ })).toBeDefined()
  expect(await ui.find({ text: /^Handover$/ })).toBeDefined()
  expect(await ui.find({ text: /^Git diff$/ })).toBeUndefined()
  await ui.press({ key: 'tab:misc' })
  expect(await ui.find({ text: /^Git diff$/ })).toBeDefined()
  expect(await ui.find({ text: /^Handover$/ })).toBeUndefined()
  expect((await ui.find({ key: 'close' }))?.props.label).toBe(' ✕ ')
  await ui.press({ key: 'close' })
  expect(closed).toBe('session-panel')
  await ui.unmount()
})

test('the handover section lists its pills, and Hand over now starts the wind-down once', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 0, context: { tokens: 50_000 } as never, rateLimits: [] } }))
  on('process.run', ($, e) => {
    const isHandover = e.argv.some(arg => arg.includes('handover-fundrivendev'))
    return { value: { exitCode: isHandover ? 0 : 1, stdout: isHandover ? 'on\n@@\n{}\n@@\n{}' : '', stderr: '' } } as never
  })
  on('session.id', () => ({ value: 's1' }) as never)
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('session.model', () => ({ value: 'opus' }))
  on('command.register', () => ({ value: undefined }) as never)
  on('session.messages', () => ({ value: [] }))
  on('ui.open', () => ({ value: undefined }) as never)
  on('env.get', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  const sent: string[] = []
  on('command.run', ($, e) => {
    sent.push(`/${e.command}`)
    return { text: '' } as never
  })
  await $.session.start({ cwd: '/tmp', surface: 'terminal', isInteractive: true })

  const ui = await $.ui.mount({ plugin: 'session-panel', surface: 'terminal', ...PANE })
  expect(await ui.find({ text: /^Call-to-action pills$/ })).toBeDefined()
  expect(await ui.find({ text: /^Handover states$/ })).toBeDefined()
  for (const label of ['Winding down', 'Writing the handover', 'Ready for the next session'])
    expect(await ui.find({ text: new RegExp(`${label}$`) })).toBeDefined()
  for (const label of ['Start with this prompt', 'Edit the prompt first', 'Start next session', 'Hand over now'])
    expect(await ui.find({ text: new RegExp(`^${label}$`) })).toBeDefined()
  await ui.press({ key: 'handover:trigger' })
  expect(sent).toEqual(['/handover:trigger'])
  expect(await ui.find({ key: 'handover:trigger' })).toBeUndefined()
  await ui.unmount()
})

const RESUME = 'Resume the session-panel work: open the PR.'
const RESUME_REPLY = 'Done.\n\nRun `/clear`, then send:\n\n```\nResume the session-panel work:\n  open the PR.\n```\n'

test('a written handover starts the next session with its resume message in one press, titled from its handover', async ($, on) => {
  const clock = mock.clock(on, { now: 1_000 })
  let sid = 's1'
  on('session.usage', () => ({ value: { startedAt: 0, context: { tokens: 50_000 } as never, rateLimits: [] } }))
  on('process.run', ($, e) => {
    if (e.argv.some(arg => arg.includes('handover-fundrivendev'))) {
      const state = { written: { ok: true }, path: '/h/written.md', loaded_from: '/h/loaded.md' }
      return { value: { exitCode: 0, stdout: `on\n@@\n${JSON.stringify(state)}\n@@\n{}`, stderr: '' } } as never
    }
    if (e.argv.includes('/h/loaded.md')) return { value: { exitCode: 0, stdout: '---\nsummary: "Ship the session panel"\n---\n@@\n12\n1000', stderr: '' } } as never
    return { value: { exitCode: 1, stdout: '', stderr: '' } } as never
  })
  on('session.id', () => ({ value: sid }) as never)
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('session.model', () => ({ value: 'opus' }))
  on('command.register', () => ({ value: undefined }) as never)
  on('command.list', () => ({ value: [{ name: 'rename' }] }) as never)
  on('session.messages', () => ({ value: [{ role: 'assistant', text: RESUME_REPLY }] }) as never)
  on('ui.open', () => ({ value: undefined }) as never)
  on('ui.copy', () => ({ value: undefined }) as never)
  on('env.get', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  const ran: string[] = []
  on('command.run', ($, e) => {
    ran.push(`/${e.command}${e.args ? ` ${e.args}` : ''}`)
    if (e.command === 'clear') sid = 's2'
    return { text: '' } as never
  })
  const filled: string[] = []
  const sent: string[] = []
  on('prompt.fill', ($, e) => {
    filled.push(e.text)
    return { isFilled: true } as never
  })
  on('prompt.submit', ($, e) => {
    sent.push(e.text)
    return { text: e.text } as never
  })
  await $.session.start({ cwd: '/tmp', surface: 'terminal', isInteractive: true })
  expect(ran).toContain('/rename Ship the session panel')

  const ui = await $.ui.mount({ plugin: 'session-panel', surface: 'terminal', ...PANE })
  expect(await ui.find({ text: /^Ship the session panel$/ })).toBeDefined()
  await ui.press({ key: 'handover:run' })
  expect(ran).toContain('/clear')
  await clock.advance(5_000)
  expect(filled).toEqual([RESUME, ''])
  expect(sent).toEqual([RESUME])
  await ui.press({ key: 'handover:run' })
  expect(ran.filter(c => c === '/clear')).toHaveLength(1)
  await ui.unmount()
})
