import type {
  AppState,
  BaselineSettings,
  CosmicSettings,
  DataLabelingSettings,
  ExportSettings,
  GraphicsSettings,
  Peak,
  PeaksSettings,
  Preset,
  PresetPayload,
  PlotSettings,
  SmoothingSettings,
  Spectrum,
  ThemeMode,
} from '../types/core'
import {
  DEFAULT_DATA_LABELING_SETTINGS,
  DEFAULT_LABEL_EXTRACT_SETTINGS,
  DEFAULT_PEAKS_SETTINGS,
} from '../types/core'
import { extractLabelFromFilename } from '../../features/import/extractLabelFromFilename'

export type Action =
  | { type: 'THEME_SET'; mode: ThemeMode }
  | { type: 'SPECTRUM_ADD'; spectrum: Spectrum }
  | { type: 'SPECTRUM_SET_ACTIVE'; id: string }
  | { type: 'SPECTRUM_RENAME'; id: string; name: string }
  | {
      type: 'SPECTRUM_SET_PROCESSED'
      id: string
      processedY: number[]
      baselineY: number[]
    }
  | { type: 'SPECTRUM_SET_SMOOTHED_Y'; id: string; smoothedY: number[] }
  | { type: 'SPECTRUM_MOVE'; id: string; direction: 'up' | 'down' }
  | { type: 'SPECTRUM_REMOVE'; id: string }
  | { type: 'SPECTRA_CLEAR' }
  | {
      type: 'SPECTRA_RENAME_ALL'
      prefix: string
      mode?: 'index' | 'sequence'
      start?: number
      step?: number
      suffix?: string
      reverse?: boolean
    }
  | {
      type: 'SPECTRA_RENAME_BY_EXTRACT'
      source: 'filename' | 'name'
      preset: 'mv' | 'firstNumber' | 'lastNumber' | 'regex' | 'slice'
      regex?: string
      group?: number
      sliceStart?: number
      sliceEnd?: number
      trimResult?: boolean
      numbersOnly?: boolean
      prefix: string
      suffix: string
    }
  | { type: 'DATA_LABELING_SET'; patch: Partial<DataLabelingSettings> }
  | { type: 'PEAKS_SET'; patch: Partial<PeaksSettings> }
  | { type: 'PEAKS_CLEAR_ACTIVE' }
  | { type: 'PEAKS_CLEAR_ALL' }
  | { type: 'PEAKS_SET_AUTO'; spectrumId: string; peaks: Peak[] }
  | { type: 'PEAKS_SET_MANUAL'; spectrumId: string; peaks: Peak[] }
  | { type: 'PEAKS_MANUAL_ADD'; spectrumId: string; x: number }
  | { type: 'PEAKS_AUTO_DELETE'; spectrumId: string; peakId: string }
  | { type: 'PEAKS_MANUAL_DELETE'; spectrumId: string; peakId: string }
  | {
      type: 'PEAKS_LABEL_OFFSET_SET'
      spectrumId: string
      peakId: string
      ax: number
      ay: number
    }
  | { type: 'PEAKS_LABEL_OFFSETS_RESET_ACTIVE' }
  | { type: 'PEAKS_LABEL_OFFSETS_RESET_ALL' }
  | { type: 'PRESET_CREATE_FROM_CURRENT'; name: string }
  | { type: 'PRESET_DUPLICATE'; id: string }
  | { type: 'PRESET_DELETE'; id: string }
  | { type: 'PRESET_RENAME'; id: string; name: string }
  | { type: 'PRESET_SET_ACTIVE'; id: string | null }
  | { type: 'PRESETS_IMPORT'; presets: Preset[] }
  | { type: 'PRESET_UPDATE_FROM_CURRENT'; id: string }
  | { type: 'PRESET_APPLY_SETTINGS'; id: string }
  | { type: 'PRESET_APPLY_ALL'; id: string }
  | { type: 'PLOT_SET'; patch: Partial<PlotSettings> }
  | { type: 'EXPORT_SET'; patch: Partial<ExportSettings> }
  | { type: 'GRAPHICS_SET'; patch: Partial<GraphicsSettings> }
  | { type: 'COSMIC_SET'; patch: Partial<CosmicSettings> }
  | { type: 'COSMIC_MANUAL_SET'; enabled: boolean }
  | {
      type: 'COSMIC_MANUAL_APPLY_ACTIVE'
      spectrumId: string
      nextY: number[]
      prevYSnapshot: number[]
    }
  | { type: 'COSMIC_MANUAL_UNDO_ACTIVE'; spectrumId: string }
  | { type: 'COSMIC_MANUAL_RESET_ACTIVE'; spectrumId: string }
  | { type: 'COSMIC_MANUAL_RESET_ALL' }
  | {
      type: 'SPECTRUM_SET_COSMIC_CLEANED_Y'
      spectrumId: string
      yClean: number[]
      removedCount: number
    }
  | { type: 'COSMIC_RESET_ACTIVE' }
  | { type: 'COSMIC_RESET_ALL' }
  | { type: 'BASELINE_SET'; patch: Partial<BaselineSettings> }
  | { type: 'BASELINE_RESET_ACTIVE' }
  | { type: 'BASELINE_RESET_ALL' }
  | { type: 'SMOOTHING_SET'; patch: Partial<SmoothingSettings> }
  | { type: 'SMOOTHING_RESET_ACTIVE' }
  | { type: 'SMOOTHING_RESET_ALL' }

function extractTokenFromText(
  text: string,
  action: Extract<Action, { type: 'SPECTRA_RENAME_BY_EXTRACT' }>,
): string | null {
  switch (action.preset) {
    case 'mv': {
      const match = text.match(/(-?\d+(?:[.,]\d+)?)\s*mV/i)
      return match?.[1] ?? null
    }
    case 'firstNumber': {
      const match = text.match(/-?\d+(?:[.,]\d+)?/)
      return match?.[0] ?? null
    }
    case 'lastNumber': {
      const matches = text.match(/-?\d+(?:[.,]\d+)?/g)
      return matches && matches.length > 0
        ? matches[matches.length - 1]
        : null
    }
    case 'regex': {
      try {
        const regex = new RegExp(action.regex ?? '', 'i')
        const match = text.match(regex)
        const groupNumberRaw = Number(action.group)
        const groupNumber =
          Number.isInteger(groupNumberRaw) && groupNumberRaw >= 0
            ? groupNumberRaw
            : 1

        return match?.[groupNumber] ?? null
      } catch {
        return null
      }
    }
    case 'slice': {
      const len = text.length
      const toAbsIndex = (raw: number, fallback: number): number => {
        if (!Number.isFinite(raw)) {
          return fallback
        }

        const value = Math.trunc(raw)
        return value < 0 ? len + value : value
      }

      const startRaw = Number(action.sliceStart)
      const endRaw = Number(action.sliceEnd)
      let start = toAbsIndex(startRaw, 0)
      let end = toAbsIndex(endRaw, len)

      start = Math.max(0, Math.min(len, start))
      end = Math.max(0, Math.min(len, end))

      if (end < start) {
        ;[start, end] = [end, start]
      }

      const raw = text.slice(start, end)
      const result = action.trimResult === false ? raw : raw.trim()
      const out = action.numbersOnly
        ? (result.match(/-?\d+(?:[.,]\d+)?/)?.[0] ?? '')
        : result

      return out.length > 0 ? out : null
    }
  }
}

function createPresetId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }

  return `preset_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

function createPeakId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }

  return `peak_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

function prunePeakOffsetsForSpectrum(
  peakLabelOffsetsById: AppState['peakLabelOffsetsById'],
  spectrumId: string,
  validPeakIds: Set<string>,
): AppState['peakLabelOffsetsById'] {
  const currentOffsets = peakLabelOffsetsById[spectrumId]
  if (!currentOffsets) {
    return peakLabelOffsetsById
  }

  let changed = false
  const nextSpectrumOffsets: Record<string, { ax: number; ay: number }> = {}

  for (const [peakId, offset] of Object.entries(currentOffsets)) {
    if (!validPeakIds.has(peakId)) {
      changed = true
      continue
    }
    nextSpectrumOffsets[peakId] = offset
  }

  if (!changed) {
    return peakLabelOffsetsById
  }

  const nextOffsets = { ...peakLabelOffsetsById }
  if (Object.keys(nextSpectrumOffsets).length === 0) {
    delete nextOffsets[spectrumId]
  } else {
    nextOffsets[spectrumId] = nextSpectrumOffsets
  }

  return nextOffsets
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function asString(
  value: unknown,
  fallback: string,
): string {
  return typeof value === 'string' ? value : fallback
}

function asBoolean(
  value: unknown,
  fallback: boolean,
): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function normalizeDataLabelingSettings(
  value: unknown,
): DataLabelingSettings {
  const source =
    typeof value === 'object' && value !== null
      ? (value as Record<string, unknown>)
      : {}
  const labelExtractSource =
    typeof source.labelExtract === 'object' && source.labelExtract !== null
      ? (source.labelExtract as Record<string, unknown>)
      : {}

  const legacyPreset = asString(
    source.extractPreset,
    DEFAULT_LABEL_EXTRACT_SETTINGS.preset,
  )
  const legacyRegex = asString(
    source.extractRegex,
    DEFAULT_LABEL_EXTRACT_SETTINGS.regex,
  )
  const legacyStart = asString(
    source.extractSliceStart,
    DEFAULT_LABEL_EXTRACT_SETTINGS.start,
  )
  const legacyEnd = asString(
    source.extractSliceEnd,
    DEFAULT_LABEL_EXTRACT_SETTINGS.end,
  )
  const legacyTrim = asBoolean(
    source.extractTrimResult,
    DEFAULT_LABEL_EXTRACT_SETTINGS.trimResult,
  )
  const legacyNumbersOnly = asBoolean(
    source.extractNumbersOnly,
    DEFAULT_LABEL_EXTRACT_SETTINGS.numbersOnly,
  )
  const legacyPrefix = asString(
    source.extractPrefixText,
    DEFAULT_LABEL_EXTRACT_SETTINGS.prefix,
  )
  const legacySuffix = asString(
    source.extractSuffix,
    DEFAULT_LABEL_EXTRACT_SETTINGS.suffix,
  )

  return {
    ...DEFAULT_DATA_LABELING_SETTINGS,
    renumberMode: asString(
      source.renumberMode,
      DEFAULT_DATA_LABELING_SETTINGS.renumberMode,
    ) as DataLabelingSettings['renumberMode'],
    renumberPrefix: asString(
      source.renumberPrefix,
      DEFAULT_DATA_LABELING_SETTINGS.renumberPrefix,
    ),
    invertOrder: asBoolean(
      source.invertOrder,
      DEFAULT_DATA_LABELING_SETTINGS.invertOrder,
    ),
    sequenceStart: asString(
      source.sequenceStart,
      DEFAULT_DATA_LABELING_SETTINGS.sequenceStart,
    ),
    sequenceStep: asString(
      source.sequenceStep,
      DEFAULT_DATA_LABELING_SETTINGS.sequenceStep,
    ),
    sequenceSuffix: asString(
      source.sequenceSuffix,
      DEFAULT_DATA_LABELING_SETTINGS.sequenceSuffix,
    ),
    labelExtract: {
      ...DEFAULT_LABEL_EXTRACT_SETTINGS,
      mode: asString(
        labelExtractSource.mode,
        DEFAULT_LABEL_EXTRACT_SETTINGS.mode,
      ) as DataLabelingSettings['labelExtract']['mode'],
      preset: asString(
        labelExtractSource.preset,
        legacyPreset,
      ) as DataLabelingSettings['labelExtract']['preset'],
      start: asString(labelExtractSource.start, legacyStart),
      end: asString(labelExtractSource.end, legacyEnd),
      trimResult: asBoolean(labelExtractSource.trimResult, legacyTrim),
      numbersOnly: asBoolean(labelExtractSource.numbersOnly, legacyNumbersOnly),
      prefix: asString(labelExtractSource.prefix, legacyPrefix),
      suffix: asString(labelExtractSource.suffix, legacySuffix),
      regex: asString(labelExtractSource.regex, legacyRegex),
    },
  }
}

function normalizePeaksSettings(value: unknown): PeaksSettings {
  if (typeof value !== 'object' || value === null) {
    return { ...DEFAULT_PEAKS_SETTINGS }
  }

  return {
    ...DEFAULT_PEAKS_SETTINGS,
    ...(value as Partial<PeaksSettings>),
    // Peaks UI supports leader labels only; normalize legacy preset values.
    labelPlacement: 'leader',
  }
}

function buildPresetPayload(state: AppState): PresetPayload {
  return {
    themeMode: state.themeMode,
    plot: { ...state.plot },
    graphics: { ...state.graphics },
    baseline: { ...state.baseline },
    smoothing: { ...state.smoothing },
    cosmic: { ...state.cosmic },
    dataLabeling: normalizeDataLabelingSettings(state.dataLabeling),
    peaksSettings: normalizePeaksSettings(state.peaks),
  }
}

function clonePresetPayload(payload: PresetPayload): PresetPayload {
  return {
    themeMode: payload.themeMode,
    plot: { ...payload.plot },
    graphics: { ...payload.graphics },
    baseline: { ...payload.baseline },
    smoothing: { ...payload.smoothing },
    cosmic: { ...payload.cosmic },
    dataLabeling: normalizeDataLabelingSettings(payload.dataLabeling),
    peaksSettings: normalizePeaksSettings(payload.peaksSettings),
  }
}

function normalizePresetPayloadFromUnknown(
  value: unknown,
  fallbackState: AppState,
): PresetPayload {
  const source = isObject(value) ? value : {}

  const themeMode =
    source.themeMode === 'system' ||
    source.themeMode === 'light' ||
    source.themeMode === 'dark'
      ? source.themeMode
      : fallbackState.themeMode

  const plot =
    isObject(source.plot)
      ? {
          ...fallbackState.plot,
          ...(source.plot as Partial<PlotSettings>),
        }
      : { ...fallbackState.plot }
  const graphics =
    isObject(source.graphics)
      ? {
          ...fallbackState.graphics,
          ...(source.graphics as Partial<GraphicsSettings>),
        }
      : { ...fallbackState.graphics }
  const baseline =
    isObject(source.baseline)
      ? {
          ...fallbackState.baseline,
          ...(source.baseline as Partial<BaselineSettings>),
        }
      : { ...fallbackState.baseline }
  const smoothing =
    isObject(source.smoothing)
      ? {
          ...fallbackState.smoothing,
          ...(source.smoothing as Partial<SmoothingSettings>),
        }
      : { ...fallbackState.smoothing }
  const cosmic =
    isObject(source.cosmic)
      ? {
          ...fallbackState.cosmic,
          ...(source.cosmic as Partial<CosmicSettings>),
        }
      : { ...fallbackState.cosmic }
  const dataLabeling = normalizeDataLabelingSettings(
    source.dataLabeling ?? fallbackState.dataLabeling,
  )
  const peaksSettings = normalizePeaksSettings(
    source.peaksSettings ?? fallbackState.peaks,
  )

  return {
    themeMode,
    plot,
    graphics,
    baseline,
    smoothing,
    cosmic,
    dataLabeling,
    peaksSettings,
  }
}

export function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'THEME_SET':
      return {
        ...state,
        themeMode: action.mode,
      }
    case 'SPECTRUM_ADD':
      return {
        ...state,
        spectra: [...state.spectra, action.spectrum],
        activeSpectrumId: action.spectrum.id,
      }
    case 'SPECTRUM_SET_ACTIVE':
      return {
        ...state,
        activeSpectrumId: action.id,
      }
    case 'SPECTRUM_RENAME': {
      const nextName = action.name.trim()

      if (nextName.length === 0) {
        return state
      }

      let hasChanges = false
      const nextSpectra = state.spectra.map((spectrum) => {
        if (spectrum.id !== action.id || spectrum.name === nextName) {
          return spectrum
        }

        hasChanges = true
        return {
          ...spectrum,
          name: nextName,
        }
      })

      if (!hasChanges) {
        return state
      }

      return {
        ...state,
        spectra: nextSpectra,
      }
    }
    case 'SPECTRUM_SET_PROCESSED': {
      const nextSmoothed = { ...state.smoothedYById }
      const nextManualClean = { ...state.manualCleanYById }
      const nextManualUndo = { ...state.manualUndoStackById }
      delete nextSmoothed[action.id]
      delete nextManualClean[action.id]
      delete nextManualUndo[action.id]

      return {
        ...state,
        processedYById: {
          ...state.processedYById,
          [action.id]: action.processedY,
        },
        baselineYById: {
          ...state.baselineYById,
          [action.id]: action.baselineY,
        },
        smoothedYById: nextSmoothed,
        manualCleanYById: nextManualClean,
        manualUndoStackById: nextManualUndo,
      }
    }
    case 'SPECTRUM_SET_SMOOTHED_Y': {
      const nextManualClean = { ...state.manualCleanYById }
      const nextManualUndo = { ...state.manualUndoStackById }
      delete nextManualClean[action.id]
      delete nextManualUndo[action.id]

      return {
        ...state,
        smoothedYById: {
          ...state.smoothedYById,
          [action.id]: action.smoothedY,
        },
        manualCleanYById: nextManualClean,
        manualUndoStackById: nextManualUndo,
      }
    }
    case 'SPECTRUM_MOVE': {
      const sourceIndex = state.spectra.findIndex(
        (spectrum) => spectrum.id === action.id,
      )

      if (sourceIndex < 0) {
        return state
      }

      if (action.direction === 'up' && sourceIndex === 0) {
        return state
      }

      if (
        action.direction === 'down' &&
        sourceIndex === state.spectra.length - 1
      ) {
        return state
      }

      const targetIndex =
        action.direction === 'up' ? sourceIndex - 1 : sourceIndex + 1

      const nextSpectra = [...state.spectra]
      ;[nextSpectra[sourceIndex], nextSpectra[targetIndex]] = [
        nextSpectra[targetIndex],
        nextSpectra[sourceIndex],
      ]

      return {
        ...state,
        spectra: nextSpectra,
      }
    }
    case 'SPECTRUM_REMOVE': {
      const nextSpectra = state.spectra.filter(
        (spectrum) => spectrum.id !== action.id,
      )

      return {
        ...state,
        spectra: nextSpectra,
        activeSpectrumId:
          state.activeSpectrumId === action.id
            ? nextSpectra[0]?.id
            : state.activeSpectrumId,
      }
    }
    case 'SPECTRA_CLEAR':
      return {
        ...state,
        spectra: [],
        activeSpectrumId: undefined,
      }
    case 'SPECTRA_RENAME_ALL': {
      const list = state.spectra
      const prefix = action.prefix.trim()
      const mode = action.mode ?? 'index'
      const reverse = Boolean(action.reverse)
      const startN =
        Number.isFinite(Number(action.start)) ? Number(action.start) : 1
      const stepN =
        Number.isFinite(Number(action.step)) ? Number(action.step) : 1
      const suffix = action.suffix ?? ''
      const nextSpectra = list.map((spectrum, index) => {
        const effectiveIndex = reverse ? list.length - 1 - index : index
        const value =
          mode === 'sequence'
            ? startN + effectiveIndex * stepN
            : effectiveIndex + 1

        return {
          ...spectrum,
          name:
            mode === 'sequence'
              ? `${prefix}${value}${suffix}`
              : prefix
                ? `${prefix}${value}`
                : `${value}`,
        }
      })

      return {
        ...state,
        spectra: nextSpectra,
      }
    }
    case 'SPECTRA_RENAME_BY_EXTRACT': {
      const prefix = action.prefix.trim()
      const suffix = action.suffix ?? ''
      const nextSpectra = state.spectra.map((spectrum) => {
        if (action.source === 'filename') {
          const sourceName =
            typeof spectrum.meta?.sourceName === 'string'
              ? spectrum.meta.sourceName
              : ''

          const extracted = extractLabelFromFilename(sourceName, {
            mode: 'filename',
            preset: action.preset,
            start: String(action.sliceStart ?? ''),
            end: String(action.sliceEnd ?? ''),
            trimResult: action.trimResult ?? true,
            numbersOnly: action.numbersOnly ?? false,
            prefix,
            suffix,
            regex: action.regex ?? '',
          })

          if (extracted === null) {
            return spectrum
          }

          return {
            ...spectrum,
            name: extracted,
          }
        }

        const sourceText =
          spectrum.name ?? ''
        const token = extractTokenFromText(sourceText, action)

        if (token === null) {
          return spectrum
        }

        if (action.preset === 'slice') {
          return {
            ...spectrum,
            name: `${prefix}${token}${suffix}`,
          }
        }

        const normalizedToken = token.replace(/,/g, '.')
        const numericValue = Number(normalizedToken)

        if (!Number.isFinite(numericValue)) {
          return spectrum
        }

        const formattedValue =
          Math.abs(numericValue - Math.round(numericValue)) < 1e-9
            ? String(Math.round(numericValue))
            : normalizedToken

        return {
          ...spectrum,
          name: `${prefix}${formattedValue}${suffix}`,
        }
      })

      return {
        ...state,
        spectra: nextSpectra,
      }
    }
    case 'DATA_LABELING_SET':
      return {
        ...state,
        dataLabeling: {
          ...state.dataLabeling,
          ...action.patch,
          ...(action.patch.labelExtract
            ? {
                labelExtract: {
                  ...state.dataLabeling.labelExtract,
                  ...action.patch.labelExtract,
                },
              }
          : {}),
        },
      }
    case 'PEAKS_SET':
      return {
        ...state,
        peaks: {
          ...state.peaks,
          ...action.patch,
          // Peaks UI now supports leader labels only; normalize legacy values.
          labelPlacement: 'leader',
        },
      }
    case 'PEAKS_CLEAR_ACTIVE': {
      if (!state.activeSpectrumId) {
        return state
      }

      const nextAuto = { ...state.peaksAutoById }
      const nextManual = { ...state.peaksManualById }
      const nextOffsets = { ...state.peakLabelOffsetsById }
      delete nextAuto[state.activeSpectrumId]
      delete nextManual[state.activeSpectrumId]
      delete nextOffsets[state.activeSpectrumId]

      return {
        ...state,
        peaksAutoById: nextAuto,
        peaksManualById: nextManual,
        peakLabelOffsetsById: nextOffsets,
      }
    }
    case 'PEAKS_CLEAR_ALL':
      return {
        ...state,
        peaksAutoById: {},
        peaksManualById: {},
        peakLabelOffsetsById: {},
      }
    case 'PEAKS_SET_AUTO':
      {
        const nextAutoPeaks = action.peaks.slice()
        const currentManualPeaks = state.peaksManualById[action.spectrumId] ?? []
        const validPeakIds = new Set<string>(
          [...nextAutoPeaks, ...currentManualPeaks].map((peak) => peak.id),
        )
        const nextOffsets = prunePeakOffsetsForSpectrum(
          state.peakLabelOffsetsById,
          action.spectrumId,
          validPeakIds,
        )

        return {
          ...state,
          peaksAutoById: {
            ...state.peaksAutoById,
            [action.spectrumId]: nextAutoPeaks,
          },
          peakLabelOffsetsById: nextOffsets,
        }
      }
    case 'PEAKS_SET_MANUAL':
      {
        const nextManualPeaks = action.peaks.slice()
        const currentAutoPeaks = state.peaksAutoById[action.spectrumId] ?? []
        const validPeakIds = new Set<string>(
          [...currentAutoPeaks, ...nextManualPeaks].map((peak) => peak.id),
        )
        const nextOffsets = prunePeakOffsetsForSpectrum(
          state.peakLabelOffsetsById,
          action.spectrumId,
          validPeakIds,
        )

        return {
          ...state,
          peaksManualById: {
            ...state.peaksManualById,
            [action.spectrumId]: nextManualPeaks,
          },
          peakLabelOffsetsById: nextOffsets,
        }
      }
    case 'PEAKS_MANUAL_ADD': {
      const currentManual = state.peaksManualById[action.spectrumId] ?? []
      const manualPeak: Peak = {
        id: createPeakId(),
        x: action.x,
        source: 'manual',
      }

      return {
        ...state,
        peaksManualById: {
          ...state.peaksManualById,
          [action.spectrumId]: [...currentManual, manualPeak],
        },
      }
    }
    case 'PEAKS_AUTO_DELETE': {
      const currentAuto = state.peaksAutoById[action.spectrumId] ?? []
      const nextAuto = currentAuto.filter((peak) => peak.id !== action.peakId)
      if (nextAuto.length === currentAuto.length) {
        return state
      }

      const currentOffsets = state.peakLabelOffsetsById[action.spectrumId] ?? {}
      const nextOffsetsForSpectrum = { ...currentOffsets }
      delete nextOffsetsForSpectrum[action.peakId]

      return {
        ...state,
        peaksAutoById: {
          ...state.peaksAutoById,
          [action.spectrumId]: nextAuto,
        },
        peakLabelOffsetsById: {
          ...state.peakLabelOffsetsById,
          [action.spectrumId]: nextOffsetsForSpectrum,
        },
      }
    }
    case 'PEAKS_MANUAL_DELETE': {
      const currentManual = state.peaksManualById[action.spectrumId] ?? []
      const nextManual = currentManual.filter((peak) => peak.id !== action.peakId)
      if (nextManual.length === currentManual.length) {
        return state
      }

      const currentOffsets = state.peakLabelOffsetsById[action.spectrumId] ?? {}
      const nextOffsetsForSpectrum = { ...currentOffsets }
      delete nextOffsetsForSpectrum[action.peakId]

      return {
        ...state,
        peaksManualById: {
          ...state.peaksManualById,
          [action.spectrumId]: nextManual,
        },
        peakLabelOffsetsById: {
          ...state.peakLabelOffsetsById,
          [action.spectrumId]: nextOffsetsForSpectrum,
        },
      }
    }
    case 'PEAKS_LABEL_OFFSET_SET': {
      if (!Number.isFinite(action.ax) || !Number.isFinite(action.ay)) {
        return state
      }

      const currentSpectrumOffsets =
        state.peakLabelOffsetsById[action.spectrumId] ?? {}
      const currentOffset = currentSpectrumOffsets[action.peakId]
      if (
        currentOffset &&
        currentOffset.ax === action.ax &&
        currentOffset.ay === action.ay
      ) {
        return state
      }

      return {
        ...state,
        peakLabelOffsetsById: {
          ...state.peakLabelOffsetsById,
          [action.spectrumId]: {
            ...currentSpectrumOffsets,
            [action.peakId]: {
              ax: action.ax,
              ay: action.ay,
            },
          },
        },
      }
    }
    case 'PEAKS_LABEL_OFFSETS_RESET_ACTIVE': {
      if (!state.activeSpectrumId) {
        return state
      }

      const nextOffsets = { ...state.peakLabelOffsetsById }
      delete nextOffsets[state.activeSpectrumId]

      return {
        ...state,
        peakLabelOffsetsById: nextOffsets,
      }
    }
    case 'PEAKS_LABEL_OFFSETS_RESET_ALL':
      return {
        ...state,
        peakLabelOffsetsById: {},
      }
    case 'PRESET_CREATE_FROM_CURRENT': {
      const now = Date.now()
      const nextName = action.name.trim() || `Preset ${state.presets.length + 1}`
      const preset: Preset = {
        id: createPresetId(),
        name: nextName,
        createdAt: now,
        updatedAt: now,
        payload: buildPresetPayload(state),
      }

      return {
        ...state,
        presets: [...state.presets, preset],
        activePresetId: preset.id,
      }
    }
    case 'PRESET_DUPLICATE': {
      const sourcePreset = state.presets.find((preset) => preset.id === action.id)
      if (!sourcePreset) {
        return state
      }

      const now = Date.now()
      const duplicatedPreset: Preset = {
        id: createPresetId(),
        name: `${sourcePreset.name} copy`,
        createdAt: now,
        updatedAt: now,
        payload: clonePresetPayload(sourcePreset.payload),
      }

      return {
        ...state,
        presets: [...state.presets, duplicatedPreset],
        activePresetId: duplicatedPreset.id,
      }
    }
    case 'PRESET_DELETE': {
      const nextPresets = state.presets.filter((preset) => preset.id !== action.id)

      return {
        ...state,
        presets: nextPresets,
        activePresetId:
          state.activePresetId === action.id ? null : state.activePresetId,
      }
    }
    case 'PRESET_RENAME': {
      const nextName = action.name.trim()
      if (nextName.length === 0) {
        return state
      }

      let changed = false
      const nextPresets = state.presets.map((preset) => {
        if (preset.id !== action.id || preset.name === nextName) {
          return preset
        }

        changed = true
        return {
          ...preset,
          name: nextName,
          updatedAt: Date.now(),
        }
      })

      if (!changed) {
        return state
      }

      return {
        ...state,
        presets: nextPresets,
      }
    }
    case 'PRESET_APPLY_SETTINGS': {
      const preset = state.presets.find((candidate) => candidate.id === action.id)
      if (!preset) {
        return state
      }

      const payload = clonePresetPayload(preset.payload)
      const nextPlot = {
        ...payload.plot,
        uiRevision: payload.plot.uiRevision ?? state.plot.uiRevision ?? 1,
      }
      return {
        ...state,
        activePresetId: preset.id,
        themeMode: payload.themeMode,
        plot: nextPlot,
        graphics: payload.graphics,
        baseline: payload.baseline,
        smoothing: payload.smoothing,
        cosmic: payload.cosmic,
        dataLabeling: payload.dataLabeling,
        peaks: normalizePeaksSettings(payload.peaksSettings),
      }
    }
    case 'PRESET_APPLY_ALL':
      return state
    case 'PRESET_SET_ACTIVE': {
      if (action.id === null) {
        return {
          ...state,
          activePresetId: null,
        }
      }

      if (!state.presets.some((preset) => preset.id === action.id)) {
        return state
      }

      return {
        ...state,
        activePresetId: action.id,
      }
    }
    case 'PRESETS_IMPORT': {
      if (action.presets.length === 0) {
        return state
      }

      const importedPresets: Preset[] = action.presets
        .filter(
          (preset): preset is Preset =>
            typeof preset.id === 'string' &&
            preset.id.length > 0 &&
            typeof preset.name === 'string' &&
            preset.name.trim().length > 0,
        )
        .map((preset) => {
          const now = Date.now()
          const createdAt = Number.isFinite(preset.createdAt)
            ? Number(preset.createdAt)
            : now
          const updatedAt = Number.isFinite(preset.updatedAt)
            ? Number(preset.updatedAt)
            : createdAt

          return {
            id: preset.id,
            name: preset.name.trim(),
            createdAt,
            updatedAt,
            payload: normalizePresetPayloadFromUnknown(
              (preset as { payload?: unknown }).payload,
              state,
            ),
          }
        })

      if (importedPresets.length === 0) {
        return state
      }

      return {
        ...state,
        presets: [...state.presets, ...importedPresets],
        activePresetId: state.activePresetId ?? importedPresets[0].id,
      }
    }
    case 'PRESET_UPDATE_FROM_CURRENT': {
      const index = state.presets.findIndex((preset) => preset.id === action.id)
      if (index < 0) {
        return state
      }

      const nextPresets = state.presets.slice()
      nextPresets[index] = {
        ...nextPresets[index],
        updatedAt: Date.now(),
        payload: buildPresetPayload(state),
      }

      return {
        ...state,
        presets: nextPresets,
      }
    }
    case 'PLOT_SET':
      return {
        ...state,
        plot: {
          ...state.plot,
          ...action.patch,
        },
      }
    case 'EXPORT_SET':
      return {
        ...state,
        export: {
          ...state.export,
          ...action.patch,
        },
      }
    case 'GRAPHICS_SET':
      return {
        ...state,
        graphics: {
          ...state.graphics,
          ...action.patch,
        },
      }
    case 'COSMIC_SET':
      return {
        ...state,
        cosmic: {
          ...state.cosmic,
          ...action.patch,
        },
      }
    case 'COSMIC_MANUAL_SET':
      return {
        ...state,
        cosmic: {
          ...state.cosmic,
          manualEnabled: action.enabled,
        },
      }
    case 'COSMIC_MANUAL_APPLY_ACTIVE': {
      const currentStack = state.manualUndoStackById[action.spectrumId] ?? []
      const nextStack = [...currentStack, action.prevYSnapshot.slice()]

      if (nextStack.length > 20) {
        nextStack.splice(0, nextStack.length - 20)
      }

      return {
        ...state,
        manualCleanYById: {
          ...state.manualCleanYById,
          [action.spectrumId]: action.nextY.slice(),
        },
        manualUndoStackById: {
          ...state.manualUndoStackById,
          [action.spectrumId]: nextStack,
        },
      }
    }
    case 'COSMIC_MANUAL_UNDO_ACTIVE': {
      const currentStack = state.manualUndoStackById[action.spectrumId] ?? []
      if (currentStack.length === 0) {
        return state
      }

      const restoredY = currentStack[currentStack.length - 1]
      const nextStack = currentStack.slice(0, -1)
      const nextUndo = { ...state.manualUndoStackById }
      const nextManualClean = { ...state.manualCleanYById }

      if (nextStack.length === 0) {
        delete nextUndo[action.spectrumId]
      } else {
        nextUndo[action.spectrumId] = nextStack
      }

      nextManualClean[action.spectrumId] = restoredY.slice()

      return {
        ...state,
        manualCleanYById: nextManualClean,
        manualUndoStackById: nextUndo,
      }
    }
    case 'COSMIC_MANUAL_RESET_ACTIVE': {
      const nextManualClean = { ...state.manualCleanYById }
      const nextManualUndo = { ...state.manualUndoStackById }
      delete nextManualClean[action.spectrumId]
      delete nextManualUndo[action.spectrumId]

      return {
        ...state,
        manualCleanYById: nextManualClean,
        manualUndoStackById: nextManualUndo,
      }
    }
    case 'COSMIC_MANUAL_RESET_ALL':
      return {
        ...state,
        manualCleanYById: {},
        manualUndoStackById: {},
      }
    case 'SPECTRUM_SET_COSMIC_CLEANED_Y': {
      const nextProcessed = { ...state.processedYById }
      const nextBaseline = { ...state.baselineYById }
      const nextSmoothed = { ...state.smoothedYById }
      const nextManualClean = { ...state.manualCleanYById }
      const nextManualUndo = { ...state.manualUndoStackById }
      delete nextProcessed[action.spectrumId]
      delete nextBaseline[action.spectrumId]
      delete nextSmoothed[action.spectrumId]
      delete nextManualClean[action.spectrumId]
      delete nextManualUndo[action.spectrumId]

      return {
        ...state,
        cosmicCleanYById: {
          ...state.cosmicCleanYById,
          [action.spectrumId]: action.yClean,
        },
        processedYById: nextProcessed,
        baselineYById: nextBaseline,
        smoothedYById: nextSmoothed,
        manualCleanYById: nextManualClean,
        manualUndoStackById: nextManualUndo,
      }
    }
    case 'COSMIC_RESET_ACTIVE': {
      if (!state.activeSpectrumId) {
        return state
      }

      const nextCosmic = { ...state.cosmicCleanYById }
      const nextProcessed = { ...state.processedYById }
      const nextBaseline = { ...state.baselineYById }
      const nextSmoothed = { ...state.smoothedYById }
      const nextManualClean = { ...state.manualCleanYById }
      const nextManualUndo = { ...state.manualUndoStackById }
      delete nextCosmic[state.activeSpectrumId]
      delete nextProcessed[state.activeSpectrumId]
      delete nextBaseline[state.activeSpectrumId]
      delete nextSmoothed[state.activeSpectrumId]
      delete nextManualClean[state.activeSpectrumId]
      delete nextManualUndo[state.activeSpectrumId]

      return {
        ...state,
        cosmicCleanYById: nextCosmic,
        processedYById: nextProcessed,
        baselineYById: nextBaseline,
        smoothedYById: nextSmoothed,
        manualCleanYById: nextManualClean,
        manualUndoStackById: nextManualUndo,
      }
    }
    case 'COSMIC_RESET_ALL':
      return {
        ...state,
        cosmicCleanYById: {},
        manualCleanYById: {},
        manualUndoStackById: {},
        processedYById: {},
        baselineYById: {},
        smoothedYById: {},
      }
    case 'BASELINE_SET':
      return {
        ...state,
        baseline: {
          ...state.baseline,
          ...action.patch,
        },
      }
    case 'BASELINE_RESET_ACTIVE': {
      if (!state.activeSpectrumId) {
        return state
      }

      const nextProcessed = { ...state.processedYById }
      const nextBaseline = { ...state.baselineYById }
      const nextSmoothed = { ...state.smoothedYById }
      delete nextProcessed[state.activeSpectrumId]
      delete nextBaseline[state.activeSpectrumId]
      delete nextSmoothed[state.activeSpectrumId]

      return {
        ...state,
        processedYById: nextProcessed,
        baselineYById: nextBaseline,
        smoothedYById: nextSmoothed,
      }
    }
    case 'BASELINE_RESET_ALL':
      return {
        ...state,
        processedYById: {},
        baselineYById: {},
        smoothedYById: {},
      }
    case 'SMOOTHING_SET':
      return {
        ...state,
        smoothing: {
          ...state.smoothing,
          ...action.patch,
        },
      }
    case 'SMOOTHING_RESET_ACTIVE': {
      if (!state.activeSpectrumId) {
        return state
      }

      const nextSmoothed = { ...state.smoothedYById }
      delete nextSmoothed[state.activeSpectrumId]

      return {
        ...state,
        smoothedYById: nextSmoothed,
      }
    }
    case 'SMOOTHING_RESET_ALL':
      return {
        ...state,
        smoothedYById: {},
      }
  }
}
