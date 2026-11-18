import { describe, expect, mock, test, type TestBody } from 'claude-code/testing'

import { afkGoal, afkLine, afkState, ago, cleanTitle, clockTime, handoverActions, handoverPhase, phaseLine, describeCall, fileMeta, handoverStatus, headline, lastSentence, previousPrompts, promptText } from '../hooks/panel'
import { HANDOVER_STATE, unknownHandover } from '../hooks/handover'

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
    expect(ago(125_000)).toBe('2 min ago')
    expect(ago(2 * 3_600_000 + 600_000)).toBe('2 hours ago')
    expect(headline('Read the pane example first. Then write it.')).toBe('Read the pane example first.')
    expect(describeCall('Bash', { command: 'ls -la' })).toBe('Bash: ls -la')
    expect(lastSentence('Read the types. Then search engine types for link supp')).toBe('Read the types.')
    expect(fileMeta(142, new Date(2026, 9, 7, 9, 32).getTime())).toBe('142 lines · 2026-10-07 09:32')
    expect(fileMeta(1, null)).toBe('1 line')
    expect(previousPrompts(11)).toBe('11 previous prompts')
    expect(previousPrompts(1)).toBe('1 previous prompt')
    expect(previousPrompts(0)).toBe('no previous prompt')
    expect(clockTime(new Date(2026, 9, 8, 9, 5).getTime())).toBe('09:05')
    expect(fileMeta(null, null)).toBeNull()
    const thresholds = { suggest: 150_000, warnAt: 167_500, trigger: 185_000 }
    const ho = { isOn: true, unknown: null, loaded: null, written: null, thresholds, thresholdsError: null, pending: null, isWriting: false, isWindingDown: false, error: null, resume: null, afk: null, relays: null }
    expect(handoverStatus(ho, 92_000).text).toBe('triggers at 185k · now 92k')
    expect(handoverStatus(ho, 167_000).color).toBe('#a5adce')
    expect(handoverStatus(ho, 167_500).color).toBe('#e5c890')
    expect(handoverStatus({ ...ho, thresholds: null, thresholdsError: 'why' }, 92_000)).toEqual({ text: 'thresholds unknown · why', color: '#e78284' })
    expect(handoverPhase({ ...ho, thresholds: null, thresholdsError: 'why' }, 190_000)).toBeNull()
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
    expect(await ui.find({ text: /and another prompt/ })).toBeUndefined()
    await ui.press({ key: 'tab:misc' })
    expect(await ui.find({ text: /and another prompt/ })).toBeDefined()
    expect(await ui.find({ text: /Build a calm side panel/ })).toBeUndefined()
    expect((await ui.find({ key: 'prompts' }))?.props.label).toBe('(1 previous prompt)')
    expect(await ui.find({ text: /no repository yet/ })).toBeDefined()
    expect(await ui.find({ text: /no issue/ })).toBeDefined()
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
  on('ui.open', () => ({ value: { isPlaced: true } }))
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
  await ui.press({ key: 'tab:misc' })
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
  on('command.register', () => ({ value: { command: 'session-panel' } }))
  on('session.id', () => ({ value: 's1' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
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
  await ui.press({ key: 'tab:misc' })
  expect(await ui.find({ text: /#21 PR 21/ })).toBeDefined()
  expect(await ui.find({ text: /#1 PR 1/ })).toBeUndefined()
  await ui.unmount()
})

test('a new session lists only the commits made since it began, in its linked worktree', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 1_700_000_000_000, context: {} as never, rateLimits: [] } }))
  on('session.model', () => ({ value: 'opus' }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('command.register', () => ({ value: { command: 'session-panel' } }))
  on('session.messages', () => ({ value: [] }))
  on('session.id', () => ({ value: 's1' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('env.get', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  const logs: string[][] = []
  on('process.run', ($, e) => {
    const ok = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
    if (e.argv.includes('--show-toplevel')) return ok('/repo\n/main/.git/worktrees/repo\n/main/.git\n')
    if (e.argv.includes('log')) {
      logs.push([...e.argv])
      return ok('')
    }
    return ok('')
  })

  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  expect(logs[0]).toContain('--since=@1700000000')

  const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
  await ui.press({ key: 'tab:misc' })
  expect(await ui.find({ text: /▣ repo/ })).toBeDefined()
  await ui.unmount()
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
  await ui.press({ key: 'tab:misc' })
  expect(await ui.find({ text: /None written yet\./ })).toBeDefined()
  await ui.unmount()

  await $.tool.call({ tool: 'Write', file_path: '/Users/me/Notes/claude/reports/26-10-06-ci-ok-wrap-up.md', content: 'x' })
  await $.tool.call({ tool: 'Bash', command: 'cat > ~/Notes/claude/questions/26-10-06-ci-ok-open-questions.md <<EOF\nx\nEOF' })
  await $.tool.call({ tool: 'Write', file_path: '/Users/me/Code/repo/README.md', content: 'x' })
  await $.tool.call({ tool: 'Artifact', file_path: '/w/guide.html' } as never)

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'session-mods', surface, ...PANE })
    await ui.press({ key: 'tab:misc' })
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

test('the Config tab shows the thresholds this session runs with, and those set since for the next session', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 0, context: { tokens: 50_000 } as never, rateLimits: [] } }))
  const state = { on: true, thresholds: { suggest: 200_000, warn_at: 225_000, trigger: 250_000 }, pending: { trigger: 120_000 } }
  on('process.run', ($, e) => {
    const answer = e.argv.includes(HANDOVER_STATE) ? { exitCode: 0, stdout: JSON.stringify(state) } : { exitCode: 1, stdout: '' }
    return { value: { stderr: '', ...answer } } as never
  })
  on('session.id', () => ({ value: 's1' }) as never)
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('session.model', () => ({ value: 'opus' }))
  on('command.register', () => ({ value: undefined }) as never)
  on('session.messages', () => ({ value: [] }))
  on('ui.open', () => ({ value: undefined }) as never)
  on('env.get', () => ({ value: undefined }))
  on('settings.read', () => ({
    value: { pluginConfigs: { 'handover@fundrivendev': { options: { trigger_tokens: 120_000, handover_dir: '/h/handovers' } } } },
  }))
  await $.session.start({ cwd: '/tmp', surface: 'terminal', isInteractive: true })

  const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
  await ui.press({ key: 'tab:config' })
  expect(await ui.find({ text: /^250k$/ })).toBeDefined()
  expect(await ui.find({ text: /^120k set in settings · applies from the next session$/ })).toBeDefined()
  expect(await ui.find({ text: /^200k$/ })).toBeDefined()
  expect(await ui.find({ text: /^\/h\/handovers$/ })).toBeDefined()
  expect(await ui.find({ text: /unknown/ })).toBeUndefined()
  await ui.unmount()
})

test('the pane takes its light colours on a light macOS', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits: [] } }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('session.model', () => ({ value: 'opus' }))
  on('command.register', () => ({ value: { command: 'session-panel' } }))
  on('session.messages', () => ({ value: [] }))
  on('session.id', () => ({ value: 's1' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
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
    const answer = e.argv.includes(HANDOVER_STATE) ? { exitCode: 0, stdout: '{"on": true}' } : { exitCode: 1, stdout: '' }
    return { value: { stderr: '', ...answer } } as never
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

test('a handover plugin older than its state command leaves the section unknown', async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 0, context: { tokens: 50_000 } as never, rateLimits: [] } }))
  on('process.run', ($, e) => {
    const answer = e.argv.includes(HANDOVER_STATE) ? { exitCode: 2, stdout: '', stderr: "handover.py: error: argument cmd: invalid choice: 'state'" } : { exitCode: 1, stdout: '' }
    return { value: { stderr: '', ...answer } } as never
  })
  on('session.id', () => ({ value: 's1' }) as never)
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('session.model', () => ({ value: 'opus' }))
  on('command.register', () => ({ value: undefined }) as never)
  on('session.messages', () => ({ value: [] }))
  on('ui.open', () => ({ value: undefined }) as never)
  on('env.get', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  await $.session.start({ cwd: '/tmp', surface: 'terminal', isInteractive: true })

  const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
  expect(await ui.find({ text: /^Handover state unknown: .*older than 0\.29\.0\.$/ })).toBeDefined()
  // Nothing is known of a loaded handover either: no `loaded none` line claims there was none.
  expect(await ui.find({ text: /^none$/ })).toBeUndefined()
  expect(await ui.find({ key: 'handover:trigger' })).toBeUndefined()
  await ui.unmount()
})

describe('AFK', () => {
  test('helpers: the state, the goal sent and the deadline line', async () => {
    const ho = { ...unknownHandover('x'), unknown: null }
    expect(afkState({ ...ho, relays: true })).toEqual({ kind: 'off' })
    expect(afkState({ ...ho, relays: false, afk: { goal: 'g', until: null } })).toEqual({ kind: 'on', goal: 'g', until: null })
    expect(afkState({ ...ho, relays: false }).kind).toBe('unavailable')
    expect(afkState({ ...ho, relays: null })).toEqual({ kind: 'unavailable', why: 'AFK mode from the pane needs handover 0.35.0 or later' })
    expect(afkGoal('  ship the pane\n until 8 ')).toBe('ship the pane until 8')
    expect([afkGoal('   '), afkGoal('OFF')]).toEqual([null, null])
    expect(afkLine(null)).toBe('AFK on')
    expect(afkLine(new Date(2026, 10, 17, 8, 0).getTime())).toBe('AFK on · until Tue 17 Nov 08:00')
  })

  /** The pane over a handover state answering `state`, the commands it runs recorded in `sent`. */
  const mountWith = async ($: Parameters<TestBody>[0], on: Parameters<TestBody>[1], state: Record<string, unknown>, sent: string[]) => {
    mock.clock(on, { now: 1_000 })
    on('session.usage', () => ({ value: { startedAt: 0, context: { tokens: 50_000 } as never, rateLimits: [] } }))
    on('process.run', ($, e) => {
      const answer = e.argv.includes(HANDOVER_STATE) ? { exitCode: 0, stdout: JSON.stringify({ on: true, ...state }) } : { exitCode: 1, stdout: '' }
      return { value: { stderr: '', ...answer } } as never
    })
    on('session.id', () => ({ value: 's1' }) as never)
    on('session.start', ($, e) => ({ cwd: e.cwd }))
    on('session.model', () => ({ value: 'opus' }))
    on('command.register', () => ({ value: undefined }) as never)
    on('session.messages', () => ({ value: [] }))
    on('ui.open', () => ({ value: undefined }) as never)
    on('env.get', () => ({ value: undefined }))
    on('settings.read', () => ({ value: {} }))
    on('command.run', ($, e) => {
      sent.push(`/${e.command}${e.args ? ` ${e.args}` : ''}`)
      return { text: '' } as never
    })
    await $.session.start({ cwd: '/tmp', surface: 'terminal', isInteractive: true })
    return $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
  }

  test('off, Go AFK opens the goal field, and Enter turns AFK on through /handover:afk', async ($, on) => {
    const sent: string[] = []
    const ui = await mountWith($, on, { relays: true }, sent)
    expect(await ui.find({ key: 'afk:goal' })).toBeUndefined()
    await ui.press({ key: 'afk:on' })
    // An empty goal sends nothing.
    await ui.input({ key: 'afk:goal', text: '  ' })
    expect(sent).toEqual([])
    await ui.input({ key: 'afk:goal', text: 'ship the pane until 8' })
    expect(sent).toEqual(['/handover:afk ship the pane until 8'])
    expect(await ui.find({ key: 'afk:goal' })).toBeUndefined()
    expect(await ui.find({ text: /^Turning AFK on…$/ })).toBeDefined()
    await ui.unmount()
  })

  test('the goal field cancels back to Go AFK', async ($, on) => {
    const sent: string[] = []
    const ui = await mountWith($, on, { relays: true }, sent)
    await ui.press({ key: 'afk:on' })
    await ui.press({ key: 'afk:cancel' })
    expect(await ui.find({ key: 'afk:goal' })).toBeUndefined()
    expect(await ui.find({ key: 'afk:on' })).toBeDefined()
    expect(sent).toEqual([])
    await ui.unmount()
  })

  test('on, the run shows its goal and deadline, and Turn AFK off runs /handover:afk off', async ($, on) => {
    const sent: string[] = []
    const until = new Date(2026, 10, 17, 8, 0).getTime() / 1000
    const ui = await mountWith($, on, { relays: true, afk: { goal: 'ship the pane', until } }, sent)
    expect(await ui.find({ text: /AFK on · until Tue 17 Nov 08:00$/ })).toBeDefined()
    expect(await ui.find({ text: /^ship the pane$/ })).toBeDefined()
    expect(await ui.find({ key: 'afk:on' })).toBeUndefined()
    await ui.press({ key: 'afk:off' })
    expect(sent).toEqual(['/handover:afk off'])
    expect(await ui.find({ text: /^Turning AFK off…$/ })).toBeDefined()
    await ui.unmount()
  })

  test('helpers: the Handover actions that share a row, in order', async () => {
    const none = { isTriggerable: false, isStopped: false, hasResume: false, isAfkOffered: false }
    expect(handoverActions(none)).toEqual([])
    expect(handoverActions({ ...none, isTriggerable: true, isAfkOffered: true })).toEqual(['handover:trigger', 'afk:on'])
    expect(handoverActions({ ...none, isStopped: true, hasResume: true, isAfkOffered: true })).toEqual(['handover:run', 'handover:edit', 'afk:on'])
    expect(handoverActions({ ...none, isStopped: true })).toEqual(['handover:edit'])
  })

  type Drawn = { type?: string; key?: string; props?: { key?: string }; children?: unknown[] }
  const walk = (node: unknown): Drawn[] => {
    if (!node || typeof node !== 'object') return []
    const d = node as Drawn
    return [d, ...(d.children ?? []).flatMap(walk)]
  }
  /** The keys of the buttons drawn inside the Box keyed `row`. */
  const buttonsIn = async (ui: { find: (q: { key: string }) => Promise<unknown> }, row: string) =>
    walk(await ui.find({ key: row }))
      .filter(d => d.type === 'Button')
      .map(d => d.key ?? d.props?.key)

  test('Hand over now and Go AFK share one wrapping row', async ($, on) => {
    const ui = await mountWith($, on, { relays: true }, [])
    expect(await buttonsIn(ui, 'handover:row')).toEqual(['handover:trigger', 'afk:on'])
    expect((await ui.find({ key: 'handover:row' }))?.props.flexWrap).toBe('wrap')
    await ui.press({ key: 'afk:on' })
    // The goal field takes Go AFK's place, its cancel on the same row.
    expect(await buttonsIn(ui, 'handover:row')).toEqual(['handover:trigger'])
    expect(await buttonsIn(ui, 'afk')).toEqual(['afk:cancel'])
    await ui.unmount()
  })

  const written = { path: '/h/written.md', title: null, lines: null, modified_at: null }

  test('once a handover is written, Start, Edit and Go AFK share the row, the resume message beneath it', async ($, on) => {
    const ui = await mountWith($, on, { relays: true, written, resume: 'Resume the panel work.' }, [])
    expect(await buttonsIn(ui, 'handover:row')).toEqual(['handover:run', 'handover:edit', 'afk:on'])
    expect((await ui.find({ key: 'handover:run' }))?.props.autoFocus).toBe(true)
    expect((await ui.find({ key: 'handover:actions' }))?.text).toMatch(/Resume the panel work\.$/)
    await ui.unmount()
  })

  test('without a resume message, the written handover offers Edit and Go AFK alone', async ($, on) => {
    const ui = await mountWith($, on, { relays: true, written, resume: null }, [])
    expect(await buttonsIn(ui, 'handover:row')).toEqual(['handover:edit', 'afk:on'])
    await ui.unmount()
  })

  test('on, Turn AFK off sits beside the AFK line', async ($, on) => {
    const ui = await mountWith($, on, { relays: true, afk: { goal: 'ship the pane', until: null } }, [])
    expect(await buttonsIn(ui, 'afk:line')).toEqual(['afk:off'])
    expect((await ui.find({ key: 'afk:line' }))?.text).toMatch(/AFK on/)
    expect(await buttonsIn(ui, 'handover:row')).toEqual(['handover:trigger'])
    await ui.unmount()
  })

  test('without a relay, or with a handover plugin that does not say, the pane says why and offers no button', async ($, on) => {
    const sent: string[] = []
    const ui = await mountWith($, on, { relays: false }, sent)
    expect(await ui.find({ text: /^AFK mode needs a relay: .*toolbox session run\.$/ })).toBeDefined()
    expect(await ui.find({ key: 'afk:on' })).toBeUndefined()
    expect(await ui.find({ text: /Rex/ })).toBeUndefined()
    await ui.unmount()
  })

  test('a handover plugin older than 0.35.0 leaves AFK unavailable', async ($, on) => {
    const ui = await mountWith($, on, {}, [])
    expect(await ui.find({ text: /^AFK mode from the pane needs handover 0\.35\.0 or later\.$/ })).toBeDefined()
    expect(await ui.find({ key: 'afk:on' })).toBeUndefined()
    await ui.unmount()
  })
})

const RESUME = 'Resume the session-panel work: open the PR.'

test('a written handover starts the next session with its resume message in one press, titled from its handover', async ($, on) => {
  const clock = mock.clock(on, { now: 1_000 })
  let sid = 's1'
  on('session.usage', () => ({ value: { startedAt: 0, context: { tokens: 50_000 } as never, rateLimits: [] } }))
  const state = {
    on: true,
    written: { path: '/h/written.md', title: null, lines: null, modified_at: null },
    loaded: { path: '/h/loaded.md', title: 'Ship the session panel', lines: 12, modified_at: 1 },
    resume: RESUME,
  }
  on('process.run', ($, e) => {
    const answer = e.argv.includes(HANDOVER_STATE) ? { exitCode: 0, stdout: JSON.stringify(state) } : { exitCode: 1, stdout: '' }
    return { value: { stderr: '', ...answer } } as never
  })
  on('session.id', () => ({ value: sid }) as never)
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('session.model', () => ({ value: 'opus' }))
  on('command.register', () => ({ value: undefined }) as never)
  on('command.list', () => ({ value: [{ name: 'rename' }] }) as never)
  on('session.messages', () => ({ value: [] }))
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
  for (const gone of [/^Situation$/, /^Merge plan$/, /other tabs of the topic/]) expect(await ui.find({ text: gone })).toBeUndefined()
  expect(await ui.find({ key: 'prompts' })).toBeUndefined()
  await ui.press({ key: 'tab:misc' })
  expect((await ui.find({ key: 'prompts' }))?.props.label).toBe('(no previous prompt)')
  await ui.unmount()
})

test('with the situation option on, the Help tab explains Situation too', { options: { situation: true } }, async ($, on) => {
  mock.clock(on, { now: 1_000 })
  on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits: [] } }))
  const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
  await ui.press({ key: 'tab:help' })
  expect(await ui.find({ text: /^Situation$/ })).toBeDefined()
  expect(await ui.find({ text: /other tabs of the topic's terminal session/ })).toBeDefined()
  await ui.unmount()
})

describe('Situation', () => {
  const ok = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  const fail = { value: { exitCode: 1, stdout: '', stderr: 'unreachable', isStdoutTruncated: false, isStderrTruncated: false } }
  const settle = async () => {
    for (let i = 0; i < 200; i++) await Promise.resolve()
  }
  const NOTES =
    '\x1e/n/plans/26-11-16-spj-merge-plan.md\t1000\n---\nstatus: doing\ntopic: spj\n---\n\n| Wave | PR | Status | Note |\n|---|---|---|---|\n| 1 | [claude-plugins#90](https://github.com/FunDrivenDev/claude-plugins/pull/90) | 🔧 | worker running |\n' +
    '\x1e/n/plans/26-11-16-spj-open-questions.md\t1000\n---\nstatus: todo\ntopic: spj\n---\n\n## Q1 — Which name?\n' +
    '\x1e/n/decisions-register/26-11-16-spj.md\t1000\n---\nkind: decision-register\ntopic: spj\n---\n\n- **D01** `proposed` — Name it Situation.\n'
  const REX = JSON.stringify({
    session_id: 'session:1',
    label: 'spj',
    windows: [
      { window_id: 'window:me', label: 'work', focused_block_id: 'block:me', layers: [{ blocks: [{ block_id: 'block:me' }] }] },
      { window_id: 'window:w', label: 'review · claude-plugins#90', focused_block_id: 'block:w', layers: [{ blocks: [{ block_id: 'block:w' }] }] },
    ],
  })
  const start = (on: Parameters<TestBody>[1], env: Record<string, string>, run: (argv: readonly string[]) => unknown) => {
    mock.clock(on, { now: 1_000 })
    on('session.usage', () => ({ value: { startedAt: 0, context: {} as never, rateLimits: [] } }))
    on('session.model', () => ({ value: 'opus' }))
    on('session.start', ($, e) => ({ cwd: e.cwd }))
    on('command.register', () => ({ value: { command: 'session-panel' } }))
    on('session.messages', () => ({ value: [] }))
    on('session.id', () => ({ value: 's1' }))
    on('ui.open', () => ({ value: { isPlaced: true } }))
    on('env.get', ($, e) => ({ value: env[(e as { name: string }).name] }))
    on('settings.read', () => ({ value: {} }))
    on('tool.call', () => ({ result: {} as never }))
    on('process.run', ($, e) => (run(e.argv) ?? ok('')) as never)
  }

  const ON = { options: { situation: true } }

  test('off by default, Main shows Handover alone, nothing is read for Situation, and Config lists the option off', async ($, on) => {
    const ran: string[] = []
    start(on, { REX_SESSION: 'session:1', REX_BLOCK: 'block:me' }, argv => {
      ran.push(argv.join(' '))
      return undefined
    })
    await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
    await $.tool.call({ tool: 'Read', file_path: '/Users/me/Notes/claude/plans/26-11-16-spj-brief.md' } as never)
    await settle()
    expect(ran.filter(c => /^(rex|gh) /.test(c) || c.includes('decisions-register') || c.includes('head -20 "$1"'))).toEqual([])
    const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
    expect(await ui.find({ text: /^Handover$/ })).toBeDefined()
    for (const gone of [/^Situation$/, /^No topic: /, /^Not read yet\.$/]) expect(await ui.find({ text: gone })).toBeUndefined()
    await ui.press({ key: 'tab:config' })
    expect(await ui.find({ text: /^situation$/ })).toBeDefined()
    expect(await ui.find({ text: /^off \(default\)$/ })).toBeDefined()
    await ui.unmount()
  })

  test('Main shows Handover then the Situation of the terminal session\'s topic, filled; the rest sits on Misc', ON, async ($, on) => {
    start(on, { REX_SESSION: 'session:1', REX_BLOCK: 'block:me' }, argv => {
      if (argv[0] === 'rex' && argv[1] === 'window') return ok(REX)
      if (argv[0] === 'rex' && argv[1] === 'capture') return argv.includes('block:w') ? ok('⏺ Reading the diff.\n❯ \n  esc to interrupt\n') : fail
      if (argv[0] === 'sh' && argv[2]?.includes('decisions-register')) return argv[4] === 'spj' ? ok(NOTES) : fail
      if (argv[0] === 'gh' && argv[1] === 'pr') return ok('{"state":"OPEN","isDraft":true,"red":1}')
      return undefined
    })
    await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
    await settle()
    const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
    expect(await ui.find({ text: /^Handover$/ })).toBeDefined()
    expect(await ui.find({ text: /^Situation$/ })).toBeDefined()
    expect(await ui.find({ text: /spj · terminal session/ })).toBeDefined()
    const pr = await ui.find({ type: 'Link', text: /claude-plugins#90/ })
    expect(pr?.props.href).toBe('https://github.com/FunDrivenDev/claude-plugins/pull/90')
    expect(JSON.stringify(await ui.find({ type: 'Text', text: /^claude-plugins#90$/ }))).toContain('#babbf1')
    expect(await ui.find({ text: /^!$/ })).toBeDefined()
    expect(await ui.find({ text: /worker running/ })).toBeDefined()
    expect(await ui.find({ text: /^stale: / })).toBeUndefined()
    expect(await ui.find({ text: /review · claude-plugins#90/ })).toBeDefined()
    expect(await ui.find({ text: /running · Reading the diff\./ })).toBeDefined()
    expect(await ui.find({ text: /^work$/ })).toBeUndefined()
    expect(await ui.find({ text: /Which name\?/ })).toBeDefined()
    expect(await ui.find({ text: /Name it Situation\./ })).toBeDefined()
    for (const gone of [/no issue/, /no repository yet/, /^Documents$/, /^Last prompt/, /^Steps/]) expect(await ui.find({ text: gone })).toBeUndefined()
    await ui.press({ key: 'tab:misc' })
    for (const moved of [/no issue/, /no repository yet/, /^Documents$/, /^Last prompt/, /^Steps/, /^Git diff$/]) expect(await ui.find({ text: moved })).toBeDefined()
    expect(await ui.find({ text: /^Situation$/ })).toBeUndefined()
    await ui.press({ key: 'tab:config' })
    expect(await ui.find({ text: /^on$/ })).toBeDefined()
    await ui.unmount()
  })

  test("a merge-plan row whose status gh contradicts shows stale and why, in yellow", ON, async ($, on) => {
    start(on, { REX_SESSION: 'session:1', REX_BLOCK: 'block:me' }, argv => {
      if (argv[0] === 'rex' && argv[1] === 'window') return ok(REX)
      if (argv[0] === 'sh' && argv[2]?.includes('decisions-register')) return argv[4] === 'spj' ? ok(NOTES.replace('|---|---|---|---|\n', '|---|---|---|---|\n| 1 | [claude-plugins#89](https://github.com/FunDrivenDev/claude-plugins/pull/89) | ✅ | base merged |\n')) : fail
      if (argv[0] === 'gh' && argv[1] === 'pr') return ok('{"state":"MERGED","isDraft":false,"red":0}')
      return undefined
    })
    await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
    await settle()
    const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
    // The ✅ row agrees with gh and stays fresh; the 🔧 row, its PR merged, alone shows stale.
    expect(await ui.find({ text: /base merged/ })).toBeDefined()
    const stale = await ui.findAll({ type: 'Text', text: /^stale: / })
    expect(stale).toHaveLength(1)
    expect(JSON.stringify(stale[0])).toContain('stale: merged')
    expect(JSON.stringify(stale[0])).toContain('#e5c890')
    expect(await ui.find({ text: /worker running/ })).toBeDefined()
    await ui.unmount()
  })

  test('a proposed decision and an open question show cut to one line, and a press shows the whole of them, the decision with its Why:', ON, async ($, on) => {
    const decision = "Keep the `gh pr ready` guard as it is, read gh's stdout once per call and cache the verdict for the rest of the turn, so that a stacked PR's parent is only asked once."
    const question = 'Should the AFK relay retry a handover that failed to load within its wait, or stop and notify with the resume message?'
    const notes = NOTES.replace('## Q1 — Which name?', `## Q1 — ${question}`).replace(
      '- **D01** `proposed` — Name it Situation.\n',
      `- **D01** \`proposed\` — ${decision}\n  Why: one read of gh per turn keeps the guard fast. By: Claude, 2026-11-18. Src: brief. Also in: —\n`,
    )
    start(on, { REX_SESSION: 'session:1', REX_BLOCK: 'block:me' }, argv => {
      if (argv[0] === 'rex' && argv[1] === 'window') return ok(REX)
      if (argv[0] === 'sh' && argv[2]?.includes('decisions-register')) return argv[4] === 'spj' ? ok(notes) : fail
      return undefined
    })
    await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
    await settle()
    const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
    const row = async (text: string) => (await ui.findAll({ type: 'Text', text })).map(t => t.props.wrap)
    expect((await ui.find({ key: 'sit:d:0:D01:fold' }))?.props.label).toBe('▸ D01')
    expect(await row(` ${decision}`)).toEqual(['truncate-end'])
    expect(await ui.find({ text: /^Why: / })).toBeUndefined()

    await ui.press({ key: 'sit:d:0:D01:fold' })
    expect((await ui.find({ key: 'sit:d:0:D01:fold' }))?.props.label).toBe('▾ D01')
    expect(await row(decision)).toEqual(['wrap'])
    expect(await row('Why: one read of gh per turn keeps the guard fast.')).toEqual(['wrap'])

    // One row is open at a time: opening the question closes the decision.
    expect((await ui.find({ key: 'sit:q:0:Q1:fold' }))?.props.label).toBe('▸ Q1')
    await ui.press({ key: 'sit:q:0:Q1:fold' })
    expect(await row(question)).toEqual(['wrap'])
    expect((await ui.find({ key: 'sit:d:0:D01:fold' }))?.props.label).toBe('▸ D01')
    expect(await ui.find({ text: /^Why: / })).toBeUndefined()

    await ui.press({ key: 'sit:q:0:Q1:fold' })
    expect((await ui.find({ key: 'sit:q:0:Q1:fold' }))?.props.label).toBe('▸ Q1')
    expect(await row(` ${question}`)).toEqual(['truncate-end'])
    await ui.unmount()
  })

  test('without a topic the section says so', ON, async ($, on) => {
    start(on, {}, () => undefined)
    await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
    await settle()
    const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
    expect(await ui.find({ text: /^No topic: / })).toBeDefined()
    await ui.unmount()
  })

  test('a terminal session label no note names gives no topic, until the session reads a note that names one; its CLI and gh down show as such', ON, async ($, on) => {
    start(on, { REX_SESSION: 'session:1', REX_BLOCK: 'block:me' }, argv => {
      if (argv[0] === 'rex' && argv[1] === 'window') return ok(REX.replace('"label":"spj"', '"label":"Dispatch"'))
      if (argv[0] === 'rex' && argv[1] === 'ls') return fail
      if (argv[0] === 'sh' && argv[2]?.includes('decisions-register')) return argv[4] === 'spj' ? ok(NOTES.split('\x1e').slice(0, 2).join('\x1e')) : fail
      if (argv[0] === 'sh' && argv[2]?.includes('head -20 "$1"')) return ok('---\ntopic: spj\n---\n')
      if (argv[0] === 'gh') return fail
      return undefined
    })
    await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
    await settle()
    let ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
    expect(await ui.find({ text: /^No topic: / })).toBeDefined()
    await ui.unmount()

    await $.tool.call({ tool: 'Read', file_path: '/Users/me/Notes/claude/plans/26-11-16-spj-brief.md' } as never)
    await settle()
    ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
    expect(await ui.find({ text: /spj · notes/ })).toBeDefined()
    expect(await ui.find({ text: /gh unreachable/ })).toBeDefined()
    expect(await ui.find({ text: /^terminal sessions unreachable$/ })).toBeDefined()
    expect(await ui.find({ text: /^No open question\.$/ })).toBeDefined()
    expect(await ui.find({ text: /^No proposed decision\.$/ })).toBeDefined()
    await ui.unmount()
  })

  test('outside a terminal session, a topic from the notes has no workers and no merge plan to show', ON, async ($, on) => {
    start(on, {}, argv => {
      if (argv[0] === 'sh' && argv[2]?.includes('decisions-register')) return ok('\x1e/n/plans/26-11-16-spj-brief.md\t1000\n---\ntopic: spj\n---\n')
      if (argv[0] === 'sh' && argv[2]?.includes('head -20 "$1"')) return ok('---\ntopic: spj\n---\n')
      return undefined
    })
    await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
    await $.tool.call({ tool: 'Bash', command: 'cat ~/Notes/claude/plans/26-11-16-spj-brief.md' } as never)
    await settle()
    const ui = await $.ui.mount({ plugin: 'session-mods', surface: 'terminal', ...PANE })
    expect(await ui.find({ text: /spj · notes/ })).toBeDefined()
    expect(await ui.find({ text: /^No merge plan\.$/ })).toBeDefined()
    expect(await ui.find({ text: /^not in a terminal session$/ })).toBeDefined()
    await ui.unmount()
  })
})
