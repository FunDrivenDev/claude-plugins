import type { Register } from 'claude-code'

import { afterStepBar, beforeStepBar, registerBar, startBar } from './bar'
import { registerPanel, startPanel, stepPanel } from './panel'

/**
 * The plugin's one hooks module: the side pane (`panel.tsx`) and the bar beneath
 * the prompt (`bar.tsx`). Each hooks its own events; the two both need,
 * `session.start` and `turn.step`, are hooked once here and run both mods' work.
 */
export const register: Register = (on, options) => {
  registerPanel(on)
  registerBar(on, options)

  /** Each mod starts even when the other fails; the first failure is then rethrown, so the engine reports the hook as skipped. */
  on('session.start', async ($, e, next) => {
    const failures: unknown[] = []
    await startPanel($, e).catch((error: unknown) => failures.push(error))
    await startBar($, e).catch((error: unknown) => failures.push(error))
    if (failures.length) throw failures[0]
    return next(e)
  })

  on('turn.step', async function* ($, e, next) {
    await beforeStepBar($, e)
    const result = yield* stepPanel($, e, next)
    await afterStepBar($, e)
    return result
  })
}
