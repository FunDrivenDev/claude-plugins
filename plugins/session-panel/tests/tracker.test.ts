import { describe, expect, test } from 'claude-code/testing'

import { findRefs, linearOfResult, prState, refsOfGh, repoOfRemote, titleOfSlug } from '../hooks/tracker'

describe('tracker references', () => {
  test('reads issues and pull requests from prompts and gh commands', async () => {
    const home = 'FunDrivenDev/defactory'
    expect(repoOfRemote('git@github.com:FunDrivenDev/defactory.git')).toBe(home)
    expect(findRefs('then push it to claude-plugins#7', home)).toEqual([
      { platform: 'github', repo: 'FunDrivenDev/claude-plugins', number: 7, type: null },
    ])
    expect(findRefs('see https://github.com/o/r/issues/12 and #3', home)).toEqual([
      { platform: 'github', repo: 'o/r', number: 12, type: 'issue' },
      { platform: 'github', repo: home, number: 3, type: null, isBare: true },
    ])
    expect(findRefs('fix https://linear.app/gs/issue/GS-42/fix-the-login', home)).toEqual([
      { platform: 'linear', workspace: 'gs', id: 'GS-42', slug: 'fix-the-login' },
    ])
    expect(refsOfGh('gh pr create --draft --title x', 'https://github.com/o/r/pull/9\n', home)).toEqual({
      refs: [{ platform: 'github', repo: 'o/r', number: 9, type: 'pull' }],
      rank: 1,
    })
    expect(refsOfGh('gh pr view 7 --repo o/r --json state', '', home)?.refs).toEqual([
      { platform: 'github', repo: 'o/r', number: 7, type: 'pull' },
    ])
    expect(refsOfGh('gh pr list', '', home)).toBeNull()
    expect(linearOfResult('{"identifier":"GS-1","title":"Login","url":"https://linear.app/gs/issue/GS-1/login"}')?.title).toBe('Login')
    expect(titleOfSlug('fix-the-login')).toBe('Fix the login')
    expect(prState({ state: 'open', draft: true })).toBe('draft')
    expect(prState({ state: 'closed', merged: true })).toBe('merged')
  })
})
