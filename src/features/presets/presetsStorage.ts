import type { Preset, PresetPayload } from '../../app/types/core'
import { downloadTextFile } from '../../lib/downloadTextFile'

const PRESETS_STORAGE_KEY = 'speclab.presets.v1'

export const PRESETS_FILE_NAME = 'speclab-presets.json'
const WINDOWS_INVALID_FILENAME_RE = /[<>:"/\\|?*]/g
const FILENAME_WHITESPACE_RE = /\s+/g
const FILENAME_TRAILING_DOTS_RE = /[. ]+$/g
const MAX_FILENAME_LENGTH = 80

type PresetsStorageEnvelope = {
  version: 1
  presets: Preset[]
  activePresetId: string | null
}

type PresetsFileEnvelope = {
  schemaVersion: 1
  app: 'SpecLab'
  exportedAt: string
  presets: unknown[]
}

type PresetsState = {
  presets: Preset[]
  activePresetId: string | null
}

export type ImportedPresetCandidate = {
  id: string
  name: string
  payload: unknown
  createdAt?: number
  updatedAt?: number
}

const EMPTY_PRESETS_STATE: PresetsState = {
  presets: [],
  activePresetId: null,
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isPayload(value: unknown): value is PresetPayload {
  if (!isObject(value)) {
    return false
  }

  return (
    (value.themeMode === 'system' ||
      value.themeMode === 'light' ||
      value.themeMode === 'dark') &&
    isObject(value.plot) &&
    isObject(value.graphics) &&
    isObject(value.baseline) &&
    isObject(value.smoothing) &&
    isObject(value.cosmic) &&
    isObject(value.dataLabeling) &&
    (value.peaksSettings === undefined || isObject(value.peaksSettings))
  )
}

function isPreset(value: unknown): value is Preset {
  if (!isObject(value)) {
    return false
  }

  return (
    typeof value.id === 'string' &&
    value.id.length > 0 &&
    typeof value.name === 'string' &&
    Number.isFinite(value.createdAt) &&
    Number.isFinite(value.updatedAt) &&
    isPayload(value.payload)
  )
}

export function serializePresetsForFile(presets: Preset[]): string {
  const payload: PresetsFileEnvelope = {
    schemaVersion: 1,
    app: 'SpecLab',
    exportedAt: new Date().toISOString(),
    presets,
  }

  return JSON.stringify(payload, null, 2)
}

export function sanitizeFilename(name: string): string {
  const withoutControlChars = Array.from(name, (char) =>
    char.charCodeAt(0) < 32 ? ' ' : char,
  ).join('')
  const cleaned = withoutControlChars
    .replace(WINDOWS_INVALID_FILENAME_RE, ' ')
    .replace(FILENAME_WHITESPACE_RE, ' ')
    .trim()
    .replace(FILENAME_TRAILING_DOTS_RE, '')

  const truncated = cleaned.slice(0, MAX_FILENAME_LENGTH).trim()
  const normalized = truncated.replace(FILENAME_TRAILING_DOTS_RE, '')

  return normalized.length > 0 ? normalized : 'preset'
}

function normalizeJsonFileName(fileName: string): string {
  const withoutExtension = fileName.trim().replace(/\.json$/i, '')
  return `${sanitizeFilename(withoutExtension)}.json`
}

export function exportPresetsToJsonFile(
  presets: Preset[],
  fileName: string = PRESETS_FILE_NAME,
): void {
  const serialized = serializePresetsForFile(presets)
  const resolvedFileName = normalizeJsonFileName(fileName)

  downloadTextFile(
    resolvedFileName,
    serialized,
    'application/json;charset=utf-8',
  )
}

export function parsePresetsFromFile(text: string): ImportedPresetCandidate[] {
  let parsed: unknown

  try {
    parsed = JSON.parse(text)
  } catch {
    throw new Error('Invalid JSON file.')
  }

  if (!isObject(parsed)) {
    throw new Error('Invalid presets file format.')
  }

  if (parsed.schemaVersion !== 1) {
    throw new Error('Unsupported presets file version.')
  }

  if (parsed.app !== 'SpecLab') {
    throw new Error('Unsupported presets file app.')
  }

  if (!Array.isArray(parsed.presets)) {
    throw new Error('Invalid presets file: "presets" must be an array.')
  }

  const imported: ImportedPresetCandidate[] = []
  for (const entry of parsed.presets) {
    if (!isObject(entry)) {
      continue
    }

    const id = typeof entry.id === 'string' ? entry.id : ''
    const name = typeof entry.name === 'string' ? entry.name : ''
    const payload = entry.payload

    if (id.length === 0 || name.length === 0 || !isObject(payload)) {
      continue
    }

    imported.push({
      id,
      name,
      payload,
      createdAt: Number.isFinite(entry.createdAt) ? Number(entry.createdAt) : undefined,
      updatedAt: Number.isFinite(entry.updatedAt) ? Number(entry.updatedAt) : undefined,
    })
  }

  if (imported.length === 0 && parsed.presets.length > 0) {
    throw new Error('No valid presets found in the file.')
  }

  return imported
}

export function loadPresetsFromStorage(): PresetsState {
  if (typeof window === 'undefined') {
    return EMPTY_PRESETS_STATE
  }

  try {
    const raw = window.localStorage.getItem(PRESETS_STORAGE_KEY)
    if (!raw) {
      return EMPTY_PRESETS_STATE
    }

    const parsed: unknown = JSON.parse(raw)
    if (!isObject(parsed) || parsed.version !== 1 || !Array.isArray(parsed.presets)) {
      return EMPTY_PRESETS_STATE
    }

    const presets = parsed.presets.filter(isPreset)
    const activePresetId =
      typeof parsed.activePresetId === 'string' &&
      presets.some((preset) => preset.id === parsed.activePresetId)
        ? parsed.activePresetId
        : null

    return {
      presets,
      activePresetId,
    }
  } catch {
    return EMPTY_PRESETS_STATE
  }
}

export function savePresetsToStorage(
  presets: Preset[],
  activePresetId: string | null,
) {
  if (typeof window === 'undefined') {
    return
  }

  const payload: PresetsStorageEnvelope = {
    version: 1,
    presets,
    activePresetId,
  }

  try {
    window.localStorage.setItem(PRESETS_STORAGE_KEY, JSON.stringify(payload))
  } catch {
    // Ignore persistence failures in restricted browser modes.
  }
}
