import { useMemo, useState } from 'react'
import { useAppDispatch, useAppState } from '../../app/state/AppStore'
import { removeCosmicRays } from './removeCosmicRays'

function clampWindow(windowValue: number): number {
  const clamped = Math.max(5, Math.min(51, Math.round(windowValue)))
  return clamped % 2 === 0 ? clamped + 1 : clamped
}

function clampThreshold(threshold: number): number {
  return Math.max(3, Math.min(10, threshold))
}

function clampMaxWidth(maxWidth: number): number {
  return Math.max(1, Math.min(7, Math.round(maxWidth)))
}

function clampIterations(iterations: number): number {
  return Math.max(1, Math.min(3, Math.round(iterations)))
}

export function CosmicRaysPanel() {
  const { spectra, activeSpectrumId, cosmic, cosmicCleanYById } = useAppState()
  const dispatch = useAppDispatch()
  const [lastRemovedById, setLastRemovedById] = useState<Record<string, number>>(
    {},
  )
  const [lastRemovedTotal, setLastRemovedTotal] = useState<number | null>(null)

  const activeSpectrum = useMemo(
    () =>
      activeSpectrumId !== undefined
        ? spectra.find((spectrum) => spectrum.id === activeSpectrumId) ?? spectra[0]
        : spectra[0],
    [activeSpectrumId, spectra],
  )

  const canApply = activeSpectrum !== undefined
  const hasActiveCleaned =
    activeSpectrum !== undefined &&
    Array.isArray(cosmicCleanYById[activeSpectrum.id]) &&
    cosmicCleanYById[activeSpectrum.id].length > 0
  const hasAnyCleaned = Object.keys(cosmicCleanYById).length > 0
  const activeRemovedCount =
    activeSpectrum !== undefined
      ? lastRemovedById[activeSpectrum.id]
      : undefined

  const handleApplyActive = () => {
    if (!activeSpectrum) {
      return
    }

    const yInput = cosmicCleanYById[activeSpectrum.id] ?? activeSpectrum.y
    const result = removeCosmicRays(yInput, cosmic)

    dispatch({
      type: 'SPECTRUM_SET_COSMIC_CLEANED_Y',
      spectrumId: activeSpectrum.id,
      yClean: result.yClean,
      removedCount: result.removedCount,
    })

    setLastRemovedById((prev) => ({
      ...prev,
      [activeSpectrum.id]: result.removedCount,
    }))
    setLastRemovedTotal(null)
  }

  const handleResetActive = () => {
    if (!activeSpectrum) {
      return
    }

    dispatch({ type: 'COSMIC_RESET_ACTIVE' })
    setLastRemovedById((prev) => {
      const next = { ...prev }
      delete next[activeSpectrum.id]
      return next
    })
    setLastRemovedTotal(null)
  }

  const handleApplyAll = () => {
    if (spectra.length === 0) {
      return
    }

    let removedTotal = 0
    const nextRemovedById: Record<string, number> = {}

    for (const spectrum of spectra) {
      const yInput = cosmicCleanYById[spectrum.id] ?? spectrum.y
      const result = removeCosmicRays(yInput, cosmic)

      dispatch({
        type: 'SPECTRUM_SET_COSMIC_CLEANED_Y',
        spectrumId: spectrum.id,
        yClean: result.yClean,
        removedCount: result.removedCount,
      })

      removedTotal += result.removedCount
      nextRemovedById[spectrum.id] = result.removedCount
    }

    setLastRemovedById(nextRemovedById)
    setLastRemovedTotal(removedTotal)
  }

  const handleResetAll = () => {
    dispatch({ type: 'COSMIC_RESET_ALL' })
    setLastRemovedById({})
    setLastRemovedTotal(null)
  }

  return (
    <div className="space-y-2">
      <label className="block space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-600">Window</span>
          <span className="text-[11px] text-slate-500">{cosmic.window}</span>
        </div>
        <input
          type="range"
          min={5}
          max={51}
          step={2}
          className="w-full accent-sky-600"
          value={cosmic.window}
          onChange={(event) => {
            const windowValue = Number(event.currentTarget.value)
            if (!Number.isFinite(windowValue)) {
              return
            }

            dispatch({
              type: 'COSMIC_SET',
              patch: { window: clampWindow(windowValue) },
            })
          }}
        />
      </label>

      <label className="block space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-600">Threshold (MAD sigmas)</span>
          <span className="text-[11px] text-slate-500">{cosmic.threshold.toFixed(1)}</span>
        </div>
        <input
          type="range"
          min={3}
          max={10}
          step={0.5}
          className="w-full accent-sky-600"
          value={cosmic.threshold}
          onChange={(event) => {
            const threshold = Number(event.currentTarget.value)
            if (!Number.isFinite(threshold)) {
              return
            }

            dispatch({
              type: 'COSMIC_SET',
              patch: { threshold: clampThreshold(threshold) },
            })
          }}
        />
      </label>

      <label className="block space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-600">Max spike width</span>
          <span className="text-[11px] text-slate-500">{cosmic.maxWidth}</span>
        </div>
        <input
          type="range"
          min={1}
          max={7}
          step={1}
          className="w-full accent-sky-600"
          value={cosmic.maxWidth}
          onChange={(event) => {
            const maxWidth = Number(event.currentTarget.value)
            if (!Number.isFinite(maxWidth)) {
              return
            }

            dispatch({
              type: 'COSMIC_SET',
              patch: { maxWidth: clampMaxWidth(maxWidth) },
            })
          }}
        />
      </label>

      <label className="flex items-center gap-2 text-xs text-slate-700">
        <input
          type="checkbox"
          className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
          checked={cosmic.positiveOnly}
          onChange={(event) =>
            dispatch({
              type: 'COSMIC_SET',
              patch: { positiveOnly: event.currentTarget.checked },
            })
          }
        />
        <span>Positive spikes only</span>
      </label>

      <label className="block space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-600">Iterations</span>
          <span className="text-[11px] text-slate-500">{cosmic.iterations}</span>
        </div>
        <input
          type="range"
          min={1}
          max={3}
          step={1}
          className="w-full accent-sky-600"
          value={cosmic.iterations}
          onChange={(event) => {
            const iterations = Number(event.currentTarget.value)
            if (!Number.isFinite(iterations)) {
              return
            }

            dispatch({
              type: 'COSMIC_SET',
              patch: { iterations: clampIterations(iterations) },
            })
          }}
        />
      </label>

      <div className="flex flex-wrap gap-1">
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={!canApply}
          onClick={handleApplyActive}
        >
          Apply cosmic
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={!canApply || !hasActiveCleaned}
          onClick={handleResetActive}
        >
          Reset cosmic
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={spectra.length === 0}
          onClick={handleApplyAll}
        >
          Apply ALL
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={!hasAnyCleaned}
          onClick={handleResetAll}
        >
          Reset ALL
        </button>
      </div>

      {activeRemovedCount !== undefined ? (
        <p className="text-[11px] text-slate-500">
          Removed: {activeRemovedCount} spikes
        </p>
      ) : null}
      {lastRemovedTotal !== null ? (
        <p className="text-[11px] text-slate-500">
          Removed total: {lastRemovedTotal} spikes
        </p>
      ) : null}
    </div>
  )
}
