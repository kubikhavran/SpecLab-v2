import type { Spectrum } from '../../app/types/core'

type DelimiterKey = 'comma' | 'semicolon' | 'tab' | 'whitespace'

type DelimiterOption = {
  key: DelimiterKey
  split: (line: string) => string[]
}

const DELIMITER_OPTIONS: DelimiterOption[] = [
  { key: 'comma', split: (line) => line.split(',') },
  { key: 'semicolon', split: (line) => line.split(';') },
  { key: 'tab', split: (line) => line.split('\t') },
  { key: 'whitespace', split: (line) => line.split(/\s+/) },
]

const COMMENT_PREFIXES = ['#', '//', ';']
const DELIMITER_SAMPLE_SIZE = 50

function isCommentLine(line: string): boolean {
  return COMMENT_PREFIXES.some((prefix) => line.startsWith(prefix))
}

function normalizeToken(token: string): string {
  const trimmed = token.trim().replace(/^"(.*)"$/, '$1').replace(/^'(.*)'$/, '$1')

  if (trimmed.includes(',') && !trimmed.includes('.')) {
    return trimmed.replace(/,/g, '.')
  }

  return trimmed
}

function parseNumberToken(token: string): number | null {
  const normalized = normalizeToken(token)

  if (normalized.length === 0) {
    return null
  }

  const value = Number(normalized)
  return Number.isFinite(value) ? value : null
}

function extractFirstPair(
  line: string,
  delimiter: DelimiterOption,
): [number, number] | null {
  const tokens = delimiter.split(line)
  const values: number[] = []

  for (const token of tokens) {
    const parsed = parseNumberToken(token)

    if (parsed === null) {
      continue
    }

    values.push(parsed)

    if (values.length === 2) {
      return [values[0], values[1]]
    }
  }

  return null
}

function detectDelimiter(lines: string[]): DelimiterOption {
  const sampleLines = lines.slice(0, DELIMITER_SAMPLE_SIZE)
  let bestOption = DELIMITER_OPTIONS[0]
  let bestScore = -1

  for (const option of DELIMITER_OPTIONS) {
    let score = 0

    for (const line of sampleLines) {
      if (extractFirstPair(line, option) !== null) {
        score += 1
      }
    }

    if (score > bestScore) {
      bestScore = score
      bestOption = option
    }
  }

  return bestOption
}

function isStrictlyMonotonic(values: number[]): boolean {
  if (values.length < 2) {
    return true
  }

  let strictlyIncreasing = true
  let strictlyDecreasing = true

  for (let i = 1; i < values.length; i += 1) {
    if (values[i] <= values[i - 1]) {
      strictlyIncreasing = false
    }

    if (values[i] >= values[i - 1]) {
      strictlyDecreasing = false
    }
  }

  return strictlyIncreasing || strictlyDecreasing
}

function getSpectrumName(fileName: string): string {
  const trimmedName = fileName.trim()
  const dotIndex = trimmedName.lastIndexOf('.')

  if (dotIndex > 0) {
    return trimmedName.slice(0, dotIndex)
  }

  return trimmedName.length > 0 ? trimmedName : 'Imported spectrum'
}

function createSpectrumId(): string {
  if (
    typeof globalThis.crypto !== 'undefined' &&
    typeof globalThis.crypto.randomUUID === 'function'
  ) {
    return globalThis.crypto.randomUUID()
  }

  return `sp_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

export function parseSpectrumText(text: string, fileName: string): Spectrum {
  const parsedLines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !isCommentLine(line))

  if (parsedLines.length === 0) {
    throw new Error(
      `No data rows found in "${fileName}". The file may be empty or comments only.`,
    )
  }

  const delimiter = detectDelimiter(parsedLines)
  const pairs: Array<[number, number]> = []

  for (const line of parsedLines) {
    const pair = extractFirstPair(line, delimiter)

    if (pair !== null) {
      pairs.push(pair)
    }
  }

  const filteredPairs = pairs.filter(
    ([xValue, yValue]) => Number.isFinite(xValue) && Number.isFinite(yValue),
  )

  if (filteredPairs.length < 2) {
    throw new Error(
      `Could not parse at least two numeric points from "${fileName}". Check delimiter and columns.`,
    )
  }

  if (!isStrictlyMonotonic(filteredPairs.map(([xValue]) => xValue))) {
    filteredPairs.sort((a, b) => a[0] - b[0])
  }

  const x = filteredPairs.map(([xValue]) => xValue)
  const y = filteredPairs.map(([, yValue]) => yValue)

  if (x.length !== y.length) {
    throw new Error(
      `Parsed x/y arrays have inconsistent lengths for "${fileName}".`,
    )
  }

  return {
    id: createSpectrumId(),
    name: getSpectrumName(fileName),
    x,
    y,
    meta: {
      sourceFile: fileName,
      points: x.length,
      delimiter: delimiter.key,
      parsedAt: new Date().toISOString(),
    },
  }
}
