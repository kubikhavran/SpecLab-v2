import type { ChangeEvent, KeyboardEvent } from 'react'
import { useMemo, useRef, useState } from 'react'
import { useAppDispatch, useAppState } from '../../app/state/AppStore'
import {
  DEFAULT_LABEL_EXTRACT_SETTINGS,
  DEFAULT_PEAKS_SETTINGS,
  type DataLabelingSettings,
  type PeaksSettings,
  type Preset,
  type PlotSettings,
} from '../../app/types/core'
import { applyBaseline } from '../baseline/applyBaseline'
import { aslsBaseline } from '../baseline/aslsBaseline'
import { removeCosmicRays } from '../cosmic/removeCosmicRays'
import { extractLabelFromFilename } from '../import/extractLabelFromFilename'
import { detectPeaks } from '../peaks/detectPeaks'
import {
  exportPresetsToJsonFile,
  parsePresetsFromFile,
  PRESETS_FILE_NAME,
  sanitizeFilename,
} from './presetsStorage'
import { savgolSmooth } from '../smoothing/savgol'

const APPLY_ALL_YIELD_EVERY = 4

function clampPolyOrder(polyOrder: number, window: number): number {
  const minValue = 2
  const maxValue = Math.min(5, Math.max(minValue, window - 1))

  return Math.min(maxValue, Math.max(minValue, Math.round(polyOrder)))
}

function yieldToMainThread(): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, 0)
  })
}

function resolveLabelExtractSettings(
  dataLabeling: DataLabelingSettings,
) {
  return {
    ...DEFAULT_LABEL_EXTRACT_SETTINGS,
    ...dataLabeling.labelExtract,
  }
}

function createPeakId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }

  return `peak_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

function createPresetId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }

  return `preset_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

function resolveUniqueImportedName(
  preferredName: string,
  usedNames: Set<string>,
): string {
  const baseName = preferredName.trim() || 'Imported preset'
  if (!usedNames.has(baseName)) {
    usedNames.add(baseName)
    return baseName
  }

  let index = 1
  while (true) {
    const suffix = index === 1 ? ' (imported)' : ` (imported ${index})`
    const candidate = `${baseName}${suffix}`
    if (!usedNames.has(candidate)) {
      usedNames.add(candidate)
      return candidate
    }
    index += 1
  }
}

function parseFiniteNumber(value: string): number | undefined {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

function resolveDetectionRange(
  peaksSettings: PeaksSettings,
  plotSettings: PlotSettings,
): { xMin?: number; xMax?: number } {
  if (!peaksSettings.useRegion) {
    return {}
  }

  if (plotSettings.xMin != null && plotSettings.xMax != null) {
    return { xMin: plotSettings.xMin, xMax: plotSettings.xMax }
  }

  return {
    xMin: parseFiniteNumber(peaksSettings.regionXMin),
    xMax: parseFiniteNumber(peaksSettings.regionXMax),
  }
}

export function PresetsPanel() {
  const { spectra, presets, activePresetId, activeSpectrumId } = useAppState()
  const dispatch = useAppDispatch()
  const [newPresetName, setNewPresetName] = useState('')
  const [renameId, setRenameId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [isApplyingAll, setIsApplyingAll] = useState(false)
  const [importStatus, setImportStatus] = useState<string | null>(null)
  const [importError, setImportError] = useState(false)
  const importInputRef = useRef<HTMLInputElement | null>(null)

  const activePreset = useMemo(
    () => presets.find((preset) => preset.id === activePresetId) ?? null,
    [activePresetId, presets],
  )

  const handleCreatePreset = () => {
    dispatch({
      type: 'PRESET_CREATE_FROM_CURRENT',
      name: newPresetName,
    })
    setNewPresetName('')
  }

  const beginRename = (id: string, currentName: string) => {
    setRenameId(id)
    setRenameDraft(currentName)
  }

  const cancelRename = () => {
    setRenameId(null)
    setRenameDraft('')
  }

  const commitRename = (id: string) => {
    dispatch({
      type: 'PRESET_RENAME',
      id,
      name: renameDraft,
    })
    cancelRename()
  }

  const handleRenameKeyDown = (
    event: KeyboardEvent<HTMLInputElement>,
    id: string,
  ) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      commitRename(id)
      return
    }

    if (event.key === 'Escape') {
      event.preventDefault()
      cancelRename()
    }
  }

  const handleDeletePreset = (id: string, name: string) => {
    if (!window.confirm(`Delete preset "${name}"?`)) {
      return
    }

    dispatch({
      type: 'PRESET_DELETE',
      id,
    })

    if (renameId === id) {
      cancelRename()
    }
  }

  const handleExportPresets = (
    presetsToExport: Preset[],
    fileName: string = PRESETS_FILE_NAME,
  ) => {
    if (presetsToExport.length === 0) {
      return
    }

    exportPresetsToJsonFile(presetsToExport, fileName)
    setImportError(false)
    setImportStatus(
      `Exported ${presetsToExport.length} preset${
        presetsToExport.length === 1 ? '' : 's'
      }.`,
    )
  }

  const handleImportFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0]
    event.currentTarget.value = ''

    if (!file) {
      return
    }

    try {
      const text = await file.text()
      const importedCandidates = parsePresetsFromFile(text)
      if (importedCandidates.length === 0) {
        setImportError(true)
        setImportStatus('No presets were imported.')
        return
      }

      const usedIds = new Set(presets.map((preset) => preset.id))
      const usedNames = new Set(presets.map((preset) => preset.name))
      const now = Date.now()
      const importedPresets: Preset[] = importedCandidates.map((candidate) => {
        let nextId = candidate.id
        while (usedIds.has(nextId)) {
          nextId = createPresetId()
        }
        usedIds.add(nextId)

        const nextName = resolveUniqueImportedName(candidate.name, usedNames)
        const createdAt = Number.isFinite(candidate.createdAt)
          ? Number(candidate.createdAt)
          : now
        const updatedAt = Number.isFinite(candidate.updatedAt)
          ? Number(candidate.updatedAt)
          : createdAt

        return {
          id: nextId,
          name: nextName,
          createdAt,
          updatedAt,
          payload: candidate.payload as Preset['payload'],
        }
      })

      dispatch({
        type: 'PRESETS_IMPORT',
        presets: importedPresets,
      })
      setImportError(false)
      setImportStatus(
        `Imported: ${importedPresets.length} preset${
          importedPresets.length === 1 ? '' : 's'
        }.`,
      )
    } catch (error) {
      setImportError(true)
      const message =
        error instanceof Error ? error.message : 'Failed to import presets.'
      setImportStatus(message)
    }
  }

  const handleApplyAllSettings = async (preset: Preset) => {
    if (isApplyingAll) {
      return
    }

    setIsApplyingAll(true)
    try {
      dispatch({
        type: 'PRESET_APPLY_SETTINGS',
        id: preset.id,
      })

      const labelExtract = resolveLabelExtractSettings(preset.payload.dataLabeling)
      const peaksSettings: PeaksSettings = {
        ...DEFAULT_PEAKS_SETTINGS,
        ...(preset.payload.peaksSettings ?? {}),
        labelPlacement: 'leader',
      }
      const targetSpectrumIds =
        peaksSettings.mode === 'all'
          ? spectra.map((spectrum) => spectrum.id)
          : [activeSpectrumId ?? spectra[0]?.id].filter(
              (id): id is string => typeof id === 'string',
            )
      for (let index = 0; index < spectra.length; index += 1) {
        const spectrum = spectra[index]
        const sourceName =
          typeof spectrum.meta?.sourceName === 'string'
            ? spectrum.meta.sourceName
            : ''
        const nextLabel = extractLabelFromFilename(sourceName, labelExtract)

        if (nextLabel !== null && nextLabel !== spectrum.name) {
          dispatch({
            type: 'SPECTRUM_RENAME',
            id: spectrum.id,
            name: nextLabel,
          })
        }
      }

      dispatch({ type: 'COSMIC_RESET_ALL' })

      const cosmicSettings = preset.payload.cosmic
      const baselineSettings = preset.payload.baseline
      const smoothingSettings = preset.payload.smoothing
      const clampedPolyOrder = clampPolyOrder(
        smoothingSettings.polyOrder,
        smoothingSettings.window,
      )
      const nextCosmicCleanYById: Record<string, number[]> = {}
      const nextProcessedYById: Record<string, number[]> = {}
      const nextSmoothedYById: Record<string, number[]> = {}

      for (let index = 0; index < spectra.length; index += 1) {
        const spectrum = spectra[index]
        const cosmicResult = removeCosmicRays(spectrum.y, {
          window: cosmicSettings.window,
          threshold: cosmicSettings.threshold,
          maxWidth: cosmicSettings.maxWidth,
          positiveOnly: cosmicSettings.positiveOnly,
          iterations: cosmicSettings.iterations,
        })

        dispatch({
          type: 'SPECTRUM_SET_COSMIC_CLEANED_Y',
          spectrumId: spectrum.id,
          yClean: cosmicResult.yClean,
          removedCount: cosmicResult.removedCount,
        })
        nextCosmicCleanYById[spectrum.id] = cosmicResult.yClean

        const baselineY = aslsBaseline(
          cosmicResult.yClean,
          baselineSettings.lambda,
          baselineSettings.p,
          baselineSettings.iterations,
        )
        const processedY = applyBaseline(cosmicResult.yClean, baselineY)

        dispatch({
          type: 'SPECTRUM_SET_PROCESSED',
          id: spectrum.id,
          processedY,
          baselineY,
        })
        nextProcessedYById[spectrum.id] = processedY

        const smoothedY = savgolSmooth(
          processedY,
          smoothingSettings.window,
          clampedPolyOrder,
        )
        dispatch({
          type: 'SPECTRUM_SET_SMOOTHED_Y',
          id: spectrum.id,
          smoothedY,
        })
        nextSmoothedYById[spectrum.id] = smoothedY

        if ((index + 1) % APPLY_ALL_YIELD_EVERY === 0) {
          await yieldToMainThread()
        }
      }

      dispatch({
        type: 'BASELINE_SET',
        patch: { enabled: true },
      })
      dispatch({
        type: 'SMOOTHING_SET',
        patch: { polyOrder: clampedPolyOrder },
      })

      dispatch({ type: 'PEAKS_LABEL_OFFSETS_RESET_ALL' })
      for (const spectrum of spectra) {
        dispatch({
          type: 'PEAKS_SET_AUTO',
          spectrumId: spectrum.id,
          peaks: [],
        })
      }

      if (!peaksSettings.enabled || targetSpectrumIds.length === 0) {
        return
      }

      const { xMin, xMax } = resolveDetectionRange(
        peaksSettings,
        preset.payload.plot,
      )
      const detectionMinProminence = Math.max(0, peaksSettings.minProminence)
      const detectionMinDistance = Math.max(0, peaksSettings.minDistance)
      const detectionMaxPeaks = Math.max(1, Math.round(peaksSettings.maxPeaks))

      for (let index = 0; index < targetSpectrumIds.length; index += 1) {
        const spectrumId = targetSpectrumIds[index]
        const spectrum = spectra.find((entry) => entry.id === spectrumId)
        if (!spectrum) {
          continue
        }

        const yUsed =
          nextCosmicCleanYById[spectrum.id] ??
          nextSmoothedYById[spectrum.id] ??
          nextProcessedYById[spectrum.id] ??
          spectrum.y
        const pointCount = Math.min(spectrum.x.length, yUsed.length)
        if (pointCount < 3) {
          dispatch({
            type: 'PEAKS_SET_AUTO',
            spectrumId: spectrum.id,
            peaks: [],
          })
          continue
        }

        const detectedPeaks = detectPeaks(
          spectrum.x.slice(0, pointCount),
          yUsed.slice(0, pointCount),
          {
            minProminence: detectionMinProminence,
            minDistanceX: detectionMinDistance,
            maxPeaks: detectionMaxPeaks,
            xMin,
            xMax,
          },
        )

        dispatch({
          type: 'PEAKS_SET_AUTO',
          spectrumId: spectrum.id,
          peaks: detectedPeaks.map((peak) => ({
            id: createPeakId(),
            x: peak.x,
            source: 'auto' as const,
          })),
        })

        if ((index + 1) % APPLY_ALL_YIELD_EVERY === 0) {
          await yieldToMainThread()
        }
      }
    } finally {
      setIsApplyingAll(false)
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-1">
        <input
          type="text"
          className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 text-xs text-slate-700"
          placeholder="Preset name"
          value={newPresetName}
          onChange={(event) => setNewPresetName(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              handleCreatePreset()
            }
          }}
        />
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-100"
          disabled={isApplyingAll}
          onClick={handleCreatePreset}
        >
          Create preset
        </button>
      </div>

      {presets.length === 0 ? (
        <p className="text-[11px] text-slate-400">No presets yet.</p>
      ) : (
        <ul className="space-y-1">
          {presets.map((preset) => {
            const isActive = preset.id === activePresetId
            const isRenaming = preset.id === renameId

            return (
              <li
                key={preset.id}
                className={[
                  'rounded border p-2',
                  isActive
                    ? 'border-sky-300 bg-sky-50'
                    : 'border-slate-200 bg-white',
                ].join(' ')}
              >
                {isRenaming ? (
                  <div className="space-y-1">
                    <input
                      type="text"
                      autoFocus
                      className="w-full rounded border border-slate-300 px-2 py-1 text-xs text-slate-700"
                      value={renameDraft}
                      onChange={(event) =>
                        setRenameDraft(event.currentTarget.value)
                      }
                      onKeyDown={(event) =>
                        handleRenameKeyDown(event, preset.id)
                      }
                    />
                    <div className="flex flex-wrap gap-1">
                      <button
                        type="button"
                        className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100"
                        onClick={() => commitRename(preset.id)}
                      >
                        Save
                      </button>
                      <button
                        type="button"
                        className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100"
                        onClick={cancelRename}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-xs font-medium text-slate-700">
                        {preset.name}
                      </span>
                      {isActive ? (
                        <span className="rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-medium text-sky-700">
                          Active
                        </span>
                      ) : null}
                    </div>
                    <div className="flex flex-wrap gap-1">
                      <button
                        type="button"
                        className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100"
                        disabled={isApplyingAll}
                        onClick={() =>
                          dispatch({
                            type: 'PRESET_SET_ACTIVE',
                            id: preset.id,
                          })
                        }
                      >
                        Select
                      </button>
                      <button
                        type="button"
                        className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100"
                        disabled={isApplyingAll}
                        onClick={() => beginRename(preset.id, preset.name)}
                      >
                        Rename
                      </button>
                      <button
                        type="button"
                        className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100"
                        disabled={isApplyingAll}
                        onClick={() =>
                          dispatch({
                            type: 'PRESET_DUPLICATE',
                            id: preset.id,
                          })
                        }
                      >
                        Duplicate
                      </button>
                      <button
                        type="button"
                        className="rounded border border-red-200 px-2 py-0.5 text-xs text-red-600 hover:bg-red-50"
                        disabled={isApplyingAll}
                        onClick={() => handleDeletePreset(preset.id, preset.name)}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}

      <div className="flex flex-wrap gap-1 border-t border-slate-200 pt-2">
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={!activePreset || isApplyingAll}
          onClick={() => {
            if (!activePreset) {
              return
            }

            dispatch({
              type: 'PRESET_APPLY_SETTINGS',
              id: activePreset.id,
            })
          }}
        >
          Apply settings
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={!activePreset || isApplyingAll}
          onClick={() => {
            if (!activePreset) {
              return
            }

            void handleApplyAllSettings(activePreset)
          }}
        >
          Apply ALL settings
        </button>
      </div>
      <div className="flex flex-wrap gap-1">
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={!activePreset || isApplyingAll}
          onClick={() => {
            if (!activePreset) {
              return
            }

            handleExportPresets(
              [activePreset],
              `${sanitizeFilename(activePreset.name)}.json`,
            )
          }}
        >
          Export selected
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={presets.length === 0 || isApplyingAll}
          onClick={() => handleExportPresets(presets)}
        >
          Export all
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={isApplyingAll}
          onClick={() => importInputRef.current?.click()}
        >
          Import...
        </button>
        <input
          ref={importInputRef}
          type="file"
          accept=".json,application/json"
          className="hidden"
          onChange={(event) => {
            void handleImportFile(event)
          }}
        />
      </div>
      {isApplyingAll ? (
        <p className="text-[11px] text-slate-500">Applying preset to all spectra...</p>
      ) : null}
      {importStatus ? (
        <p
          className={`text-[11px] ${
            importError ? 'text-red-600 dark:text-red-400' : 'text-slate-500 dark:text-slate-400'
          }`}
        >
          {importStatus}
        </p>
      ) : null}
    </div>
  )
}
