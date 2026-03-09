import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react'
import type { GraphicsPalette } from '../../app/types/core'
import { useAppDispatch, useAppState } from '../../app/state/AppStore'
import { toSubscript, toSuperscript } from '../../lib/text/superSub'

const fontFamilies = ['Arial', 'Inter', 'Times New Roman', 'Courier New'] as const
const paletteOptions: Array<{ label: string; value: GraphicsPalette }> = [
  { label: 'Auto (Plotly)', value: 'auto' },
  { label: 'Publication Bold', value: 'pubBold' },
  { label: 'Publication Colorblind', value: 'pubColorblind' },
  { label: 'Tol Bright', value: 'tolBright' },
  { label: 'Tol Muted', value: 'tolMuted' },
  { label: 'Deep Rainbow', value: 'deepRainbow' },
  { label: 'Viridis (dark)', value: 'viridisDark' },
  { label: 'Plasma (dark)', value: 'plasmaDark' },
  { label: 'Cividis (dark)', value: 'cividisDark' },
  { label: 'Tableau 10', value: 'tableau10' },
  { label: 'Dark2', value: 'dark2' },
  { label: 'Paired', value: 'paired' },
  { label: 'Okabe-Ito (Colorblind)', value: 'colorblind' },
  { label: 'Electrochem (red->purple)', value: 'electrochem' },
  { label: 'Monochrome', value: 'mono' },
  { label: 'Neon', value: 'neon' },
]

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

type AxisLabelKey = 'xLabel' | 'yLabel'
type ScriptKind = 'super' | 'sub'

const SUPER_PLACEHOLDER = '\u2070'
const SUB_PLACEHOLDER = '\u2080'

export function GraphicsPanel() {
  const { graphics } = useAppState()
  const dispatch = useAppDispatch()
  const [widthText, setWidthText] = useState(String(graphics.exportWidth))
  const [heightText, setHeightText] = useState(String(graphics.exportHeight))
  const xLabelInputRef = useRef<HTMLInputElement>(null)
  const yLabelInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setWidthText(String(graphics.exportWidth))
  }, [graphics.exportWidth])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHeightText(String(graphics.exportHeight))
  }, [graphics.exportHeight])

  const commitSize = (kind: 'w' | 'h') => {
    const raw = kind === 'w' ? widthText : heightText
    const parsed = Number(raw.replace(/[^\d]/g, ''))

    if (!Number.isFinite(parsed)) {
      return
    }

    const clamped = Math.max(200, Math.min(20000, parsed))
    dispatch({
      type: 'GRAPHICS_SET',
      patch: kind === 'w' ? { exportWidth: clamped } : { exportHeight: clamped },
    })
  }

  const onSizeKeyDown = (kind: 'w' | 'h') => (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      commitSize(kind)
    }
  }

  const setAxisLabel = (axisLabel: AxisLabelKey, nextValue: string) => {
    dispatch({
      type: 'GRAPHICS_SET',
      patch: axisLabel === 'xLabel' ? { xLabel: nextValue } : { yLabel: nextValue },
    })
  }

  const applyLabelScript = (
    kind: ScriptKind,
    axisLabel: AxisLabelKey,
    currentValue: string,
  ) => {
    const inputRef = axisLabel === 'xLabel' ? xLabelInputRef : yLabelInputRef
    const input = inputRef.current
    if (!input) {
      return
    }

    const selectionStart = input.selectionStart ?? currentValue.length
    const selectionEnd = input.selectionEnd ?? selectionStart
    const hasSelection = selectionEnd > selectionStart
    const converter = kind === 'super' ? toSuperscript : toSubscript
    const sourceText = hasSelection
      ? currentValue.slice(selectionStart, selectionEnd)
      : kind === 'super'
        ? SUPER_PLACEHOLDER
        : SUB_PLACEHOLDER
    const converted = converter(sourceText)
    const nextValue = `${currentValue.slice(0, selectionStart)}${converted}${currentValue.slice(selectionEnd)}`
    const nextSelectionStart = hasSelection
      ? selectionStart + converted.length
      : selectionStart
    const nextSelectionEnd = hasSelection
      ? nextSelectionStart
      : nextSelectionStart + converted.length

    setAxisLabel(axisLabel, nextValue)

    requestAnimationFrame(() => {
      const nextInput = inputRef.current
      if (!nextInput) {
        return
      }
      nextInput.focus()
      nextInput.setSelectionRange(nextSelectionStart, nextSelectionEnd)
    })
  }

  const onAxisLabelKeyDown = (
    axisLabel: AxisLabelKey,
    currentValue: string,
  ) => (event: KeyboardEvent<HTMLInputElement>) => {
    const wantsSuperscript =
      event.ctrlKey &&
      event.shiftKey &&
      (event.code === 'Period' || event.key === '.' || event.key === '>')
    const wantsSubscript =
      event.ctrlKey &&
      event.shiftKey &&
      (event.code === 'Comma' || event.key === ',' || event.key === '<')

    if (!wantsSuperscript && !wantsSubscript) {
      return
    }

    event.preventDefault()
    applyLabelScript(
      wantsSuperscript ? 'super' : 'sub',
      axisLabel,
      currentValue,
    )
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-1">
        <label className="space-y-0.5">
          <div className="flex items-center justify-between gap-1">
            <span className="text-[11px] text-slate-600">X label</span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                className="rounded border border-slate-300 px-1 py-0.5 text-[10px] text-slate-700 hover:bg-slate-100"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() =>
                  applyLabelScript(
                    'super',
                    'xLabel',
                    graphics.xLabel,
                  )
                }
                aria-label="Superscript selected X label text"
              >
                x^
              </button>
              <button
                type="button"
                className="rounded border border-slate-300 px-1 py-0.5 text-[10px] text-slate-700 hover:bg-slate-100"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() =>
                  applyLabelScript(
                    'sub',
                    'xLabel',
                    graphics.xLabel,
                  )
                }
                aria-label="Subscript selected X label text"
              >
                x_
              </button>
            </div>
          </div>
          <input
            ref={xLabelInputRef}
            type="text"
            className="w-full rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-700"
            value={graphics.xLabel}
            onChange={(event) =>
              dispatch({
                type: 'GRAPHICS_SET',
                patch: { xLabel: event.currentTarget.value },
              })
            }
            onKeyDown={onAxisLabelKeyDown(
              'xLabel',
              graphics.xLabel,
            )}
          />
        </label>
        <label className="space-y-0.5">
          <div className="flex items-center justify-between gap-1">
            <span className="text-[11px] text-slate-600">Y label</span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                className="rounded border border-slate-300 px-1 py-0.5 text-[10px] text-slate-700 hover:bg-slate-100"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() =>
                  applyLabelScript(
                    'super',
                    'yLabel',
                    graphics.yLabel,
                  )
                }
                aria-label="Superscript selected Y label text"
              >
                x^
              </button>
              <button
                type="button"
                className="rounded border border-slate-300 px-1 py-0.5 text-[10px] text-slate-700 hover:bg-slate-100"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() =>
                  applyLabelScript(
                    'sub',
                    'yLabel',
                    graphics.yLabel,
                  )
                }
                aria-label="Subscript selected Y label text"
              >
                x_
              </button>
            </div>
          </div>
          <input
            ref={yLabelInputRef}
            type="text"
            className="w-full rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-700"
            value={graphics.yLabel}
            onChange={(event) =>
              dispatch({
                type: 'GRAPHICS_SET',
                patch: { yLabel: event.currentTarget.value },
              })
            }
            onKeyDown={onAxisLabelKeyDown(
              'yLabel',
              graphics.yLabel,
            )}
          />
        </label>
      </div>
      <p className="text-[11px] text-slate-500">
        Tip: use ^{'{...}'} for superscript and _{'{...}'} for subscript (e.g.,
        {' '}cm^{'{-1}'}, E_{'{corr}'}).
      </p>

      <div className="grid grid-cols-2 gap-1">
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
            checked={graphics.axisLabelBold}
            onChange={(event) =>
              dispatch({
                type: 'GRAPHICS_SET',
                patch: { axisLabelBold: event.currentTarget.checked },
              })
            }
          />
          <span>Axis labels bold</span>
        </label>
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
            checked={graphics.axisLabelItalic}
            onChange={(event) =>
              dispatch({
                type: 'GRAPHICS_SET',
                patch: { axisLabelItalic: event.currentTarget.checked },
              })
            }
          />
          <span>Axis labels italic</span>
        </label>
      </div>

      <div className="grid grid-cols-2 gap-1">
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
            checked={graphics.showXTickLabels}
            onChange={(event) =>
              dispatch({
                type: 'GRAPHICS_SET',
                patch: { showXTickLabels: event.currentTarget.checked },
              })
            }
          />
          <span>Show X tick labels</span>
        </label>
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
            checked={graphics.showYTickLabels}
            onChange={(event) =>
              dispatch({
                type: 'GRAPHICS_SET',
                patch: { showYTickLabels: event.currentTarget.checked },
              })
            }
          />
          <span>Show Y tick labels</span>
        </label>
      </div>

      <div className="grid grid-cols-2 gap-1">
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
            checked={graphics.tickLabelBold}
            onChange={(event) =>
              dispatch({
                type: 'GRAPHICS_SET',
                patch: { tickLabelBold: event.currentTarget.checked },
              })
            }
          />
          <span>Tick labels bold</span>
        </label>
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
            checked={graphics.tickLabelItalic}
            onChange={(event) =>
              dispatch({
                type: 'GRAPHICS_SET',
                patch: { tickLabelItalic: event.currentTarget.checked },
              })
            }
          />
          <span>Tick labels italic</span>
        </label>
      </div>

      <div className="grid grid-cols-2 gap-1">
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
            checked={graphics.showXTickMarks}
            onChange={(event) =>
              dispatch({
                type: 'GRAPHICS_SET',
                patch: { showXTickMarks: event.currentTarget.checked },
              })
            }
          />
          <span>Show X tick marks</span>
        </label>
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
            checked={graphics.showYTickMarks}
            onChange={(event) =>
              dispatch({
                type: 'GRAPHICS_SET',
                patch: { showYTickMarks: event.currentTarget.checked },
              })
            }
          />
          <span>Show Y tick marks</span>
        </label>
      </div>

      <div className="grid grid-cols-2 gap-1">
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
            checked={graphics.showGrid}
            onChange={(event) =>
              dispatch({
                type: 'GRAPHICS_SET',
                patch: { showGrid: event.currentTarget.checked },
              })
            }
          />
          <span>Show grid</span>
        </label>
        <label className="space-y-0.5">
          <span className="text-[11px] text-slate-600">Grid color</span>
          <input
            type="color"
            className="h-8 w-full rounded border border-slate-300 p-1"
            value={graphics.gridColor}
            onChange={(event) =>
              dispatch({
                type: 'GRAPHICS_SET',
                patch: { gridColor: event.currentTarget.value },
              })
            }
          />
        </label>
      </div>

      <label className="block space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-600">Grid width</span>
          <span className="text-[11px] text-slate-500">{graphics.gridWidth}</span>
        </div>
        <input
          type="range"
          min={1}
          max={3}
          step={1}
          className="w-full accent-sky-600"
          value={graphics.gridWidth}
          onChange={(event) =>
            dispatch({
              type: 'GRAPHICS_SET',
              patch: {
                gridWidth: clamp(Number(event.currentTarget.value), 1, 3),
              },
            })
          }
        />
      </label>

      <div className="grid grid-cols-2 gap-1">
        <label className="space-y-0.5">
          <span className="text-[11px] text-slate-600">Axis line color</span>
          <input
            type="color"
            className="h-8 w-full rounded border border-slate-300 p-1"
            value={graphics.axisLineColor}
            onChange={(event) =>
              dispatch({
                type: 'GRAPHICS_SET',
                patch: { axisLineColor: event.currentTarget.value },
              })
            }
          />
        </label>
        <label className="space-y-0.5">
          <span className="text-[11px] text-slate-600">Frame</span>
          <select
            className="w-full rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-700"
            value={graphics.frameMode}
            onChange={(event) =>
              dispatch({
                type: 'GRAPHICS_SET',
                patch: {
                  frameMode: event.currentTarget.value as 'open' | 'box',
                },
              })
            }
          >
            <option value="open">Open (left/bottom)</option>
            <option value="box">Box (all sides)</option>
          </select>
        </label>
      </div>

      <label className="block space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-600">Axis line width</span>
          <span className="text-[11px] text-slate-500">{graphics.axisLineWidth}</span>
        </div>
        <input
          type="range"
          min={1}
          max={6}
          step={1}
          className="w-full accent-sky-600"
          value={graphics.axisLineWidth}
          onChange={(event) =>
            dispatch({
              type: 'GRAPHICS_SET',
              patch: {
                axisLineWidth: clamp(Number(event.currentTarget.value), 1, 6),
              },
            })
          }
        />
      </label>

      <label className="block space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-600">Trace line width</span>
          <span className="text-[11px] text-slate-500">{graphics.traceLineWidth}</span>
        </div>
        <input
          type="range"
          min={1}
          max={6}
          step={1}
          className="w-full accent-sky-600"
          value={graphics.traceLineWidth}
          onChange={(event) =>
            dispatch({
              type: 'GRAPHICS_SET',
              patch: {
                traceLineWidth: clamp(Number(event.currentTarget.value), 1, 6),
              },
            })
          }
        />
      </label>

      <label className="block space-y-0.5">
        <span className="text-[11px] text-slate-600">Font family</span>
        <select
          className="w-full rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-700"
          value={graphics.fontFamily}
          onChange={(event) =>
            dispatch({
              type: 'GRAPHICS_SET',
              patch: { fontFamily: event.currentTarget.value },
            })
          }
        >
          {fontFamilies.map((family) => (
            <option key={family} value={family}>
              {family}
            </option>
          ))}
        </select>
      </label>

      <label className="block space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-600">Base font size</span>
          <span className="text-[11px] text-slate-500">{graphics.baseFontSize}</span>
        </div>
        <input
          type="range"
          min={10}
          max={48}
          step={1}
          className="w-full accent-sky-600"
          value={graphics.baseFontSize}
          onChange={(event) =>
            dispatch({
              type: 'GRAPHICS_SET',
              patch: {
                baseFontSize: clamp(Number(event.currentTarget.value), 10, 48),
              },
            })
          }
        />
      </label>

      <label className="block space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-600">Tick font size</span>
          <span className="text-[11px] text-slate-500">{graphics.tickFontSize}</span>
        </div>
        <input
          type="range"
          min={8}
          max={36}
          step={1}
          className="w-full accent-sky-600"
          value={graphics.tickFontSize}
          onChange={(event) =>
            dispatch({
              type: 'GRAPHICS_SET',
              patch: {
                tickFontSize: clamp(Number(event.currentTarget.value), 8, 36),
              },
            })
          }
        />
      </label>

      <label className="block space-y-0.5">
        <span className="text-[11px] text-slate-600">Palette</span>
        <select
          className="w-full rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-700"
          value={graphics.palette}
          onChange={(event) =>
            dispatch({
              type: 'GRAPHICS_SET',
              patch: { palette: event.currentTarget.value as GraphicsPalette },
            })
          }
        >
          {paletteOptions.map((palette) => (
            <option key={palette.value} value={palette.value}>
              {palette.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-2 text-xs text-slate-700">
        <input
          type="checkbox"
          className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
          checked={graphics.inlineSpectrumLabels}
          onChange={(event) =>
            dispatch({
              type: 'GRAPHICS_SET',
              patch: { inlineSpectrumLabels: event.currentTarget.checked },
            })
          }
        />
        <span>Inline spectrum labels</span>
      </label>
      <div className="grid grid-cols-2 gap-1">
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
            checked={graphics.spectrumLabelBold}
            disabled={!graphics.inlineSpectrumLabels}
            onChange={(event) =>
              dispatch({
                type: 'GRAPHICS_SET',
                patch: { spectrumLabelBold: event.currentTarget.checked },
              })
            }
          />
          <span>Spectrum labels bold</span>
        </label>
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
            checked={graphics.spectrumLabelItalic}
            disabled={!graphics.inlineSpectrumLabels}
            onChange={(event) =>
              dispatch({
                type: 'GRAPHICS_SET',
                patch: { spectrumLabelItalic: event.currentTarget.checked },
              })
            }
          />
          <span>Spectrum labels italic</span>
        </label>
      </div>

      <div className="grid grid-cols-2 gap-1">
        <label className="space-y-0.5">
          <span className="text-[11px] text-slate-600">Width</span>
          <input
            type="text"
            inputMode="numeric"
            className="w-full rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-700"
            value={widthText}
            onChange={(event) => setWidthText(event.currentTarget.value)}
            onBlur={() => commitSize('w')}
            onKeyDown={onSizeKeyDown('w')}
          />
        </label>
        <label className="space-y-0.5">
          <span className="text-[11px] text-slate-600">Height</span>
          <input
            type="text"
            inputMode="numeric"
            className="w-full rounded border border-slate-300 px-1.5 py-1 text-xs text-slate-700"
            value={heightText}
            onChange={(event) => setHeightText(event.currentTarget.value)}
            onBlur={() => commitSize('h')}
            onKeyDown={onSizeKeyDown('h')}
          />
        </label>
      </div>
      <label className="flex items-center gap-2 text-xs text-slate-700">
        <input
          type="checkbox"
          className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
          checked={graphics.previewCanvasSize}
          onChange={(event) =>
            dispatch({
              type: 'GRAPHICS_SET',
              patch: { previewCanvasSize: event.currentTarget.checked },
            })
          }
        />
        <span>Preview export size on canvas</span>
      </label>
      <p className="text-[11px] text-slate-400">
        Used for PNG/SVG export size (px).
      </p>
    </div>
  )
}

