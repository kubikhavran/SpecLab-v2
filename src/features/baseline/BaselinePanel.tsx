import { useMemo } from 'react'
import { useAppDispatch, useAppState } from '../../app/state/AppStore'
import { applyBaseline } from './applyBaseline'
import { aslsBaseline } from './aslsBaseline'

const LAMBDA_EXP_MIN = 4
const LAMBDA_EXP_MAX = 9

export function BaselinePanel() {
  const {
    spectra,
    activeSpectrumId,
    baseline,
    cosmicCleanYById,
    processedYById,
    baselineYById,
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
  const hasProcessedActive =
    activeSpectrum !== undefined &&
    Array.isArray(processedYById[activeSpectrum.id]) &&
    processedYById[activeSpectrum.id].length > 0
  const hasBaselineAny = Object.keys(baselineYById).length > 0
  const lambdaExp = Math.min(
    LAMBDA_EXP_MAX,
    Math.max(
      LAMBDA_EXP_MIN,
      Math.round(
        Math.log10(Math.max(baseline.lambda, 10 ** LAMBDA_EXP_MIN)),
      ),
    ),
  )
  const lambdaValue = 10 ** lambdaExp

  const handleApply = () => {
    if (!activeSpectrum) {
      return
    }

    const yInput = cosmicCleanYById[activeSpectrum.id] ?? activeSpectrum.y
    const baselineY = aslsBaseline(
      yInput,
      baseline.lambda,
      baseline.p,
      baseline.iterations,
    )
    const processedY = applyBaseline(yInput, baselineY)

    dispatch({
      type: 'SPECTRUM_SET_PROCESSED',
      id: activeSpectrum.id,
      processedY,
      baselineY,
    })
    dispatch({
      type: 'BASELINE_SET',
      patch: { enabled: true },
    })
  }

  const handleReset = () => {
    if (!activeSpectrum) {
      return
    }

    dispatch({ type: 'BASELINE_RESET_ACTIVE' })
    dispatch({
      type: 'BASELINE_SET',
      patch: { enabled: false },
    })
  }

  const handleApplyAll = () => {
    if (spectra.length === 0) {
      return
    }

    for (const spectrum of spectra) {
      const yInput = cosmicCleanYById[spectrum.id] ?? spectrum.y
      const baselineY = aslsBaseline(
        yInput,
        baseline.lambda,
        baseline.p,
        baseline.iterations,
      )
      const processedY = applyBaseline(yInput, baselineY)

      dispatch({
        type: 'SPECTRUM_SET_PROCESSED',
        id: spectrum.id,
        processedY,
        baselineY,
      })
    }

    dispatch({
      type: 'BASELINE_SET',
      patch: { enabled: true },
    })
  }

  const handleResetAll = () => {
    dispatch({ type: 'BASELINE_RESET_ALL' })
    dispatch({
      type: 'BASELINE_SET',
      patch: { enabled: false },
    })
  }

  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-xs text-slate-700">
        <input
          type="checkbox"
          className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
          checked={baseline.showOverlay}
          onChange={(event) =>
            dispatch({
              type: 'BASELINE_SET',
              patch: { showOverlay: event.currentTarget.checked },
            })
          }
        />
        <span>Show baseline overlay</span>
      </label>

      <label className="block space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-600">Lambda</span>
          <span className="text-[11px] text-slate-500">
            1e{lambdaExp} ({lambdaValue.toLocaleString()})
          </span>
        </div>
        <input
          type="range"
          min={LAMBDA_EXP_MIN}
          max={LAMBDA_EXP_MAX}
          step={1}
          className="w-full accent-sky-600"
          value={lambdaExp}
          onChange={(event) => {
            const exponent = Number(event.currentTarget.value)

            if (!Number.isFinite(exponent)) {
              return
            }

            const clampedExponent = Math.min(
              LAMBDA_EXP_MAX,
              Math.max(LAMBDA_EXP_MIN, Math.round(exponent)),
            )

            dispatch({
              type: 'BASELINE_SET',
              patch: { lambda: 10 ** clampedExponent },
            })
          }}
        />
      </label>

      <label className="block space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-600">p</span>
          <span className="text-[11px] text-slate-500">
            {baseline.p.toFixed(3)}
          </span>
        </div>
        <input
          type="range"
          min={0.001}
          max={0.1}
          step={0.001}
          className="w-full accent-sky-600"
          value={baseline.p}
          onChange={(event) => {
            const p = Number(event.currentTarget.value)

            if (!Number.isFinite(p)) {
              return
            }

            dispatch({
              type: 'BASELINE_SET',
              patch: { p: Math.min(0.1, Math.max(0.001, p)) },
            })
          }}
        />
      </label>

      <label className="block space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-600">Iterations</span>
          <span className="text-[11px] text-slate-500">
            {baseline.iterations}
          </span>
        </div>
        <input
          type="range"
          min={5}
          max={30}
          step={1}
          className="w-full accent-sky-600"
          value={baseline.iterations}
          onChange={(event) => {
            const iterations = Number(event.currentTarget.value)

            if (!Number.isFinite(iterations)) {
              return
            }

            dispatch({
              type: 'BASELINE_SET',
              patch: {
                iterations: Math.min(30, Math.max(5, Math.round(iterations))),
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
          Apply baseline
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={!canApply || !hasProcessedActive}
          onClick={handleReset}
        >
          Reset baseline
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
          disabled={!hasBaselineAny}
          onClick={handleResetAll}
        >
          Reset ALL
        </button>
      </div>
    </div>
  )
}
