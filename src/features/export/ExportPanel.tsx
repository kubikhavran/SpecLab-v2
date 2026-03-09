import type { MutableRefObject } from 'react'
import { useEffect, useMemo, useState } from 'react'
import Plotly from 'plotly.js-dist-min'
import type { Data, Layout, PlotlyHTMLElement } from 'plotly.js'
import { useAppDispatch, useAppState } from '../../app/state/AppStore'
import { getExportFilename } from './exportFilename'
import {
  decodePlotlySvgDataUrl,
  downloadPngFromSvg,
  downloadSvg,
  patchTickStyles,
} from './exportSvgPipeline'
import { exportAllToZip } from './exportAllToZip'
import {
  chooseExportFolder,
  EXPORT_FOLDER_STORAGE_KEY,
  isTauriRuntime,
  saveTextOutput,
} from './exportSave'
import { spectrumToDelimitedText } from './exportSpectrumData'

type ExportPanelProps = {
  plotDivRef: MutableRefObject<PlotlyHTMLElement | null>
}

type ExportFormat = 'png' | 'svg'

type LooseAnnotation = Record<string, unknown> & {
  bgcolor?: unknown
  bordercolor?: unknown
  borderwidth?: unknown
  showarrow?: unknown
}

type LooseLayout = {
  paper_bgcolor?: unknown
  plot_bgcolor?: unknown
  annotations?: unknown
}

type LooseTrace = {
  line?: { width?: unknown }
}

type GraphDivState = PlotlyHTMLElement & {
  layout?: LooseLayout
  _fullLayout?: LooseLayout
  data?: LooseTrace[]
}

type LooseSpectrumTrace = {
  type?: unknown
  mode?: unknown
  meta?: unknown
  line?: { width?: unknown }
}

function clampInt(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n))
}

function isTransparentColor(color: string | undefined): boolean {
  if (!color) {
    return true
  }

  const normalized = color.trim().toLowerCase()
  if (!normalized || normalized === 'transparent') {
    return true
  }

  if (!normalized.startsWith('rgba(')) {
    return false
  }

  const channels = normalized
    .slice(5, -1)
    .split(',')
    .map((part) => Number(part.trim()))

  return channels.length === 4 && Number.isFinite(channels[3]) && channels[3] <= 0
}

function getInlineLabelBgColor(color: string | undefined): string {
  if (isTransparentColor(color)) {
    return 'rgba(0,0,0,0)'
  }

  return color ?? 'rgba(0,0,0,0)'
}

function asString(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback
}

function getPrimarySpectrumTraceWidths(
  graphDiv: PlotlyHTMLElement,
): { indexes: number[]; widths: number[]; uniformWidth: number } {
  const rawData = (graphDiv as unknown as { data?: unknown }).data
  if (!Array.isArray(rawData)) {
    return { indexes: [], widths: [], uniformWidth: 1.5 }
  }

  const indexes: number[] = []
  const widths: number[] = []

  rawData.forEach((trace, index) => {
    if (typeof trace !== 'object' || trace === null) {
      return
    }

    const traceAny = trace as LooseSpectrumTrace
    const isScatter = traceAny.type === 'scatter'
    const mode = typeof traceAny.mode === 'string' ? traceAny.mode : ''
    const isLineMode = mode.includes('lines')
    const meta =
      typeof traceAny.meta === 'object' && traceAny.meta !== null
        ? (traceAny.meta as { isSpectrum?: unknown })
        : null
    const isSpectrumTrace = meta?.isSpectrum === true

    if (!isScatter || !isLineMode || !isSpectrumTrace) {
      return
    }

    indexes.push(index)
    widths.push(
      typeof traceAny.line?.width === 'number' ? traceAny.line.width : 1.5,
    )
  })

  if (indexes.length === 0) {
    return { indexes: [], widths: [], uniformWidth: 1.5 }
  }

  return {
    indexes,
    widths,
    uniformWidth: Math.min(...widths),
  }
}

async function withUniformExportLineWidths(
  graphDiv: PlotlyHTMLElement,
  runExport: () => Promise<void>,
) {
  const traceInfo = getPrimarySpectrumTraceWidths(graphDiv)
  if (traceInfo.indexes.length === 0) {
    await runExport()
    return
  }

  await Plotly.restyle(
    graphDiv,
    { 'line.width': traceInfo.uniformWidth } as unknown as Data,
    traceInfo.indexes,
  )

  try {
    await runExport()
  } finally {
    await Plotly.restyle(
      graphDiv,
      { 'line.width': traceInfo.widths } as unknown as Data,
      traceInfo.indexes,
    )
  }
}

export function ExportPanel({ plotDivRef }: ExportPanelProps) {
  const { spectra, activeSpectrumId, plot, graphics, export: exportSettings } =
    useAppState()
  const dispatch = useAppDispatch()
  const [transparentBackground, setTransparentBackground] = useState(false)
  const [decimalComma, setDecimalComma] = useState(true)
  const [isExporting, setIsExporting] = useState(false)
  const roundedExportW = Math.round(graphics.exportWidth)
  const roundedExportH = Math.round(graphics.exportHeight)
  const exportW = clampInt(roundedExportW, 300, 8000)
  const exportH = clampInt(roundedExportH, 300, 8000)
  const isExportSizeClamped =
    exportW !== roundedExportW || exportH !== roundedExportH

  const activeSpectrum = useMemo(
    () =>
      activeSpectrumId !== undefined
        ? spectra.find((spectrum) => spectrum.id === activeSpectrumId) ??
          spectra[0]
        : spectra[0],
    [activeSpectrumId, spectra],
  )
  const defaultImageBase = plot.showAllSpectra
    ? 'overlay'
    : activeSpectrum !== undefined
      ? activeSpectrum.name
      : 'plot'
  const defaultDataBase =
    activeSpectrum !== undefined ? `${activeSpectrum.name}_data` : 'spectrum_data'
  const defaultZipBase = plot.showAllSpectra ? 'overlay_all' : 'all_spectra'

  const isPlotReady = plotDivRef.current !== null
  const hasSpectra = spectra.length > 0
  const exportDisabled = !isPlotReady || isExporting
  const exportDataDisabled = !hasSpectra
  const tauriEnabled = isTauriRuntime()

  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }

    try {
      window.localStorage.setItem(
        EXPORT_FOLDER_STORAGE_KEY,
        exportSettings.folder,
      )
    } catch {
      // Ignore persistence failures in restricted browser modes.
    }
  }, [exportSettings.folder])

  const exportData = async (delimiter: ';' | '\t') => {
    if (!activeSpectrum) {
      return
    }

    const serialized = spectrumToDelimitedText({
      spectrum: activeSpectrum,
      delimiter,
      decimalComma,
    })
    const extension = delimiter === ';' ? 'csv' : 'tsv'
    const mime =
      delimiter === ';'
        ? 'text/csv;charset=utf-8'
        : 'text/tab-separated-values;charset=utf-8'
    const fileName = getExportFilename(
      exportSettings.filename,
      extension,
      defaultDataBase,
    )

    await saveTextOutput({
      fileName,
      text: serialized,
      mime,
      exportFolder: exportSettings.folder,
    })
  }

  const exportAllData = async (delimiter: ';' | '\t') => {
    if (!hasSpectra) {
      return
    }

    await exportAllToZip({
      spectra,
      delimiter,
      decimalComma,
      zipFileName: getExportFilename(
        exportSettings.filename,
        'zip',
        defaultZipBase,
      ),
      exportFolder: exportSettings.folder,
    })
  }

  const exportPlot = async (format: ExportFormat) => {
    const graphDiv = plotDivRef.current

    if (!graphDiv) {
      return
    }

    setIsExporting(true)

    const graphState = graphDiv as GraphDivState
    const fullLayoutAny = graphState._fullLayout ?? graphState.layout ?? {}
    const prevPaper = asString(fullLayoutAny.paper_bgcolor, '#ffffff')
    const prevPlot = asString(fullLayoutAny.plot_bgcolor, '#ffffff')
    const currentAnnotations =
      Array.isArray(fullLayoutAny.annotations)
        ? fullLayoutAny.annotations
            .filter(
              (annotation): annotation is LooseAnnotation =>
                typeof annotation === 'object' && annotation !== null,
            )
            .map((annotation) => ({ ...annotation }))
        : null
    const rawData = (graphDiv as unknown as { data?: unknown }).data
    const currentTraceWidths: number[] = Array.isArray(rawData)
      ? rawData.map((trace) => {
          const lineValue =
            typeof trace === 'object' && trace !== null && 'line' in trace
              ? (trace as { line?: { width?: unknown } }).line
              : undefined

          return typeof lineValue?.width === 'number' ? lineValue.width : 2
        })
      : []
    const restoreTracePatch = {
      'line.width': currentTraceWidths,
    } as unknown as Data
    const restoreLayoutPatch: Record<string, unknown> = {
      paper_bgcolor: prevPaper,
      plot_bgcolor: prevPlot,
    }

    try {
      const exportPaperBg = transparentBackground
        ? 'rgba(0,0,0,0)'
        : '#ffffff'

      if (transparentBackground) {
        await Plotly.relayout(graphDiv, {
          paper_bgcolor: 'rgba(0,0,0,0)',
          plot_bgcolor: 'rgba(0,0,0,0)',
        })
      } else {
        await Plotly.relayout(graphDiv, {
          paper_bgcolor: '#ffffff',
          plot_bgcolor: '#ffffff',
        })
      }

      if (currentAnnotations && currentAnnotations.length > 0) {
        const effectivePaperBg = asString(
          (graphDiv as GraphDivState)._fullLayout?.paper_bgcolor,
          exportPaperBg,
        )
        const inlineLabelBg = getInlineLabelBgColor(effectivePaperBg)
        const exportAnnotations = currentAnnotations.map((annotation) => {
          if (annotation.showarrow === false) {
            return {
              ...annotation,
              bgcolor: inlineLabelBg,
              bordercolor: inlineLabelBg,
              borderwidth: 0,
            }
          }

          return { ...annotation }
        })

        await Plotly.relayout(graphDiv, {
          annotations: exportAnnotations,
        } as unknown as Partial<Layout>)
      }

      await Plotly.redraw(graphDiv)

      await withUniformExportLineWidths(graphDiv, async () => {
        const exportFileName = getExportFilename(
          exportSettings.filename,
          format,
          defaultImageBase,
        )

        // Export pipeline: snapshot SVG first, patch tick styles in SVG, then output SVG/PNG.
        const rawSvgDataUrl = await Plotly.toImage(graphDiv, {
          format: 'svg',
          width: exportW,
          height: exportH,
          scale: 1,
        })
        const rawSvgText = decodePlotlySvgDataUrl(rawSvgDataUrl)
        const patchedSvgText = patchTickStyles(rawSvgText, {
          tickLabelBold: graphics.tickLabelBold,
          tickLabelItalic: graphics.tickLabelItalic,
        })

        if (format === 'svg') {
          await downloadSvg(
            patchedSvgText,
            exportFileName,
            exportSettings.folder,
          )
        } else {
          await downloadPngFromSvg({
            svgText: patchedSvgText,
            filename: exportFileName,
            width: exportW,
            height: exportH,
            scale: 2,
            transparentBackground,
            exportFolder: exportSettings.folder,
          })
        }
      })
    } finally {
      try {
        if (currentTraceWidths.length > 0) {
          await Plotly.restyle(graphDiv, restoreTracePatch)
        }

        if (currentAnnotations) {
          await Plotly.relayout(graphDiv, {
            annotations: currentAnnotations,
          } as unknown as Partial<Layout>)
        }

        await Plotly.relayout(
          graphDiv,
          restoreLayoutPatch as unknown as Partial<Layout>,
        )
      } finally {
        setIsExporting(false)
      }
    }
  }

  return (
    <div className="space-y-2">
      <label className="block space-y-1">
        <span className="text-xs text-slate-700">Filename</span>
        <input
          type="text"
          className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700"
          placeholder="e.g., EC-SERS_2026-02-09"
          value={exportSettings.filename}
          onChange={(event) =>
            dispatch({
              type: 'EXPORT_SET',
              patch: { filename: event.currentTarget.value },
            })
          }
        />
      </label>

      <div className="space-y-1">
        <span className="text-xs text-slate-700">Export folder</span>
        <div className="flex gap-1">
          <input
            type="text"
            readOnly
            className="w-full rounded border border-slate-300 bg-slate-50 px-2 py-1 text-xs text-slate-700"
            value={exportSettings.folder}
            placeholder="Not set (downloads in browser)"
          />
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
            disabled={!tauriEnabled}
            onClick={() => {
              void (async () => {
                const selectedFolder = await chooseExportFolder(
                  exportSettings.folder,
                )
                if (!selectedFolder) {
                  return
                }

                dispatch({
                  type: 'EXPORT_SET',
                  patch: { folder: selectedFolder },
                })
              })()
            }}
          >
            Choose...
          </button>
        </div>
        {!tauriEnabled ? (
          <p className="text-[11px] text-slate-400">
            Folder saving is available in the Tauri app.
          </p>
        ) : null}
      </div>

      <label className="flex items-center gap-2 text-xs text-slate-700">
        <input
          type="checkbox"
          className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
          checked={transparentBackground}
          onChange={(event) =>
            setTransparentBackground(event.currentTarget.checked)
          }
        />
        <span>Transparent background</span>
      </label>

      <div className="flex flex-wrap gap-1">
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={exportDisabled}
          onClick={() => exportPlot('png')}
        >
          Export PNG
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={exportDisabled}
          onClick={() => exportPlot('svg')}
        >
          Export SVG
        </button>
      </div>
      <p className="text-[11px] text-slate-500">
        Export size: {exportW} x {exportH} px{' '}
        <span className="text-slate-400">(from Graphics)</span>
      </p>
      {isExportSizeClamped ? (
        <p className="text-[11px] text-slate-400">
          Clamped to 300..8000 for export.
        </p>
      ) : null}

      <div className="space-y-1 border-t border-slate-200 pt-2">
        <p className="text-xs text-slate-700">Data export</p>
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
            checked={decimalComma}
            onChange={(event) => setDecimalComma(event.currentTarget.checked)}
          />
          <span>Decimal comma (CZ)</span>
        </label>

        <div className="flex flex-wrap gap-1">
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={exportDataDisabled}
          onClick={() => {
            void exportData(';')
          }}
        >
          Export CSV (;)
        </button>
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
          disabled={exportDataDisabled}
          onClick={() => {
            void exportData('\t')
          }}
        >
          Export TSV
        </button>
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
            disabled={exportDataDisabled}
            onClick={() => {
              void exportAllData(';')
            }}
          >
            Export ALL -&gt; ZIP (CSV)
          </button>
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-default disabled:opacity-50"
            disabled={exportDataDisabled}
            onClick={() => {
              void exportAllData('\t')
            }}
          >
            Export ALL -&gt; ZIP (TSV)
          </button>
        </div>
      </div>

      {!isPlotReady ? (
        <p className="text-[11px] text-slate-400">Plot not ready yet.</p>
      ) : null}
    </div>
  )
}
