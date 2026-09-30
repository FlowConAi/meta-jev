import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

const entrypoint = process.argv[2]
if (!entrypoint) {
  process.stderr.write('Jevc module entrypoint is required\n')
  process.exit(2)
}
const { runReducer, validateProgram } = await import(pathToFileURL(entrypoint).href)

const input = JSON.parse(readFileSync(0, 'utf8'))
const issues = validateProgram(input.program)
if (issues.some((issue) => issue.severity === 'error')) {
  process.stderr.write(`${JSON.stringify({ issues })}\n`)
  process.exitCode = 2
} else {
  process.stdout.write(`${JSON.stringify({ verdict: runReducer(input.program, input.answers) })}\n`)
}
