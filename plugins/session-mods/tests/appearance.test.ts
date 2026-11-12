import { describe, expect, test } from 'claude-code/testing'

import { duration, herdrScheme, prettyModel, recolor } from '../hooks/appearance'

describe('appearance', () => {
  test("Herdr's pinned appearance wins, and an unset or broken one leaves the choice to the OS", () => {
    expect(herdrScheme('{"appearance":"light","theme":{"light":"catppuccin-latte"}}')).toBe('light')
    expect(herdrScheme('{"appearance":"dark"}')).toBe('dark')
    expect(herdrScheme('{"zoom":1}')).toBeNull()
    expect(herdrScheme('{"appearance":"system"}')).toBeNull()
    expect(herdrScheme('null')).toBeNull()
    expect(herdrScheme('{not json')).toBeNull()
  })

  test('names models and durations calmly', () => {
    expect(prettyModel('claude-opus-5-5')).toBe('Opus 5.5')
    expect(prettyModel('claude-haiku-4-5-20251001')).toBe('Haiku 4.5')
    expect(prettyModel('gpt-x')).toBe('gpt-x')
    expect(duration(3_725_000)).toBe('1h02m')
    expect(duration(65_000)).toBe('1m05s')
    expect(duration(-5)).toBe('0s')
  })

  test('swap each colour for its light twin on a light appearance, and leave the dark one alone', () => {
    const tree = {
      type: 'Box',
      props: { borderColor: '#a6d189' },
      children: [{ type: 'Text', props: { color: '#ffff00', bold: true }, hover: { color: '#e78284' }, children: ['#ffff00'] }],
    }
    expect(recolor(tree, 'dark')).toBe(tree)
    expect(recolor(tree, 'light')).toEqual({
      type: 'Box',
      props: { borderColor: '#40a02b' },
      children: [{ type: 'Text', props: { color: '#9a6700', bold: true }, hover: { color: '#d20f39' }, children: ['#ffff00'] }],
    })
  })

  test('the pane and the bar share one palette, Linear and GitHub colours included', () => {
    const light = (color: string) => recolor({ type: 'Text', props: { color } }, 'light').props.color
    expect(light('#e5c890')).toBe('#9a6700')
    expect(light('#ffc107')).toBe('#9a6700')
    expect(light('#3fb950')).toBe('#1a7f37')
    expect(light('#5e6ad2')).toBe('#4c55b8')
    expect(light('#123456')).toBe('#123456')
  })
})
