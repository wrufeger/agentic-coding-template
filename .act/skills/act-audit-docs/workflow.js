export const meta = {
  name: 'act-audit-docs',
  description: 'Audit docs/project against the code: per doc area an explorer, then a doc-writer bound to that area; areas in parallel, docs/README.md last',
  whenToUse: 'Claude Code only, and only when the human explicitly asks for the workflow variant of act-audit-docs',
  phases: [
    { title: 'Explore', detail: 'one explorer per doc area, read-only' },
    { title: 'Correct', detail: 'one doc-writer per doc area, writes only its own files' },
    { title: 'Index', detail: 'one doc-writer updates docs/README.md' },
  ],
}

// args: {date: 'YYYY-MM-DD', areas: [{name, docs: [...], code?: [...], focus?}], wave?: string, readme?: false}
// A doc path is a file or a folder (ending in / or /**) under docs/project/. No path may sit in two areas:
// the check that compares parallel workers' write scopes does not see workflow agents, so this script does.

const MAX_AREAS = 12
const DOCS_ROOT = 'docs/project'
const README = 'docs/README.md'

const RESULT_SCHEMA = {
  type: 'object',
  properties: {
    changed: { type: 'array', items: { type: 'string' }, description: 'files edited, relative to the project root' },
    corrections: { type: 'array', items: { type: 'string' }, description: 'one line per corrected claim: file, old -> new, evidence <path>:<line>' },
    code_findings: { type: 'array', items: { type: 'string' }, description: 'mismatches that need a code change, not a doc edit' },
    unverified: { type: 'array', items: { type: 'string' }, description: 'doc claims the report did not cover, left unchanged' },
  },
  required: ['changed', 'corrections', 'code_findings', 'unverified'],
}

function fail(message) {
  throw new Error(`act-audit-docs workflow: ${message}`)
}

function docBase(areaName, raw) {
  if (typeof raw !== 'string' || !raw.trim()) fail(`area "${areaName}": a doc path must be a non-empty string, got ${JSON.stringify(raw)}`)
  const path = raw.trim()
  if (path.includes('\\') || path.startsWith('/') || /^[A-Za-z]:/.test(path)) {
    fail(`area "${areaName}": "${path}" must be relative to the project root, with / as separator`)
  }
  const base = path.replace(/\/\*\*$/, '').replace(/\/$/, '')
  const segments = base.split('/')
  // a comma would split the Write scope line into two patterns, a backtick or line break would reshape it;
  // Windows drops a trailing dot or space, so "a.md." would be a second name for "a.md"
  if (segments.some(s => s === '' || s === '.' || s === '..' || /[. ]$/.test(s)) || !/^[\p{L}\p{N} ._()[\]\/-]+$/u.test(base)) {
    fail(`area "${areaName}": "${path}" must name a file or a folder (ending in / or /**): letters, digits, space and . _ - ( ) [ ] only, no wildcards, no segment that is . or .. or ends in a dot or space`)
  }
  if (base !== DOCS_ROOT && !base.startsWith(`${DOCS_ROOT}/`)) {
    fail(`area "${areaName}": "${path}" is outside ${DOCS_ROOT}/ (${README} is the last step's alone)`)
  }
  return base
}

function oneLine(text) {
  return String(text).replace(/\s+/g, ' ').trim()
}

// case-blind: Windows and macOS file systems are, and so is the hook's pattern match on Windows
function overlaps(a, b) {
  const [x, y] = [a.toLowerCase(), b.toLowerCase()]
  return x === y || x.startsWith(`${y}/`) || y.startsWith(`${x}/`)
}

function readAreas(input) {
  if (!input || typeof input !== 'object') fail('args missing: {date, areas: [...]}')
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(input.date || ''))) fail(`args.date must be YYYY-MM-DD, got "${input.date}"`)
  const list = input.areas
  if (!Array.isArray(list) || list.length === 0) fail('args.areas must be a non-empty array')
  if (list.length > MAX_AREAS) fail(`${list.length} areas, at most ${MAX_AREAS} per run: split the pass into two runs`)
  const areas = []
  const owner = []  // [base, area name] for every doc path seen so far
  for (const item of list) {
    const name = item && typeof item.name === 'string' ? item.name.trim() : ''
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(name)) fail(`area name "${name}" must be one word (letters, digits, . _ -)`)
    if (areas.some(a => a.name === name)) fail(`area "${name}" appears twice`)
    if (!Array.isArray(item.docs) || item.docs.length === 0) fail(`area "${name}": docs must be a non-empty array`)
    const docs = []
    for (const raw of item.docs) {
      const base = docBase(name, raw)
      const clash = owner.find(([other]) => overlaps(base, other))
      if (clash) fail(`"${raw.trim()}" (area "${name}") overlaps "${clash[0]}" (area "${clash[1]}"): cut the areas by file`)
      owner.push([base, name])
      docs.push(raw.trim())
    }
    const code = Array.isArray(item.code) ? item.code.map(oneLine).filter(Boolean) : []
    const focus = typeof item.focus === 'string' ? oneLine(item.focus) : ''
    areas.push({ name, docs, code, focus })
  }
  return areas
}

function explorerPrompt(area) {
  return [
    'Tier: standard · Estimate: 15–30 tool calls · Cap: 40',
    'Write scope: none',
    '',
    `act-audit-docs, doc area "${area.name}", explorer step. Establish what actually exists in the code for this area: modules, endpoints, tables, commands, tests, configuration.`,
    ...(area.focus ? [`Focus: ${area.focus}`] : []),
    `The docs of this area (${area.docs.join(', ')}) only tell you which claims to check: report the code, not the docs.`,
    area.code.length ? `Start from: ${area.code.join(', ')}` : 'Find the relevant code yourself.',
    ...(args.wave ? [`Recent changes to cover: ${oneLine(args.wave)}`] : []),
    'Back every fact with <path>:<line>, and say plainly what you looked for and did not find. At most 40 lines, no raw dumps. Change nothing.',
  ].join('\n')
}

function writerPrompt(area, report) {
  return [
    'Tier: standard · Estimate: 10–25 tool calls · Cap: 40',
    `Write scope: ${area.docs.join(', ')}`,
    '',
    `act-audit-docs, doc area "${area.name}", doc-writer step. Compare the explorer report below against ${area.docs.join(', ')} and correct those files directly, so they describe the actual state, never the plan.`,
    ...(area.focus ? [`Focus: ${area.focus}`] : []),
    `- Edit nothing outside the Write scope above, ${README} included: a later step updates it.`,
    '- Change only what the report backs with <path>:<line>. A claim it does not cover stays as it is and goes under unverified.',
    '- A mismatch that needs a code change is not worked around in the docs: list it under code_findings.',
    '- In testing.md, check that the runner it names exists and that its command is not interactive.',
    '- Write in the project\'s docs language (language-docs in docs/ai/config.md).',
    '',
    'Explorer report:',
    report,
  ].join('\n')
}

function readmePrompt(changed) {
  return [
    'Tier: standard · Estimate: 3–8 tool calls · Cap: 15',
    `Write scope: ${README}`,
    '',
    `act-audit-docs, index step. Update ${README}: its index entries and data-as-of dates (${args.date}) for these files, changed in this pass:`,
    ...changed.map(path => `- ${path}`),
    'Nothing else changes. Report the file under changed, and every entry you could not match under unverified.',
  ].join('\n')
}

const areas = readAreas(args)
log(`${areas.length} doc area(s): ${areas.map(a => a.name).join(', ')}`)

const results = await pipeline(
  areas,
  area => agent(explorerPrompt(area), { label: `explore:${area.name}`, phase: 'Explore', agentType: 'explorer' }),
  (report, area) => (typeof report === 'string' && report.trim()
    ? agent(writerPrompt(area, report), { label: `correct:${area.name}`, phase: 'Correct', agentType: 'doc-writer', schema: RESULT_SCHEMA })
    : null),
)

const done = areas.map((area, i) => (results[i]
  ? { name: area.name, docs: area.docs, ...results[i] }
  : { name: area.name, docs: area.docs, skipped: true }))
const skipped = done.filter(a => a.skipped).map(a => a.name)
if (skipped.length) log(`no result for: ${skipped.join(', ')}; check these areas by hand`)

const changed = [...new Set(done.flatMap(a => a.changed || []))]
let readme = null
if (args.readme === false) log(`${README} left out (readme: false)`)
else if (!changed.length) log(`no doc changed, ${README} left as it is`)
else readme = await agent(readmePrompt(changed), { label: 'index:README', phase: 'Index', agentType: 'doc-writer', schema: RESULT_SCHEMA })

return { areas: done, readme, changed, skipped }
