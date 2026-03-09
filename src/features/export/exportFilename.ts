const WINDOWS_INVALID_FILENAME_RE = /[\\/:*?"<>|]/g
const REPEATED_WHITESPACE_RE = /\s+/g
const TRAILING_SPACES_OR_DOTS_RE = /[. ]+$/g
const MAX_FILENAME_BASE_LENGTH = 80

function stripControlCharacters(value: string): string {
  return Array.from(value, (character) =>
    character.charCodeAt(0) < 32 ? ' ' : character,
  ).join('')
}

export function sanitizeExportBaseName(rawName: string): string {
  const withoutControls = stripControlCharacters(rawName)
  const cleaned = withoutControls
    .replace(WINDOWS_INVALID_FILENAME_RE, ' ')
    .replace(REPEATED_WHITESPACE_RE, ' ')
    .trim()
    .replace(TRAILING_SPACES_OR_DOTS_RE, '')

  const truncated = cleaned.slice(0, MAX_FILENAME_BASE_LENGTH).trim()
  return truncated.replace(TRAILING_SPACES_OR_DOTS_RE, '')
}

export function getExportFilename(
  baseName: string,
  extension: string,
  fallbackBaseName: string,
): string {
  const normalizedExtension = extension.replace(/^\./, '').toLowerCase()
  const sanitizedBase = sanitizeExportBaseName(baseName)
  const sanitizedFallback = sanitizeExportBaseName(fallbackBaseName)
  const resolvedBase = sanitizedBase || sanitizedFallback || 'preset'
  const expectedSuffix = `.${normalizedExtension}`

  if (resolvedBase.toLowerCase().endsWith(expectedSuffix)) {
    return resolvedBase
  }

  return `${resolvedBase}${expectedSuffix}`
}
