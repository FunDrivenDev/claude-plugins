import { describe, expect, mock, test } from 'claude-code/testing'

import { ago, cleanTitle, clockTime, handoverPhase, phaseLine, describeCall, duration, fileMeta, handoverStatus, handoverTitle, headline, lastSentence, prettyModel, previousPrompts, promptText, recolor, resumeMessage } from '../hooks/panel'

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
    expect(lastSentence('Read the types. Then search engine types for link supp')).toBe('Read the types.')
    expect(handoverTitle('---\nstatus: done\nsummary: "panel corner"\n---\n# Handover: x')).toBe('panel corner')
    expect(handoverTitle('# Handover: session-panel tracker\n')).toBe('session-panel tracker')
    expect(fileMeta(142, new Date(2026, 9, 7, 9, 32).getTime())).toBe('142 lines · 2026-10-07 09:32')
    expect(fileMeta(1, null)).toBe('1 line')
    expect(previousPrompts(11)).toBe('11 previous prompts')
    expect(previousPrompts(1)).toBe('1 previous prompt')
    expect(previousPrompts(0)).toBe('no previous prompt')
    expect(clockTime(new Date(2026, 9, 8, 9, 5).getTime())).toBe('09:05')
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
    const ui = await $.ui.mount({ plugin: 'session-mods', surface, ...PANE })
    expect(await ui.find({ text: /and another prompt/ })).toBeDefined()
    expect(await ui.find({ text: /Build a calm side panel/ })).toBeUndefined()
    expect((await ui.find({ key: 'prompts' }))?.props.label).toBe('(1 previous prompt)')
    expect(await ui.find({ text: /no repository yet/ })).toBeDefined()
    expect(await ui.find({ text: /no issue/ })).toBeDefined()
    await ui.press({ key: 'tab:misc' })
    expect(await ui.find({ text: /1 running · 0 done/ })).toBeDefined()
    expect((await ui.find({ key: 'agent:a1' }))?.props.label).toContain('Find hooks')
    await ui.press({ key: 'tab:main' })
    await ui.unmount()
  }

  await $.turn.complete({ answer: 'Found them', durationMs: 5, isAborted: false, turnId: 't', agentId: 'a1', reason: 'answer' })

  const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
  await ui.press({ key: 'tab:misc' })
  expect(await ui.find({ text: /0 running · 1 done/ })).toBeDefined()
  await ui.press({ key: 'agent:a1' })
  expect(await ui.find({ text: /Found them/ })).toBeDefined()
  await ui.press({ key: 'tab:main' })
  await ui.press({ key: 'prompts' })
  expect(await ui.find({ text: /Build a calm side panel/ })).toBeDefined()
  expect(await ui.find({ text: /and another prompt/ })).toBeDefined()
  expect(await ui.find({ text: new RegExp(`^#2 · ${clockTime(1_000)}$`) })).toBeDefined()
  await ui.press({ key: 'prompts:back' })
  expect((await ui.find({ key: 'prompts' }))?.props.label).toBe('(1 previous prompt)')
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
    const ui = await $.ui.mount({ plugin: 'session-mods', surface, ...PANE })
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

  const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
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

  const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
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
  const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
  expect(await ui.find({ text: /⎇ claude-plugins/ })).toBeDefined()
  expect(await ui.find({ text: /#7 Publish/ })).toBeDefined()
  expect(await ui.find({ text: /draft/ })).toBeDefined()
  await ui.unmount()
})

test('a bare #N numbering a list yields to the pull request the session works on, read again from the transcript', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.model', () => ({ value: 'opus' }))
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits: [] } }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('command.register', () => ({ value: undefined }))
  on('session.id', () => ({ value: 's1' }))
  on('ui.open', () => ({ value: undefined }))
  on('env.get', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  on('session.messages', () => ({
    value: [
      { role: 'user', text: 'number them #1, #2, #3', toolUses: [] },
      { role: 'assistant', text: '', toolUses: [{ tool_use_id: 'b1', tool: 'Bash', input: { command: 'gh pr edit 21 --body-file b.md' }, text: '' }] },
    ],
  }))
  on('process.run', ($, e) => {
    const ok = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
    if (e.argv.includes('get-url')) return ok('git@github.com:FunDrivenDev/claude-plugins.git\n')
    const n = e.argv[0] === 'gh' ? /issues\/(\d+)$/.exec(e.argv[2] ?? '')?.[1] : undefined
    if (n) return ok(JSON.stringify({ title: `PR ${n}`, state: n === '1' ? 'closed' : 'open', url: `https://github.com/FunDrivenDev/claude-plugins/pull/${n}`, isPr: true, merged: n === '1', draft: n !== '1' }))
    return ok('')
  })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })

  const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
  expect(await ui.find({ text: /#21 PR 21/ })).toBeDefined()
  expect(await ui.find({ text: /#1 PR 1/ })).toBeUndefined()
  await ui.unmount()
})

test('a new session lists only the commits made since it began, in its linked worktree', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 1_700_000_000_000, context: {} as never, rateLimits: [] } }))
  on('session.model', () => ({ value: 'opus' }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('command.register', () => ({ value: undefined }))
  on('session.messages', () => ({ value: [] }))
  on('session.id', () => ({ value: 's1' }))
  on('ui.open', () => ({ value: undefined }))
  on('env.get', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  const logs: string[][] = []
  on('process.run', ($, e) => {
    const ok = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
    if (e.argv.includes('--show-toplevel')) return ok('/repo\n/main/.git/worktrees/repo\n/main/.git\n')
    if (e.argv.includes('--git-common-dir')) return ok('/main/.git/worktrees/repo\n/main/.git\n')
    if (e.argv.includes('log')) {
      logs.push([...e.argv])
      return ok('')
    }
    return ok('')
  })

  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  expect(logs[0]).toContain('--since=@1700000000')

  const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
  expect(await ui.find({ text: /▣ repo/ })).toBeDefined()
  await ui.unmount()
})

describe('colours and replies', () => {
  test('swap each colour for its light twin on a light appearance, and leave the dark one alone', () => {
    const tree = { type: 'Box', props: { borderColor: '#a6d189' }, children: [{ type: 'Text', props: { color: '#e5c890', bold: true }, hover: { color: '#e78284' }, children: ['#e5c890'] }] }
    expect(recolor(tree, 'dark')).toBe(tree)
    expect(recolor(tree, 'light')).toEqual({
      type: 'Box',
      props: { borderColor: '#40a02b' },
      children: [{ type: 'Text', props: { color: '#9a6700', bold: true }, hover: { color: '#d20f39' }, children: ['#e5c890'] }],
    })
  })

  test('read the resume message the closing reply ends on', () => {
    const reply = 'Done.\n\nRun `/clear`, then send:\n\n```\nResume the session-panel work:\n  open the PR.\n```\n'
    expect(resumeMessage(reply)).toBe('Resume the session-panel work: open the PR.')
    expect(resumeMessage('```\nno clear before\n```')).toBeNull()
    expect(resumeMessage('Run /clear.')).toBeNull()
  })

})

test('the documents the session writes list under their kind, linked, by name, artifacts first', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits: [] } }))
  on('tool.call', ($, e) => ({ result: (e.tool === 'Artifact' ? { url: 'https://claude.ai/artifact/9', path: '/w/guide.html', title: 'Panel guide' } : {}) as never }))
  const opened: string[] = []
  const real = (p: string) => p.replace('/Users/me/Notes/', '/Users/me/Code/notes/')
  on('process.run', ($, e) => {
    const ok = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
    if (e.argv[0] === 'open') opened.push(e.argv[1]!)
    if (e.argv[2]?.includes('TMPDIR')) return ok('/Users/me\n/Users/me/Code/repo/.git\n/private/tmp\n/private/tmp\n/Users/me/Code/notes/claude/agent-handovers\n/Users/me/.claude/plans\n')
    if (e.argv[2]?.includes('start=$1')) {
      const files = e.argv.slice(5)
      return ok(files.map(f => `${f}\n${real(f)}\n${f.startsWith('/Users/me/Code/repo/') ? '/Users/me/Code/repo/.git' : '/Users/me/Code/notes/.git'}\n`).join(''))
    }
    return ok('')
  })

  const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
  expect(await ui.find({ text: /None written yet\./ })).toBeDefined()
  await ui.unmount()

  await $.tool.call({ tool: 'Write', file_path: '/Users/me/Notes/claude/reports/26-10-06-ci-ok-wrap-up.md', content: 'x' })
  await $.tool.call({ tool: 'Bash', command: 'cat > ~/Notes/claude/questions/26-10-06-ci-ok-open-questions.md <<EOF\nx\nEOF' })
  await $.tool.call({ tool: 'Write', file_path: '/Users/me/Code/repo/README.md', content: 'x' })
  await $.tool.call({ tool: 'Artifact', file_path: '/w/guide.html' } as never)

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'session-mods', surface, ...PANE })
    expect(await ui.find({ text: /None written yet/ })).toBeUndefined()
    expect(await ui.find({ text: /^Documents$/ })).toBeDefined()
    expect(await ui.find({ text: /^Artifacts$/ })).toBeDefined()
    expect(await ui.find({ text: /^Reports$/ })).toBeDefined()
    expect(await ui.find({ text: /^Questions$/ })).toBeDefined()
    if (surface === 'terminal') {
      const link = await ui.find({ type: 'Link', text: /26-10-06-ci-ok-wrap-up/ })
      expect(link?.props.href).toBe('file:///Users/me/Notes/claude/reports/26-10-06-ci-ok-wrap-up.md')
      expect((await ui.find({ type: 'Link', text: /Panel guide/ }))?.props.href).toBe('https://claude.ai/artifact/9')
    } else {
      await ui.press({ key: 'doc:/Users/me/Code/notes/claude/reports/26-10-06-ci-ok-wrap-up.md' })
      expect(opened).toEqual(['/Users/me/Notes/claude/reports/26-10-06-ci-ok-wrap-up.md'])
    }
    expect(await ui.find({ text: /26-10-06-ci-ok-open-questions/ })).toBeDefined()
    expect(await ui.find({ text: /README/ })).toBeUndefined()
    expect(await ui.find({ text: /\.md/ })).toBeUndefined()
    await ui.unmount()
  }
})

test('the Config tab lists each value the pane reads, as in effect, with its default', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits: [] } }))
  const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
  await ui.press({ key: 'tab:config' })
  expect(await ui.find({ text: /^plansDirectory$/ })).toBeDefined()
  expect(await ui.find({ text: /~\/Notes\/claude\/agent-handovers \(default\)/ })).toBeDefined()
  for (const gone of [/^cacheTtl$/, /^autoCompactWindow$/, /^CC_TOKEN_LIMIT$/, /^CC_TOKEN_RESERVE$/]) expect(await ui.find({ text: gone })).toBeUndefined()
  await ui.unmount()
})

test('the pane takes its light colours on a light macOS', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits: [] } }))
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
  const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
  expect(await ui.find({ text: /context/ })).toBeUndefined()
  expect(await ui.find({ text: /⌛|⏳/ })).toBeUndefined()
  expect(JSON.stringify(await ui.find({ key: 'tab:main:box' }))).toContain('"borderColor":"#1e66f5"')
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

  let ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
  expect(await ui.find({ text: /^Session$/ })).toBeDefined()
  await ui.unmount()

  const set = await $.tool.call({ tool: 'mcp__session-mods__session_title', title: '"Session panel tabs."' } as never)
  expect(set.text).toBe('Session title set: Session panel tabs')
  expect(ran).toEqual([])
  await $.turn.complete({ answer: 'Done', durationMs: 5, isAborted: false, turnId: 't', reason: 'answer' } as never)
  for (let k = 0; k < 50 && !ran.length; k++) await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE }).then(m => m.unmount())
  expect(ran).toEqual(['rename Session panel tabs'])
  const empty = await $.tool.call({ tool: 'mcp__session-mods__session_title', title: ' ' } as never)
  expect(empty.deny).toContain('empty title')

  ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
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

test('the handover section leaves its states to Help, and Hand over now starts the wind-down once', async ($, on) => {
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

  const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
  expect(await ui.find({ text: /^Handover states$/ })).toBeUndefined()
  expect(await ui.find({ text: /Writing the handover$/ })).toBeUndefined()
  expect(await ui.find({ text: /^Call-to-action pills$/ })).toBeUndefined()
  expect((await ui.find({ key: 'handover:trigger' }))?.props.label).toBe('Hand over now')
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

  const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
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

test('a session without a title of its own reminds the agent once, and no more once titled', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  let sid = 's1'
  on('session.id', () => ({ value: sid }) as never)
  on('command.list', () => ({ value: [] }) as never)
  const contexts: (readonly string[] | undefined)[] = []
  on('prompt.submit', ($, e) => {
    contexts.push(e.context)
    return { text: e.text }
  })
  const reminded = () => contexts.map(c => (c ?? []).some(line => line.includes('session_title')))

  await $.prompt.submit(typed('Fix the panel'))
  await $.prompt.submit(typed('and the tests'))
  expect(reminded()).toEqual([true, false])

  sid = 's2'
  await $.tool.call({ tool: 'mcp__session-mods__session_title', title: 'Panel title fix' } as never)
  await $.prompt.submit(typed('carry on'))
  expect(reminded()).toEqual([true, false, false])
})

test('the Help tab explains each item beside an example of it, in place of the rest', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits: [] } }))
  const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
  await ui.press({ key: 'tab:help' })
  expect(await ui.find({ text: /Closes the pane; \/session-panel reopens it/ })).toBeDefined()
  expect(await ui.find({ text: /Hand over now/ })).toBeDefined()
  expect(await ui.find({ text: /● pushed, ○ local only/ })).toBeDefined()
  expect(await ui.find({ text: /Last prompt/ })).toBeDefined()
  for (const title of [/^Documents$/, /^Handover$/]) expect(await ui.find({ text: title })).toBeDefined()
  expect(await ui.find({ key: 'prompts' })).toBeUndefined()
  await ui.press({ key: 'tab:main' })
  expect((await ui.find({ key: 'prompts' }))?.props.label).toBe('(no previous prompt)')
  await ui.unmount()
})
