import { useEffect, useMemo, useRef, useState } from 'react'
import { useAppState } from '../../app/state/AppStore'

type PeakRow = {
  id: string
  x: number
  y: number | null
  source: 'auto' | 'manual'
}

type PeakGroup = {
  spectrumId: string
  spectrumName: string
  rows: PeakRow[]
}

type ExportFormat = 'tsv' | 'csv'
const PEAKS_PANEL_COLLAPSED_KEY = 'speclab_peaksPanelCollapsed'

function sanitizeFileBase(rawValue: string): string {
  const withoutControlChars = Array.from(rawValue, (character) =>
    character.charCodeAt(0) < 32 ? ' ' : character,
  ).join('')
  const normalized = withoutControlChars
    .replace(/[\\/:*?"<>|]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/[. ]+$/g, '')

  const withoutExtension = normalized.replace(/\.(csv|tsv)$/i, '')
  return withoutExtension || 'peaks'
}

function encodeDelimitedField(value: string, delimiter: string): string {
  if (
    value.includes(delimiter) ||
    value.includes('\n') ||
    value.includes('\r') ||
    value.includes('"')
  ) {
    return `"${value.replace(/"/g, '""')}"`
  }

  return value
}

function interpolateYAtX(
  xValues: number[],
  yValues: number[],
  xTarget: number,
): number | null {
  if (xValues.length === 0 || yValues.length === 0 || xValues.length !== yValues.length) {
    return null
  }

  if (!Number.isFinite(xTarget)) {
    return null
  }

  const pointCount = xValues.length
  if (pointCount === 1) {
    return xValues[0] === xTarget && Number.isFinite(yValues[0]) ? yValues[0] : null
  }

  const firstX = xValues[0]
  const lastX = xValues[pointCount - 1]
  const isAscending = lastX >= firstX
  const minX = isAscending ? firstX : lastX
  const maxX = isAscending ? lastX : firstX
  if (xTarget < minX || xTarget > maxX) {
    return null
  }

  let low = 0
  let high = pointCount - 1
  while (low <= high) {
    const mid = Math.floor((low + high) / 2)
    const xMid = xValues[mid]
    if (!Number.isFinite(xMid)) {
      return null
    }

    if (xMid === xTarget) {
      const yMatch = yValues[mid]
      return Number.isFinite(yMatch) ? yMatch : null
    }

    if (isAscending) {
      if (xMid < xTarget) {
        low = mid + 1
      } else {
        high = mid - 1
      }
    } else if (xMid > xTarget) {
      low = mid + 1
    } else {
      high = mid - 1
    }
  }

  const leftIndex = high
  const rightIndex = low
  if (leftIndex < 0 || rightIndex >= pointCount) {
    return null
  }

  const x0 = xValues[leftIndex]
  const x1 = xValues[rightIndex]
  const y0 = yValues[leftIndex]
  const y1 = yValues[rightIndex]
  if (
    !Number.isFinite(x0) ||
    !Number.isFinite(x1) ||
    !Number.isFinite(y0) ||
    !Number.isFinite(y1) ||
    x1 === x0
  ) {
    return null
  }

  const ratio = (xTarget - x0) / (x1 - x0)
  const yInterpolated = y0 + ratio * (y1 - y0)
  return Number.isFinite(yInterpolated) ? yInterpolated : null
}

function formatY(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return ''
  }

  const trimmed = value.toFixed(6).replace(/\.?0+$/g, '')
  return trimmed === '-0' ? '0' : trimmed
}

export function PeaksListPanel() {
  const {
    spectra,
    activeSpectrumId,
    peaks,
    peaksAutoById,
    peaksManualById,
    cosmicCleanYById,
    smoothedYById,
    processedYById,
    export: exportSettings,
  } = useAppState()
  const [copyStatus, setCopyStatus] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === 'undefined') {
      return false
    }

    try {
      const storedValue = window.localStorage.getItem(PEAKS_PANEL_COLLAPSED_KEY)
      return storedValue === '1'
    } catch {
      return false
    }
  })
  const copyStatusTimerRef = useRef<number | null>(null)

  const activeSpectrum =
    activeSpectrumId !== undefined
      ? spectra.find((spectrum) => spectrum.id === activeSpectrumId) ?? spectra[0]
      : spectra[0]

  const decimals = Math.max(0, Math.round(peaks.decimals))
  const groups = useMemo<PeakGroup[]>(() => {
    if (!peaks.enabled) {
      return []
    }

    const targetSpectra =
      peaks.mode === 'active'
        ? activeSpectrum
          ? [activeSpectrum]
          : []
        : spectra

    return targetSpectra
      .map((spectrum) => {
        const ySource =
          cosmicCleanYById[spectrum.id] ??
          smoothedYById[spectrum.id] ??
          processedYById[spectrum.id] ??
          spectrum.y
        const autoRows: PeakRow[] = (peaksAutoById[spectrum.id] ?? [])
          .filter((peak) => Number.isFinite(peak.x))
          .map((peak) => ({
            id: peak.id,
            x: peak.x,
            y: interpolateYAtX(spectrum.x, ySource, peak.x),
            source: 'auto',
          }))
        const manualRows: PeakRow[] = (peaksManualById[spectrum.id] ?? [])
          .filter((peak) => Number.isFinite(peak.x))
          .map((peak) => ({
            id: peak.id,
            x: peak.x,
            y: interpolateYAtX(spectrum.x, ySource, peak.x),
            source: 'manual',
          }))
        const rows = [...autoRows, ...manualRows].sort((a, b) => a.x - b.x)

        if (rows.length === 0) {
          return null
        }

        return {
          spectrumId: spectrum.id,
          spectrumName: spectrum.name,
          rows,
        }
      })
      .filter((group): group is PeakGroup => group !== null)
  }, [
    activeSpectrum,
    cosmicCleanYById,
    peaks.enabled,
    peaks.mode,
    peaksAutoById,
    peaksManualById,
    processedYById,
    smoothedYById,
    spectra,
  ])
  const modeSuffix = peaks.mode === 'active' ? 'peaks-active' : 'peaks-all'
  const fileBase = sanitizeFileBase(exportSettings.filename.trim() || 'peaks')
  const spectraCount = groups.length
  const peakCount = groups.reduce((total, group) => total + group.rows.length, 0)

  const buildDelimitedText = (format: ExportFormat): string => {
    const delimiter = format === 'tsv' ? '\t' : ','
    const header = `spectrum${delimiter}x${delimiter}y${delimiter}source`
    const rows = groups.flatMap((group) =>
      group.rows.map((row) =>
        [
          encodeDelimitedField(group.spectrumName, delimiter),
          encodeDelimitedField(row.x.toFixed(decimals), delimiter),
          encodeDelimitedField(formatY(row.y), delimiter),
          row.source === 'auto' ? 'A' : 'M',
        ].join(delimiter),
      ),
    )

    return [header, ...rows].join('\n')
  }

  const clearCopyStatusTimer = () => {
    if (copyStatusTimerRef.current !== null) {
      window.clearTimeout(copyStatusTimerRef.current)
      copyStatusTimerRef.current = null
    }
  }

  const setTransientCopyStatus = (message: string) => {
    clearCopyStatusTimer()
    setCopyStatus(message)
    copyStatusTimerRef.current = window.setTimeout(() => {
      setCopyStatus(null)
      copyStatusTimerRef.current = null
    }, 1800)
  }

  const copyText = async (format: ExportFormat) => {
    const text = buildDelimitedText(format)
    try {
      await navigator.clipboard.writeText(text)
      setTransientCopyStatus(`Copied ${format.toUpperCase()}.`)
    } catch {
      setTransientCopyStatus('Copy failed.')
    }
  }

  const downloadText = (format: ExportFormat) => {
    const text = buildDelimitedText(format)
    const extension = format === 'tsv' ? 'tsv' : 'csv'
    const mime =
      format === 'tsv'
        ? 'text/tab-separated-values;charset=utf-8'
        : 'text/csv;charset=utf-8'
    const blob = new Blob([text], { type: mime })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${fileBase}-${modeSuffix}.${extension}`
    document.body.appendChild(anchor)
    anchor.click()
    document.body.removeChild(anchor)
    URL.revokeObjectURL(url)
  }

  useEffect(
    () => () => {
      clearCopyStatusTimer()
    },
    [],
  )

  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }

    try {
      window.localStorage.setItem(
        PEAKS_PANEL_COLLAPSED_KEY,
        collapsed ? '1' : '0',
      )
    } catch {
      // Ignore persistence errors.
    }
  }, [collapsed])

  if (groups.length === 0) {
    return null
  }

  return (
    <section className="mt-4 rounded-lg border border-slate-200 bg-slate-50/70 p-3 dark:border-slate-800 dark:bg-slate-950/40">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <button
            type="button"
            className="rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            aria-label={collapsed ? 'Expand peaks panel' : 'Collapse peaks panel'}
            aria-expanded={!collapsed}
            onClick={() => setCollapsed((prev) => !prev)}
          >
            <span
              className={`inline-block transition-transform ${
                collapsed ? '-rotate-90' : 'rotate-0'
              }`}
            >
              ▾
            </span>
          </button>
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Peaks</h3>
          <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            {spectraCount} spectra • {peakCount} peaks
          </span>
        </div>
        <div className="flex flex-wrap gap-1">
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
            onClick={() => {
              void copyText('tsv')
            }}
          >
            Copy TSV
          </button>
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
            onClick={() => {
              void copyText('csv')
            }}
          >
            Copy CSV
          </button>
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
            onClick={() => downloadText('tsv')}
          >
            Download TSV
          </button>
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
            onClick={() => downloadText('csv')}
          >
            Download CSV
          </button>
        </div>
      </div>
      {copyStatus ? (
        <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
          {copyStatus}
        </p>
      ) : null}
      {!collapsed ? (
        <div className="mt-2 max-h-80 space-y-2 overflow-auto pr-1">
          {groups.map((group) => (
            <div
              key={group.spectrumId}
              className="rounded border border-slate-200 bg-white/90 p-2 dark:border-slate-700 dark:bg-slate-900/70"
            >
              <div className="flex items-center justify-between gap-2">
                <p className="truncate text-xs font-medium text-slate-800 dark:text-slate-100">
                  {group.spectrumName}
                </p>
                <span className="text-[11px] text-slate-500 dark:text-slate-400">
                  {group.rows.length}
                </span>
              </div>
              <div className="mt-1 rounded border border-slate-200 dark:border-slate-700">
                <table className="w-full border-collapse text-xs">
                  <thead className="bg-slate-100 dark:bg-slate-800">
                    <tr>
                      <th className="px-2 py-1 text-left font-medium text-slate-600 dark:text-slate-300">
                        X
                      </th>
                      <th className="px-2 py-1 text-left font-medium text-slate-600 dark:text-slate-300">
                        Y
                      </th>
                      <th className="w-14 px-2 py-1 text-left font-medium text-slate-600 dark:text-slate-300">
                        Source
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.rows.map((row) => (
                      <tr
                        key={row.id}
                        className="border-t border-slate-100 dark:border-slate-800"
                      >
                        <td className="px-2 py-1 text-slate-700 dark:text-slate-200">
                          {row.x.toFixed(decimals)}
                        </td>
                        <td className="px-2 py-1 text-slate-700 dark:text-slate-200">
                          {formatY(row.y)}
                        </td>
                        <td className="px-2 py-1 text-slate-500 dark:text-slate-400">
                          {row.source === 'auto' ? 'A' : 'M'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  )
}
