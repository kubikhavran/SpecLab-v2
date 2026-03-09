import { useMemo } from 'react'
import { useAppDispatch, useAppState } from '../../app/state/AppStore'
import type { Peak } from '../../app/types/core'
import { detectPeaks } from './detectPeaks'

function parseNumber(value: string): number | undefined {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

function clampInt(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, Math.round(value)))
}

function clampNumber(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

function createPeakId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }

  return `peak_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

export function PeaksPanel() {
  const {
    spectra,
    activeSpectrumId,
    peaks,
    plot,
    cosmicCleanYById,
    processedYById,
    smoothedYById,
    peaksAutoById,
    peaksManualById,
    peakLabelOffsetsById,
  } = useAppState()
  const dispatch = useAppDispatch()

  const activeSpectrum = useMemo(
    () =>
      activeSpectrumId !== undefined
        ? spectra.find((spectrum) => spectrum.id === activeSpectrumId) ?? spectra[0]
        : spectra[0],
    [activeSpectrumId, spectra],
  )

  const activeId = activeSpectrum?.id
  const hasActivePeaks =
    activeId !== undefined &&
    ((peaksAutoById[activeId]?.length ?? 0) > 0 ||
      (peaksManualById[activeId]?.length ?? 0) > 0)
  const hasAnyPeaks =
    Object.values(peaksAutoById).some((items) => items.length > 0) ||
    Object.values(peaksManualById).some((items) => items.length > 0)
  const autoPeakCount =
    peaks.mode === 'active'
      ? activeId
        ? peaksAutoById[activeId]?.length ?? 0
        : 0
      : Object.values(peaksAutoById).reduce(
          (total, peakList) => total + peakList.length,
          0,
        )
  const hasActiveOffsets =
    activeId !== undefined &&
    Object.keys(peakLabelOffsetsById[activeId] ?? {}).length > 0
  const hasAnyOffsets = Object.values(peakLabelOffsetsById).some(
    (entry) => Object.keys(entry).length > 0,
  )

  const resolveRange = () => {
    if (!peaks.useRegion) {
      return { xMin: undefined, xMax: undefined }
    }

    if (plot.xMin != null && plot.xMax != null) {
      return { xMin: plot.xMin, xMax: plot.xMax }
    }

    const xMin = parseNumber(peaks.regionXMin)
    const xMax = parseNumber(peaks.regionXMax)
    return {
      xMin: xMin !== undefined ? xMin : undefined,
      xMax: xMax !== undefined ? xMax : undefined,
    }
  }

  const toAutoPeaks = (x: number[], y: number[]): Peak[] => {
    const { xMin, xMax } = resolveRange()
    const detected = detectPeaks(x, y, {
      minProminence: Math.max(0, peaks.minProminence),
      minDistanceX: Math.max(0, peaks.minDistance),
      maxPeaks: Math.max(1, peaks.maxPeaks),
      xMin,
      xMax,
    })

    return detected.map((item) => ({
      id: createPeakId(),
      x: item.x,
      source: 'auto',
    }))
  }

  const detectForSpectrum = (spectrumId: string) => {
    const spectrum = spectra.find((entry) => entry.id === spectrumId)
    if (!spectrum) {
      return
    }

    const yBase =
      cosmicCleanYById[spectrum.id] ??
      smoothedYById[spectrum.id] ??
      processedYById[spectrum.id] ??
      spectrum.y
    const pointCount = Math.min(spectrum.x.length, yBase.length)
    if (pointCount < 3) {
      dispatch({
        type: 'PEAKS_SET_AUTO',
        spectrumId: spectrum.id,
        peaks: [],
      })
      return
    }

    const nextPeaks = toAutoPeaks(
      spectrum.x.slice(0, pointCount),
      yBase.slice(0, pointCount),
    )

    dispatch({
      type: 'PEAKS_SET_AUTO',
      spectrumId: spectrum.id,
      peaks: nextPeaks,
    })
  }

  const handleDetectActive = () => {
    if (!activeId || !peaks.enabled) {
      return
    }

    detectForSpectrum(activeId)
  }

  const handleDetectAll = () => {
    if (!peaks.enabled || spectra.length === 0) {
      return
    }

    for (const spectrum of spectra) {
      detectForSpectrum(spectrum.id)
    }
  }

  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300">
        <input
          type="checkbox"
          className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
          checked={peaks.enabled}
          onChange={(event) =>
            dispatch({
              type: 'PEAKS_SET',
              patch: { enabled: event.currentTarget.checked },
            })
          }
        />
        <span>Enabled</span>
      </label>

      <div className="grid grid-cols-2 gap-1">
        <label className="space-y-0.5">
          <span className="text-[11px] text-slate-600 dark:text-slate-400">Mode</span>
          <select
            className="w-full rounded border border-slate-300 bg-white px-1.5 py-1 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            value={peaks.mode}
            onChange={(event) =>
              dispatch({
                type: 'PEAKS_SET',
                patch: {
                  mode: event.currentTarget.value as 'active' | 'all',
                },
              })
            }
          >
            <option value="active">Active</option>
            <option value="all">All</option>
          </select>
        </label>

        <div className="space-y-0.5">
          <span className="text-[11px] text-slate-600 dark:text-slate-400">Label placement</span>
          <p className="rounded border border-slate-300 bg-white px-1.5 py-1 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100">
            Leader (draggable)
          </p>
        </div>
      </div>
      <p className="text-[11px] text-slate-500 dark:text-slate-400">
        Leader labels are draggable and stay connected to peaks with a line.
      </p>

      <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300">
        <input
          type="checkbox"
          className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
          checked={peaks.manualPickEnabled}
          onChange={(event) =>
            dispatch({
              type: 'PEAKS_SET',
              patch: { manualPickEnabled: event.currentTarget.checked },
            })
          }
        />
        <span>Manual pick tool (click on plot)</span>
      </label>
      <p className="text-[11px] text-slate-500 dark:text-slate-400">
        When enabled, click on the spectrum to add a peak label at that X. Y is
        taken from the curve. Shift+click a peak label to delete it (auto or manual).
      </p>

      <div className="grid grid-cols-3 gap-1">
        <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
            checked={peaks.showMarkers}
            onChange={(event) =>
              dispatch({
                type: 'PEAKS_SET',
                patch: { showMarkers: event.currentTarget.checked },
              })
            }
          />
          <span>Show markers</span>
        </label>

        <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
            checked={peaks.showLabels}
            onChange={(event) =>
              dispatch({
                type: 'PEAKS_SET',
                patch: { showLabels: event.currentTarget.checked },
              })
            }
          />
          <span>Show labels</span>
        </label>

        <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
            checked={peaks.showLeaderLines}
            onChange={(event) =>
              dispatch({
                type: 'PEAKS_SET',
                patch: { showLeaderLines: event.currentTarget.checked },
              })
            }
          />
          <span>Show leader lines</span>
        </label>
      </div>

      <label className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-600 dark:text-slate-400">
            Label angle
          </span>
          <span className="text-[11px] text-slate-500 dark:text-slate-400">
            {clampInt(peaks.labelAngleDeg, -90, 90)}°
          </span>
        </div>
        <input
          type="range"
          min={-90}
          max={90}
          step={5}
          className="w-full accent-sky-600"
          value={clampInt(peaks.labelAngleDeg, -90, 90)}
          onChange={(event) => {
            const parsed = parseNumber(event.currentTarget.value)
            if (parsed === undefined) {
              return
            }

            dispatch({
              type: 'PEAKS_SET',
              patch: { labelAngleDeg: clampInt(parsed, -90, 90) },
            })
          }}
        />
      </label>

      <div className="space-y-2 rounded border border-slate-200 p-2 dark:border-slate-700">
        <p className="text-[11px] font-medium text-slate-600 dark:text-slate-300">
          Label style
        </p>

        <label className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-slate-600 dark:text-slate-400">
              Font size
            </span>
            <span className="text-[11px] text-slate-500 dark:text-slate-400">
              {clampInt(peaks.labelFontSize, 8, 96)} px
            </span>
          </div>
          <input
            type="range"
            min={8}
            max={96}
            step={1}
            className="w-full accent-sky-600"
            value={clampInt(peaks.labelFontSize, 8, 96)}
            onChange={(event) => {
              const parsed = parseNumber(event.currentTarget.value)
              if (parsed === undefined) {
                return
              }

              dispatch({
                type: 'PEAKS_SET',
                patch: { labelFontSize: clampInt(parsed, 8, 96) },
              })
            }}
          />
        </label>

        <div className="grid grid-cols-2 gap-1">
          <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300">
            <input
              type="checkbox"
              className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
              checked={peaks.labelBold}
              onChange={(event) =>
                dispatch({
                  type: 'PEAKS_SET',
                  patch: { labelBold: event.currentTarget.checked },
                })
              }
            />
            <span>Bold</span>
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300">
            <input
              type="checkbox"
              className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
              checked={peaks.labelItalic}
              onChange={(event) =>
                dispatch({
                  type: 'PEAKS_SET',
                  patch: { labelItalic: event.currentTarget.checked },
                })
              }
            />
            <span>Italic</span>
          </label>
        </div>

        <div className="grid grid-cols-[1fr_auto] items-end gap-2">
          <label className="space-y-0.5">
            <span className="text-[11px] text-slate-600 dark:text-slate-400">
              Label color
            </span>
            <select
              className="w-full rounded border border-slate-300 bg-white px-1.5 py-1 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              value={peaks.labelColorMode}
              onChange={(event) =>
                dispatch({
                  type: 'PEAKS_SET',
                  patch: {
                    labelColorMode: event.currentTarget.value as 'trace' | 'custom',
                  },
                })
              }
            >
              <option value="trace">Match spectrum</option>
              <option value="custom">Custom</option>
            </select>
          </label>

          {peaks.labelColorMode === 'custom' ? (
            <label className="space-y-0.5">
              <span className="text-[11px] text-slate-600 dark:text-slate-400">
                &nbsp;
              </span>
              <input
                type="color"
                className="h-8 w-10 rounded border border-slate-300 bg-white p-0.5 dark:border-slate-700 dark:bg-slate-900"
                value={peaks.labelColor}
                onChange={(event) =>
                  dispatch({
                    type: 'PEAKS_SET',
                    patch: { labelColor: event.currentTarget.value },
                  })
                }
              />
            </label>
          ) : null}
        </div>
      </div>

      <div
        className={`space-y-2 rounded border border-slate-200 p-2 dark:border-slate-700 ${
          peaks.showLeaderLines ? '' : 'opacity-60'
        }`}
      >
        <p className="text-[11px] font-medium text-slate-600 dark:text-slate-300">
          Leader line
        </p>

        <label className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-slate-600 dark:text-slate-400">
              Line width
            </span>
            <span className="text-[11px] text-slate-500 dark:text-slate-400">
              {clampNumber(peaks.leaderLineWidth, 1, 6)} px
            </span>
          </div>
          <input
            type="range"
            min={1}
            max={6}
            step={0.5}
            className="w-full accent-sky-600"
            value={clampNumber(peaks.leaderLineWidth, 1, 6)}
            disabled={!peaks.showLeaderLines}
            onChange={(event) => {
              const parsed = parseNumber(event.currentTarget.value)
              if (parsed === undefined) {
                return
              }

              dispatch({
                type: 'PEAKS_SET',
                patch: { leaderLineWidth: clampNumber(parsed, 1, 6) },
              })
            }}
          />
        </label>

        <div className="grid grid-cols-[1fr_auto] items-end gap-2">
          <label className="space-y-0.5">
            <span className="text-[11px] text-slate-600 dark:text-slate-400">
              Line color
            </span>
            <select
              className="w-full rounded border border-slate-300 bg-white px-1.5 py-1 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              value={peaks.leaderColorMode}
              disabled={!peaks.showLeaderLines}
              onChange={(event) =>
                dispatch({
                  type: 'PEAKS_SET',
                  patch: {
                    leaderColorMode: event.currentTarget.value as 'trace' | 'custom',
                  },
                })
              }
            >
              <option value="trace">Match spectrum</option>
              <option value="custom">Custom</option>
            </select>
          </label>

          {peaks.leaderColorMode === 'custom' ? (
            <label className="space-y-0.5">
              <span className="text-[11px] text-slate-600 dark:text-slate-400">
                &nbsp;
              </span>
              <input
                type="color"
                className="h-8 w-10 rounded border border-slate-300 bg-white p-0.5 dark:border-slate-700 dark:bg-slate-900"
                value={peaks.leaderColor}
                disabled={!peaks.showLeaderLines}
                onChange={(event) =>
                  dispatch({
                    type: 'PEAKS_SET',
                    patch: { leaderColor: event.currentTarget.value },
                  })
                }
              />
            </label>
          ) : null}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-1">
        <label className="space-y-1">
          <span className="text-[11px] text-slate-600 dark:text-slate-400">Min prominence</span>
          <div className="flex items-center gap-2">
            <input
              type="range"
              min={0}
              max={100}
              step={1}
              className="w-full accent-sky-600"
              value={clampInt(peaks.minProminence, 0, 100)}
              onChange={(event) => {
                const parsed = parseNumber(event.currentTarget.value)
                if (parsed === undefined) {
                  return
                }

                dispatch({
                  type: 'PEAKS_SET',
                  patch: { minProminence: clampInt(parsed, 0, 100) },
                })
              }}
            />
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              className="w-16 rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              value={clampInt(peaks.minProminence, 0, 100)}
              onChange={(event) => {
                const parsed = parseNumber(event.currentTarget.value)
                if (parsed === undefined) {
                  return
                }

                dispatch({
                  type: 'PEAKS_SET',
                  patch: { minProminence: clampInt(parsed, 0, 100) },
                })
              }}
            />
          </div>
        </label>

        <label className="space-y-1">
          <span className="text-[11px] text-slate-600 dark:text-slate-400">Min distance</span>
          <div className="flex items-center gap-2">
            <input
              type="range"
              min={0}
              max={200}
              step={1}
              className="w-full accent-sky-600"
              value={clampInt(peaks.minDistance, 0, 200)}
              onChange={(event) => {
                const parsed = parseNumber(event.currentTarget.value)
                if (parsed === undefined) {
                  return
                }

                dispatch({
                  type: 'PEAKS_SET',
                  patch: { minDistance: clampInt(parsed, 0, 200) },
                })
              }}
            />
            <input
              type="number"
              min={0}
              max={200}
              step={1}
              className="w-16 rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              value={clampInt(peaks.minDistance, 0, 200)}
              onChange={(event) => {
                const parsed = parseNumber(event.currentTarget.value)
                if (parsed === undefined) {
                  return
                }

                dispatch({
                  type: 'PEAKS_SET',
                  patch: { minDistance: clampInt(parsed, 0, 200) },
                })
              }}
            />
          </div>
        </label>

        <label className="space-y-1">
          <span className="text-[11px] text-slate-600 dark:text-slate-400">Max peaks</span>
          <div className="flex items-center gap-2">
            <input
              type="range"
              min={1}
              max={200}
              step={1}
              className="w-full accent-sky-600"
              value={clampInt(peaks.maxPeaks, 1, 200)}
              onChange={(event) => {
                const parsed = parseNumber(event.currentTarget.value)
                if (parsed === undefined) {
                  return
                }

                dispatch({
                  type: 'PEAKS_SET',
                  patch: { maxPeaks: clampInt(parsed, 1, 200) },
                })
              }}
            />
            <input
              type="number"
              min={1}
              max={200}
              step={1}
              className="w-16 rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              value={clampInt(peaks.maxPeaks, 1, 200)}
              onChange={(event) => {
                const parsed = parseNumber(event.currentTarget.value)
                if (parsed === undefined) {
                  return
                }

                dispatch({
                  type: 'PEAKS_SET',
                  patch: { maxPeaks: clampInt(parsed, 1, 200) },
                })
              }}
            />
          </div>
        </label>

        <label className="space-y-0.5">
          <span className="text-[11px] text-slate-600 dark:text-slate-400">Decimals</span>
          <input
            type="number"
            className="w-full rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            value={peaks.decimals}
            onChange={(event) => {
              const parsed = parseNumber(event.currentTarget.value)
              if (parsed === undefined) {
                return
              }

              dispatch({
                type: 'PEAKS_SET',
                patch: { decimals: Math.max(0, Math.round(parsed)) },
              })
            }}
          />
        </label>
      </div>

      <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300">
        <input
          type="checkbox"
          className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
          checked={peaks.useRegion}
          onChange={(event) =>
            dispatch({
              type: 'PEAKS_SET',
              patch: { useRegion: event.currentTarget.checked },
            })
          }
        />
        <span>Limit to X range</span>
      </label>

      {peaks.useRegion ? (
        <div className="grid grid-cols-2 gap-1">
          <label className="space-y-0.5">
            <span className="text-[11px] text-slate-600 dark:text-slate-400">X min</span>
            <input
              type="text"
              className="w-full rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              value={peaks.regionXMin}
              onChange={(event) =>
                dispatch({
                  type: 'PEAKS_SET',
                  patch: { regionXMin: event.currentTarget.value },
                })
              }
            />
          </label>

          <label className="space-y-0.5">
            <span className="text-[11px] text-slate-600 dark:text-slate-400">X max</span>
            <input
              type="text"
              className="w-full rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              value={peaks.regionXMax}
              onChange={(event) =>
                dispatch({
                  type: 'PEAKS_SET',
                  patch: { regionXMax: event.currentTarget.value },
                })
              }
            />
          </label>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-1">
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          disabled={!peaks.enabled || !activeId}
          onClick={handleDetectActive}
        >
          Detect (active)
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          disabled={!peaks.enabled || spectra.length === 0}
          onClick={handleDetectAll}
        >
          Detect ALL
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          disabled={!activeId || !hasActivePeaks}
          onClick={() => dispatch({ type: 'PEAKS_CLEAR_ACTIVE' })}
        >
          Clear (active)
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          disabled={!hasAnyPeaks}
          onClick={() => dispatch({ type: 'PEAKS_CLEAR_ALL' })}
        >
          Clear ALL
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          disabled={!hasActiveOffsets}
          onClick={() => dispatch({ type: 'PEAKS_LABEL_OFFSETS_RESET_ACTIVE' })}
        >
          Reset label positions (active)
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          disabled={!hasAnyOffsets}
          onClick={() => dispatch({ type: 'PEAKS_LABEL_OFFSETS_RESET_ALL' })}
        >
          Reset label positions (all)
        </button>
      </div>

      <p className="text-[11px] text-slate-500 dark:text-slate-400">
        Auto peaks: {autoPeakCount}
      </p>

      <p className="text-[11px] text-slate-500 dark:text-slate-400">
        Manual peaks store X only; Y is derived from the active curve.
      </p>
    </div>
  )
}
