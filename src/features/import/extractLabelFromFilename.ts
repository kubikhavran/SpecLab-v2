import type { LabelExtractSettings } from '../../app/types/core'

function toAbsIndex(raw: number, fallback: number, length: number): number {
  if (!Number.isFinite(raw)) {
    return fallback
  }

  const value = Math.trunc(raw)
  return value < 0 ? length + value : value
}

function extractTokenFromFilename(
  filename: string,
  settings: LabelExtractSettings,
): string | null {
  switch (settings.preset) {
    case 'mv': {
      const match = filename.match(/(-?\d+(?:[.,]\d+)?)\s*mV/i)
      return match?.[1] ?? null
    }
    case 'firstNumber': {
      const match = filename.match(/-?\d+(?:[.,]\d+)?/)
      return match?.[0] ?? null
    }
    case 'lastNumber': {
      const matches = filename.match(/-?\d+(?:[.,]\d+)?/g)
      return matches && matches.length > 0
        ? matches[matches.length - 1]
        : null
    }
    case 'regex': {
      try {
        const regex = new RegExp(settings.regex ?? '', 'i')
        const match = filename.match(regex)
        return match?.[1] ?? null
      } catch {
        return null
      }
    }
    case 'slice': {
      const len = filename.length
      const startRaw = Number(settings.start)
      const endRaw = Number(settings.end)
      let start = toAbsIndex(startRaw, 0, len)
      let end = toAbsIndex(endRaw, len, len)

      start = Math.max(0, Math.min(len, start))
      end = Math.max(0, Math.min(len, end))

      if (end < start) {
        ;[start, end] = [end, start]
      }

      const raw = filename.slice(start, end)
      const trimmed = settings.trimResult ? raw.trim() : raw

      if (!settings.numbersOnly) {
        return trimmed.length > 0 ? trimmed : null
      }

      const numberToken = trimmed.match(/-?\d+(?:[.,]\d+)?/)?.[0] ?? ''
      return numberToken.length > 0 ? numberToken : null
    }
  }
}

export function extractLabelFromFilename(
  filename: string,
  settings: LabelExtractSettings,
): string | null {
  if (settings.mode !== 'filename') {
    return null
  }

  const token = extractTokenFromFilename(filename, settings)
  if (token === null) {
    return null
  }

  if (settings.preset === 'slice') {
    const prefix = settings.prefix.trim()
    return `${prefix}${token}${settings.suffix ?? ''}`
  }

  const normalizedToken = token.replace(/,/g, '.')
  const numericValue = Number(normalizedToken)
  if (!Number.isFinite(numericValue)) {
    return null
  }

  const formattedValue =
    Math.abs(numericValue - Math.round(numericValue)) < 1e-9
      ? String(Math.round(numericValue))
      : normalizedToken
  const prefix = settings.prefix.trim()

  return `${prefix}${formattedValue}${settings.suffix ?? ''}`
}
