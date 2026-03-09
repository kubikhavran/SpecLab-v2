import { useMemo } from 'react'
import { useAppDispatch, useAppState } from '../../app/state/AppStore'
import { savgolSmooth } from './savgol'

function clampPolyOrder(polyOrder: number, window: number): number {
  const minValue = 2
  const maxValue = Math.min(5, Math.max(minValue, window - 1))

  return Math.min(maxValue, Math.max(minValue, Math.round(polyOrder)))
}

export function SmoothingPanel() {
  const {
    spectra,
    activeSpectrumId,
    smoothing,
    cosmicCleanYById,
    processedYById,
    smoothedYById,
  } = useAppState()
  const dispatch = useAppDispatch()

  const activeSpectrum = useMemo(
    () =>
      activeSpectrumId !== undefined
        ? spectra.find((spectrum) => spectrum.id === activeSpectrumId)
        : undefined,
    [activeSpectrumId, spectra],
  )

  const canApply = activeSpectrum !== undefined
  const canApplyAll = spectra.length > 0
  const hasSmoothedActive =
    activeSpectrum !== undefined &&
    Array.isArray(smoothedYById[activeSpectrum.id]) &&
    smoothedYById[activeSpectrum.id].length > 0
  const hasSmoothedAny = Object.keys(smoothedYById).length > 0

  const handleApply = () => {
    if (!activeSpectrum) {
      return
    }

    const baseY =
      processedYById[activeSpectrum.id] ??
      (cosmicCleanYById[activeSpectrum.id] ?? activeSpectrum.y)
    const clampedPolyOrder = clampPolyOrder(smoothing.polyOrder, smoothing.window)
    const smoothed = savgolSmooth(baseY, smoothing.window, clampedPolyOrder)

    dispatch({
      type: 'SPECTRUM_SET_SMOOTHED_Y',
      id: activeSpectrum.id,
      smoothedY: smoothed,
    })
    dispatch({
      type: 'SMOOTHING_SET',
      patch: { polyOrder: clampedPolyOrder },
    })
  }

  const handleReset = () => {
    if (!activeSpectrum) {
      return
    }

    dispatch({ type: 'SMOOTHING_RESET_ACTIVE' })
  }

  const handleApplyAll = () => {
    if (spectra.length === 0) {
      return
    }

    const clampedPolyOrder = clampPolyOrder(smoothing.polyOrder, smoothing.window)

    for (const spectrum of spectra) {
      const baseY =
        processedYById[spectrum.id] ??
        (cosmicCleanYById[spectrum.id] ?? spectrum.y)
      const smoothed = savgolSmooth(baseY, smoothing.window, clampedPolyOrder)

      dispatch({
        type: 'SPECTRUM_SET_SMOOTHED_Y',
        id: spectrum.id,
        smoothedY: smoothed,
      })
    }

    dispatch({
      type: 'SMOOTHING_SET',
      patch: { polyOrder: clampedPolyOrder },
    })
  }

  const handleResetAll = () => {
    dispatch({ type: 'SMOOTHING_RESET_ALL' })
  }

  return (
    <div className="space-y-2">
      <label className="block space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-600">Window</span>
          <span className="text-[11px] text-slate-500">{smoothing.window}</span>
        </div>
        <input
          type="range"
          min={5}
          max={51}
          step={2}
          className="w-full accent-sky-600"
          value={smoothing.window}
          onChange={(event) => {
            const windowValue = Number(event.currentTarget.value)

            if (!Number.isFinite(windowValue)) {
              return
            }

            const nextWindow = Math.max(5, Math.min(51, Math.round(windowValue)))
            const nextPolyOrder = clampPolyOrder(smoothing.polyOrder, nextWindow)

            dispatch({
              type: 'SMOOTHING_SET',
              patch: { window: nextWindow, polyOrder: nextPolyOrder },
            })
          }}
        />
      </label>

      <label className="block space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-600">Poly order</span>
          <span className="text-[11px] text-slate-500">
            {clampPolyOrder(smoothing.polyOrder, smoothing.window)}
          </span>
        </div>
        <input
          type="range"
          min={2}
          max={5}
          step={1}
          className="w-full accent-sky-600"
          value={clampPolyOrder(smoothing.polyOrder, smoothing.window)}
          onChange={(event) => {
            const polyOrder = Number(event.currentTarget.value)

            if (!Number.isFinite(polyOrder)) {
              return
            }

            dispatch({
              type: 'SMOOTHING_SET',
              patch: {
                polyOrder: clampPolyOrder(polyOrder, smoothing.window),
              },
            })
          }}
        />
      </label>

      <div className="flex flex-wrap gap-1">
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={!canApply}
          onClick={handleApply}
        >
          Apply smoothing
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={!canApply || !hasSmoothedActive}
          onClick={handleReset}
        >
          Reset smoothing
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={!canApplyAll}
          onClick={handleApplyAll}
        >
          Apply ALL
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={!hasSmoothedAny}
          onClick={handleResetAll}
        >
          Reset ALL
        </button>
      </div>
    </div>
  )
}
