import type { KeyboardEvent } from 'react'
import { useState } from 'react'
import type { DataLabelingSettings, ExtractPreset, RenumberMode } from '../../app/types/core'
import { useAppDispatch, useAppState } from '../../app/state/AppStore'

export function SpectrumList() {
  const { spectra, activeSpectrumId, plot, dataLabeling } = useAppState()
  const dispatch = useAppDispatch()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftName, setDraftName] = useState('')

  const updateDataLabeling = (patch: Partial<DataLabelingSettings>) => {
    dispatch({
      type: 'DATA_LABELING_SET',
      patch,
    })
  }

  const updateLabelExtract = (
    patch: Partial<DataLabelingSettings['labelExtract']>,
  ) => {
    updateDataLabeling({
      labelExtract: {
        ...dataLabeling.labelExtract,
        ...patch,
      },
    })
  }

  const cancelRename = () => {
    setEditingId(null)
    setDraftName('')
  }

  const saveRename = (id: string) => {
    dispatch({
      type: 'SPECTRUM_RENAME',
      id,
      name: draftName,
    })

    cancelRename()
  }

  const handleRenameKeyDown = (
    event: KeyboardEvent<HTMLInputElement>,
    id: string,
  ) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      saveRename(id)
    }

    if (event.key === 'Escape') {
      event.preventDefault()
      cancelRename()
    }
  }

  const handleAutoLabel = () => {
    if (dataLabeling.renumberMode === 'extract') {
      if (dataLabeling.labelExtract.mode !== 'filename') {
        return
      }

      dispatch({
        type: 'SPECTRA_RENAME_BY_EXTRACT',
        source: 'filename',
        preset: dataLabeling.labelExtract.preset,
        prefix: dataLabeling.labelExtract.prefix,
        suffix: dataLabeling.labelExtract.suffix,
        ...(dataLabeling.labelExtract.preset === 'regex'
          ? { regex: dataLabeling.labelExtract.regex }
          : {}),
        ...(dataLabeling.labelExtract.preset === 'slice'
          ? {
              sliceStart: Number(dataLabeling.labelExtract.start),
              sliceEnd: Number(dataLabeling.labelExtract.end),
              trimResult: dataLabeling.labelExtract.trimResult,
              numbersOnly: dataLabeling.labelExtract.numbersOnly,
            }
          : {}),
      })
      return
    }

    dispatch({
      type: 'SPECTRA_RENAME_ALL',
      prefix: dataLabeling.renumberPrefix,
      mode: dataLabeling.renumberMode,
      reverse: dataLabeling.invertOrder,
      ...(dataLabeling.renumberMode === 'sequence'
        ? {
            start: Number(dataLabeling.sequenceStart),
            step: Number(dataLabeling.sequenceStep),
            suffix: dataLabeling.sequenceSuffix,
          }
        : {}),
    })
  }

  return (
    <div className="min-w-0 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
          Loaded
        </p>
        <button
          type="button"
          className="rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-600 hover:bg-slate-100"
          onClick={() => dispatch({ type: 'SPECTRA_CLEAR' })}
        >
          Clear
        </button>
      </div>
      <label className="flex items-center gap-2 text-xs text-slate-700">
        <input
          type="checkbox"
          className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
          checked={plot.reverseOverlayOrder}
          onChange={(event) =>
            dispatch({
              type: 'PLOT_SET',
              patch: { reverseOverlayOrder: event.currentTarget.checked },
            })
          }
          disabled={spectra.length < 2}
        />
        <span>Invert overlay order</span>
      </label>
      <p className="text-[11px] text-slate-500">Affects overlay stacking order.</p>

      <div className="flex flex-wrap items-center gap-1">
        <label className="sr-only" htmlFor="renumber-mode">
          Auto-label mode
        </label>
        <select
          id="renumber-mode"
          className="rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-700"
          value={dataLabeling.renumberMode}
          onChange={(event) => {
            const mode = event.currentTarget.value as RenumberMode
            updateDataLabeling({ renumberMode: mode })
            if (mode !== 'index') {
              updateDataLabeling({ renumberPrefix: '' })
            }
            updateLabelExtract({
              mode: mode === 'extract' ? 'filename' : 'none',
            })
          }}
        >
          <option value="index">Numbers (1..N)</option>
          <option value="sequence">Sequence (start/step)</option>
          <option value="extract">Extract from filename</option>
        </select>

        <label className="sr-only" htmlFor="renumber-prefix">
          Auto-label prefix
        </label>
        <select
          id="renumber-prefix"
          className="rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-700"
          value={dataLabeling.renumberPrefix}
          onChange={(event) =>
            updateDataLabeling({ renumberPrefix: event.currentTarget.value })
          }
        >
          <option value="">Numbers only</option>
          <option value="S">S</option>
          <option value="Spec ">Spec </option>
        </select>
        <button
          type="button"
          className="rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-600 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          onClick={handleAutoLabel}
          disabled={spectra.length === 0}
        >
          {dataLabeling.renumberMode === 'extract' ? 'Apply extract' : 'Renumber'}
        </button>
      </div>
      {dataLabeling.renumberMode !== 'extract' ? (
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
            checked={dataLabeling.invertOrder}
            onChange={(event) =>
              updateDataLabeling({ invertOrder: event.currentTarget.checked })
            }
          />
          <span>Invert order</span>
        </label>
      ) : null}
      {dataLabeling.renumberMode === 'sequence' ? (
        <div className="grid grid-cols-3 gap-1">
          <label className="space-y-0.5">
            <span className="text-[11px] text-slate-600">Start</span>
            <input
              type="text"
              inputMode="decimal"
              className="w-full rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-700"
              value={dataLabeling.sequenceStart}
              onChange={(event) =>
                updateDataLabeling({ sequenceStart: event.currentTarget.value })
              }
            />
          </label>
          <label className="space-y-0.5">
            <span className="text-[11px] text-slate-600">Step</span>
            <input
              type="text"
              inputMode="decimal"
              className="w-full rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-700"
              value={dataLabeling.sequenceStep}
              onChange={(event) =>
                updateDataLabeling({ sequenceStep: event.currentTarget.value })
              }
            />
          </label>
          <label className="space-y-0.5">
            <span className="text-[11px] text-slate-600">Suffix</span>
            <input
              type="text"
              placeholder=" mV"
              className="w-full rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-700"
              value={dataLabeling.sequenceSuffix}
              onChange={(event) =>
                updateDataLabeling({ sequenceSuffix: event.currentTarget.value })
              }
            />
          </label>
        </div>
      ) : dataLabeling.renumberMode === 'extract' ? (
        <div className="space-y-1">
          <label className="space-y-0.5">
            <span className="text-[11px] text-slate-600">Preset</span>
            <select
              className="w-full rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-700"
              value={dataLabeling.labelExtract.preset}
              onChange={(event) =>
                updateLabelExtract({
                  preset: event.currentTarget.value as ExtractPreset,
                })
              }
            >
              <option value="mv">mV token (...50mV...)</option>
              <option value="firstNumber">First number</option>
              <option value="lastNumber">Last number</option>
              <option value="regex">Custom regex</option>
              <option value="slice">Slice (start..end)</option>
            </select>
          </label>
          {dataLabeling.labelExtract.preset === 'regex' ? (
            <label className="space-y-0.5">
              <span className="text-[11px] text-slate-600">Regex</span>
              <input
                type="text"
                className="w-full rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-700"
                placeholder="(\\d+)mV"
                value={dataLabeling.labelExtract.regex}
                onChange={(event) =>
                  updateLabelExtract({ regex: event.currentTarget.value })
                }
              />
            </label>
          ) : null}
          {dataLabeling.labelExtract.preset === 'slice' ? (
            <div className="space-y-1">
              <div className="grid grid-cols-2 gap-1">
                <label className="space-y-0.5">
                  <span className="text-[11px] text-slate-600">Start</span>
                  <input
                    type="text"
                    inputMode="numeric"
                    className="w-full rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-700"
                    value={dataLabeling.labelExtract.start}
                    onChange={(event) =>
                      updateLabelExtract({ start: event.currentTarget.value })
                    }
                  />
                </label>
                <label className="space-y-0.5">
                  <span className="text-[11px] text-slate-600">End</span>
                  <input
                    type="text"
                    inputMode="numeric"
                    className="w-full rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-700"
                    value={dataLabeling.labelExtract.end}
                    onChange={(event) =>
                      updateLabelExtract({ end: event.currentTarget.value })
                    }
                  />
                </label>
              </div>
              <label className="flex items-center gap-2 text-xs text-slate-700">
                <input
                  type="checkbox"
                  className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
                  checked={dataLabeling.labelExtract.trimResult}
                  onChange={(event) =>
                    updateLabelExtract({ trimResult: event.currentTarget.checked })
                  }
                />
                <span>Trim result</span>
              </label>
              <label className="flex items-center gap-2 text-xs text-slate-700">
                <input
                  type="checkbox"
                  className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
                  checked={dataLabeling.labelExtract.numbersOnly}
                  onChange={(event) =>
                    updateLabelExtract({
                      numbersOnly: event.currentTarget.checked,
                    })
                  }
                />
                <span>Numbers only</span>
              </label>
              <p className="text-[11px] text-slate-500">
                Extracts the first numeric token from the sliced text (e.g.
                "_-50mV" -&gt; "-50").
              </p>
              <p className="text-[11px] text-slate-500">
                Supports negative indices (from end), e.g. -1 is last char.
                Range is [start, end) (end exclusive).
              </p>
            </div>
          ) : null}
          <div className="grid grid-cols-2 gap-1">
            <label className="space-y-0.5">
              <span className="text-[11px] text-slate-600">Prefix</span>
              <input
                type="text"
                className="w-full rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-700"
                value={dataLabeling.labelExtract.prefix}
                onChange={(event) =>
                  updateLabelExtract({ prefix: event.currentTarget.value })
                }
              />
            </label>
            <label className="space-y-0.5">
              <span className="text-[11px] text-slate-600">Suffix</span>
              <input
                type="text"
                className="w-full rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-700"
                placeholder=" mV"
                value={dataLabeling.labelExtract.suffix}
                onChange={(event) =>
                  updateLabelExtract({ suffix: event.currentTarget.value })
                }
              />
            </label>
          </div>
        </div>
      ) : null}

      {spectra.length === 0 ? (
        <p className="text-[11px] text-slate-400">No spectra loaded.</p>
      ) : (
        <ul className="space-y-1">
          {spectra.map((spectrum, index) => {
            const isActive = spectrum.id === activeSpectrumId
            const isEditing = spectrum.id === editingId
            const isFirst = index === 0
            const isLast = index === spectra.length - 1

            return (
              <li key={spectrum.id}>
                <div
                  className={[
                    'min-w-0 rounded-md border p-2',
                    isActive
                      ? 'border-sky-300 bg-sky-50'
                      : 'border-slate-200 bg-white',
                  ].join(' ')}
                >
                  {isEditing ? (
                    <div className="min-w-0 space-y-1.5">
                      <input
                        type="text"
                        autoFocus
                        value={draftName}
                        className="w-full min-w-0 rounded border border-slate-300 px-2 py-1 text-xs text-slate-700"
                        onChange={(event) => setDraftName(event.currentTarget.value)}
                        onKeyDown={(event) =>
                          handleRenameKeyDown(event, spectrum.id)
                        }
                      />
                      <p className="text-[11px] text-slate-500">
                        {spectrum.x.length} points
                      </p>
                      <div className="flex flex-wrap gap-1">
                        <button
                          type="button"
                          className="rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-600 hover:bg-slate-100"
                          onClick={() => saveRename(spectrum.id)}
                        >
                          Save
                        </button>
                        <button
                          type="button"
                          className="rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-600 hover:bg-slate-100"
                          onClick={cancelRename}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="min-w-0 space-y-1.5">
                      <div className="flex min-w-0 items-center justify-between gap-2">
                        <button
                          type="button"
                          className="min-w-0 flex-1 text-left"
                          onClick={() =>
                            dispatch({
                              type: 'SPECTRUM_SET_ACTIVE',
                              id: spectrum.id,
                            })
                          }
                        >
                          <span className="block truncate text-xs font-medium text-slate-700">
                            {spectrum.name}
                          </span>
                        </button>
                        <span className="shrink-0 text-[11px] text-slate-500">
                          {spectrum.x.length} points
                        </span>
                      </div>

                      <div className="flex flex-wrap gap-1">
                        <button
                          type="button"
                          className="rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-600 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
                          onClick={() =>
                            dispatch({
                              type: 'SPECTRUM_SET_ACTIVE',
                              id: spectrum.id,
                            })
                          }
                          disabled={isActive}
                        >
                          Select
                        </button>

                        <button
                          type="button"
                          aria-label={`Move up ${spectrum.name}`}
                          className="rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-600 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
                          onClick={() =>
                            dispatch({
                              type: 'SPECTRUM_MOVE',
                              id: spectrum.id,
                              direction: 'up',
                            })
                          }
                          disabled={isFirst}
                        >
                          &uarr;
                        </button>

                        <button
                          type="button"
                          aria-label={`Move down ${spectrum.name}`}
                          className="rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-600 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
                          onClick={() =>
                            dispatch({
                              type: 'SPECTRUM_MOVE',
                              id: spectrum.id,
                              direction: 'down',
                            })
                          }
                          disabled={isLast}
                        >
                          &darr;
                        </button>

                        <button
                          type="button"
                          className="rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-600 hover:bg-slate-100"
                          onClick={() => {
                            setEditingId(spectrum.id)
                            setDraftName(spectrum.name)
                          }}
                        >
                          Rename
                        </button>

                        <button
                          type="button"
                          className="rounded border border-red-200 px-1.5 py-0.5 text-xs text-red-600 hover:bg-red-50"
                          onClick={() =>
                            dispatch({ type: 'SPECTRUM_REMOVE', id: spectrum.id })
                          }
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

