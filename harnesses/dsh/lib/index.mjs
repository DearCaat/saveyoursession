/**
 * SaveYourSession entry point for DeepSeek Harness.
 *
 * DSH plugins are namespace modules: the bundle patch mounts this module and
 * `apply()` registers commands in the host.  Commands are deliberately thin
 * wrappers around the shared Python manager so native session formats remain
 * owned by the common implementation.
 */
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineTool } from '@deepseek-ai/dsh-tools'

export const name = 'saveyoursession-dsh'
export const inject = ['commands', 'tools']

const HERE = dirname(fileURLToPath(import.meta.url))
const PACKAGE_ROOT = resolve(HERE, '..')

function managerPath() {
  const configured = process.env.SAVEYOURSESSION_MANAGER
  if (configured) return configured
  // Source checkout: harnesses/dsh/lib -> plugin/scripts/manager.py.
  return resolve(PACKAGE_ROOT, '..', '..', 'scripts', 'manager.py')
}

function parseFlags(raw = '') {
  const flags = {}
  const tokens = raw.trim().split(/\s+/u).filter(Boolean)
  for (let i = 0; i < tokens.length; i += 1) {
    const token = tokens[i]
    if (!token.startsWith('--')) continue
    const body = token.slice(2)
    const eq = body.indexOf('=')
    if (eq >= 0) flags[body.slice(0, eq)] = body.slice(eq + 1)
    else if (tokens[i + 1] && !tokens[i + 1].startsWith('--')) flags[body] = tokens[++i]
    else flags[body] = true
  }
  return flags
}

function runManager(args) {
  const script = managerPath()
  if (!existsSync(script)) {
    return Promise.reject(new Error(`SaveYourSession manager not found: ${script}. Set SAVEYOURSESSION_MANAGER.`))
  }
  return new Promise((resolvePromise, reject) => {
    const python = process.env.PYTHON ?? (process.platform === 'win32' ? 'python' : 'python3')
    const child = spawn(python, [script, ...args], {
      env: process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', chunk => { stdout += chunk })
    child.stderr.on('data', chunk => { stderr += chunk })
    child.once('error', reject)
    child.once('close', code => {
      if (code !== 0) return reject(new Error(stderr.trim() || `manager exited with code ${code}`))
      try { resolvePromise(JSON.parse(stdout)) }
      catch { resolvePromise(stdout.trim()) }
    })
  })
}

function success(value) {
  return { kind: 'success', text: typeof value === 'string' ? value : JSON.stringify(value, null, 2) }
}

export function apply(ctx) {
  const command = (name_, description, handler, input) => {
    ctx.commands.register({ name: name_, description, ...(input ? { input: { hint: input } } : {}), handler })
  }

  command('save-session-list', 'List native sessions across all harnesses (or one harness)', async invocation => {
    const f = parseFlags(invocation.rawInput)
    const args = ['list']
    if (typeof f.harness === 'string') args.push('--harness', f.harness)
    if (typeof f.limit === 'string') args.push('--limit', f.limit)
    return success(await runManager(args))
  }, '[--harness codex|claude|grok-build|dsh] [--limit N]')

  command('save-session-search', 'Search native session metadata and content across harnesses', async invocation => {
    const query = invocation.rawInput.trim()
    if (!query) throw new Error('usage: /save-session-search <query>')
    return success(await runManager(['search', query]))
  }, '<query>')

  command('save-session-sync', 'Sync one session or all sessions to the local archive and HF Dataset', async invocation => {
    const f = parseFlags(invocation.rawInput)
    const args = ['sync']
    if (typeof f.harness === 'string') args.push('--harness', f.harness)
    if (typeof f['session-id'] === 'string') args.push('--session-id', f['session-id'])
    return success(await runManager(args))
  }, '[--harness H] [--session-id ID]')

  command('save-session-restore', 'Restore an archived session into its native harness directory', async invocation => {
    const tokens = invocation.rawInput.trim().split(/\s+/u).filter(Boolean)
    if (tokens.length < 2) throw new Error('usage: /save-session-restore <harness> <session-id> [--target-root PATH]')
    const [harness, sessionId] = tokens
    const f = parseFlags(tokens.slice(2).join(' '))
    const args = ['restore', harness, sessionId]
    if (typeof f['target-root'] === 'string') args.push('--target-root', f['target-root'])
    return success(await runManager(args))
  }, '<harness> <session-id> [--target-root PATH]')

  // Model-facing tools.  DSH agents call these directly; the slash commands
  // above remain a convenient host/interactive alias and share the same bridge.
  const output = {
    schema: {},
    render: (_args, value) => [{ type: 'text', text: typeof value === 'string' ? value : JSON.stringify(value, null, 2) }],
  }
  ctx.tools.register(defineTool({
    name: 'save_session_list',
    description: 'List native sessions across Codex, Claude, Grok Build, and DSH.',
    parameters: { harness: { type: 'string', description: 'Optional harness filter.' }, limit: { type: 'integer', description: 'Maximum number of rows.' } },
    output,
    execute: args => runManager(['list', ...(args.harness ? ['--harness', args.harness] : []), ...(args.limit === undefined ? [] : ['--limit', String(args.limit)])]),
  }))
  ctx.tools.register(defineTool({
    name: 'save_session_search',
    description: 'Search session metadata and native content across all harnesses.',
    parameters: { query: { type: 'string', required: true, description: 'Text to search for.' } },
    output,
    execute: args => runManager(['search', args.query]),
  }))
  ctx.tools.register(defineTool({
    name: 'save_session_sync',
    description: 'Archive native sessions locally and mirror new files to the configured HF Dataset.',
    parameters: { harness: { type: 'string', description: 'Optional harness filter.' }, session_id: { type: 'string', description: 'Optional native session id.' } },
    output,
    execute: args => runManager(['sync', ...(args.harness ? ['--harness', args.harness] : []), ...(args.session_id ? ['--session-id', args.session_id] : [])]),
  }))
  ctx.tools.register(defineTool({
    name: 'save_session_restore',
    description: 'Restore an archived session into the matching native harness directory.',
    parameters: { harness: { type: 'string', required: true, description: 'codex, claude, grok-build, or dsh.' }, session_id: { type: 'string', required: true, description: 'Native session id.' }, target_root: { type: 'string', description: 'Optional destination directory.' } },
    output,
    execute: args => runManager(['restore', args.harness, args.session_id, ...(args.target_root ? ['--target-root', args.target_root] : [])]),
  }))
}
