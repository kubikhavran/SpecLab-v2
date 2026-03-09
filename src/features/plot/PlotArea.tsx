import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
} from 'react'
import createPlotlyComponent from 'react-plotly.js/factory'
import Plotly from 'plotly.js-dist-min'
import type {
  Config,
  Data,
  Layout,
  PlotlyHTMLElement,
  PlotMouseEvent,
} from 'plotly.js'
import { useAppDispatch, useAppState } from '../../app/state/AppStore'
import type { Peak, Spectrum } from '../../app/types/core'
import { formatAxisLabel } from '../../lib/formatAxisLabel'
import { getPaletteColors } from '../graphics/palettes'
import { PeaksListPanel } from '../peaks/PeaksListPanel'
import { applyTickTextInlineStyles } from './tickTextStyles'

type PlotSeries = {
  id: string
  name: string
  x: number[]
  y: number[]
  isActive: boolean
}

const Plot = createPlotlyComponent(Plotly)

const fallbackX: number[] = [100, 120, 140, 160, 180, 200, 220, 240]
const fallbackY: number[] = [12, 18, 15, 24, 21, 27, 23, 30]
const DEFAULT_COLORWAY = [
  '#1f77b4',
  '#ff7f0e',
  '#2ca02c',
  '#d62728',
  '#9467bd',
  '#8c564b',
  '#e377c2',
  '#7f7f7f',
  '#bcbd22',
  '#17becf',
]

type PlotAreaProps = {
  plotDivRef: MutableRefObject<PlotlyHTMLElement | null>
}

type SpectrumTraceMeta = {
  spectrumId: string
  isSpectrum: true
}

type PeakAnnotationBinding = {
  spectrumId: string
  peakId: string
  source: 'auto' | 'manual'
  x?: number
}

type PeakLabelOffsetDraft = {
  ax?: number
  ay?: number
}

type PlotlyAnnotationClickPayload = {
  index?: unknown
  annotation?: {
    index?: unknown
    _index?: unknown
    x?: unknown
    customdata?: unknown
  } | null
  event?: {
    shiftKey?: unknown
    button?: unknown
  } | null
}

type PlotlyAnnotationEmitter = PlotlyHTMLElement & {
  on?: (eventName: string, handler: (payload: unknown) => void) => void
  off?: (eventName: string, handler: (payload: unknown) => void) => void
  removeListener?: (
    eventName: string,
    handler: (payload: unknown) => void,
  ) => void
}

function clampInt(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n))
}

function computeLayoutMargins(
  shouldPreviewCanvasSize: boolean,
  useInlineLabels: boolean,
  options: {
    baseFontSize: number
    tickFontSize: number
    showXTickLabels: boolean
    showYTickLabels: boolean
    axisLabelBold: boolean
    axisLabelItalic: boolean
  },
): { l: number; r: number; t: number; b: number } {
  const baseMargins = {
    l: 72,
    r: useInlineLabels ? 160 : 24,
    t: 24,
    b: 64,
  }

  if (!shouldPreviewCanvasSize) {
    return baseMargins
  }

  const labelStyleFactor =
    options.axisLabelBold || options.axisLabelItalic ? 1.1 : 1
  const xTickExtra = options.showXTickLabels
    ? Math.round(options.tickFontSize * 1.4)
    : 0
  const yTickExtra = options.showYTickLabels
    ? Math.round(options.tickFontSize * 1.8)
    : 0

  return {
    l: Math.max(
      baseMargins.l,
      Math.round(options.baseFontSize * 2.2 * labelStyleFactor + yTickExtra),
    ),
    r: baseMargins.r,
    t: Math.max(baseMargins.t, Math.round(options.baseFontSize * 0.8)),
    b: Math.max(
      baseMargins.b,
      Math.round(options.baseFontSize * 3.0 * labelStyleFactor + xTickExtra),
    ),
  }
}

function getRange(values: number[]): { min: number; max: number } {
  if (values.length === 0) {
    return { min: Number.NaN, max: Number.NaN }
  }

  return {
    min: Math.min(...values),
    max: Math.max(...values),
  }
}

function formatRangeValue(value: number): string {
  return Number.isFinite(value) ? value.toString() : 'n/a'
}

function truncateLabel(text: string, maxLength: number): string {
  if (text.length <= maxLength) {
    return text
  }

  return `${text.slice(0, Math.max(0, maxLength - 3))}...`
}

function escapeHtml(str: string): string {
  return str.replace(/[&<>"']/g, (char) => {
    switch (char) {
      case '&':
        return '&amp;'
      case '<':
        return '&lt;'
      case '>':
        return '&gt;'
      case '"':
        return '&quot;'
      case '\'':
        return '&#39;'
      default:
        return char
    }
  })
}

function styleText(
  str: string | undefined,
  bold: boolean,
  italic: boolean,
): string {
  const safe = escapeHtml(str ?? '')
  if (!safe) {
    return safe
  }

  if (bold && italic) {
    return `<b><i>${safe}</i></b>`
  }

  if (bold) {
    return `<b>${safe}</b>`
  }

  if (italic) {
    return `<i>${safe}</i>`
  }

  return safe
}

function styleFormattedText(
  formattedHtml: string,
  bold: boolean,
  italic: boolean,
): string {
  if (!formattedHtml) {
    return formattedHtml
  }

  if (bold && italic) {
    return `<b><i>${formattedHtml}</i></b>`
  }

  if (bold) {
    return `<b>${formattedHtml}</b>`
  }

  if (italic) {
    return `<i>${formattedHtml}</i>`
  }

  return formattedHtml
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

function getCanvasColor(mode: 'auto' | 'white' | 'dark'): string {
  if (mode === 'white') {
    return '#ffffff'
  }

  if (mode === 'dark') {
    return '#0b1220'
  }

  return 'rgba(0, 0, 0, 0)'
}

function getCanvasFrameClass(mode: 'auto' | 'white' | 'dark'): string {
  if (mode === 'white') {
    return 'bg-white dark:bg-white'
  }

  if (mode === 'dark') {
    return 'bg-slate-950/60 dark:bg-slate-950/60'
  }

  return 'bg-slate-50/70 dark:bg-slate-950/40'
}

function toSeries(
  spectrum: Spectrum,
  yValues: number[],
  activeId: string | undefined,
  yOffset: number,
): PlotSeries {
  const pointCount = Math.min(spectrum.x.length, yValues.length)

  return {
    id: spectrum.id,
    name: spectrum.name,
    x: spectrum.x.slice(0, pointCount),
    y: yValues.slice(0, pointCount).map((value) => value + yOffset),
    isActive: activeId !== undefined && spectrum.id === activeId,
  }
}

function resolvePeakIndex(xValues: number[], peak: Peak): number | null {
  if (xValues.length === 0) {
    return null
  }

  const candidateIndex = peak.i
  if (
    typeof candidateIndex === 'number' &&
    Number.isInteger(candidateIndex) &&
    candidateIndex >= 0 &&
    candidateIndex < xValues.length
  ) {
    return candidateIndex
  }

  let bestIndex = 0
  let bestDistance = Math.abs(xValues[0] - peak.x)
  for (let i = 1; i < xValues.length; i += 1) {
    const distance = Math.abs(xValues[i] - peak.x)
    if (distance < bestDistance) {
      bestDistance = distance
      bestIndex = i
    }
  }

  return bestIndex
}

function interpolateYAtX(
  xValues: number[],
  yValues: number[],
  xTarget: number,
): number | null {
  const pointCount = Math.min(xValues.length, yValues.length)
  if (pointCount === 0) {
    return null
  }

  if (pointCount === 1) {
    return yValues[0]
  }

  const firstX = xValues[0]
  const lastX = xValues[pointCount - 1]
  const isAscending = lastX >= firstX

  if (isAscending) {
    if (xTarget <= firstX) {
      return yValues[0]
    }
    if (xTarget >= lastX) {
      return yValues[pointCount - 1]
    }
  } else {
    if (xTarget >= firstX) {
      return yValues[0]
    }
    if (xTarget <= lastX) {
      return yValues[pointCount - 1]
    }
  }

  let low = 0
  let high = pointCount - 1
  while (high - low > 1) {
    const mid = Math.floor((low + high) / 2)
    const xMid = xValues[mid]
    if ((isAscending && xMid <= xTarget) || (!isAscending && xMid >= xTarget)) {
      low = mid
    } else {
      high = mid
    }
  }

  const x0 = xValues[low]
  const x1 = xValues[high]
  const y0 = yValues[low]
  const y1 = yValues[high]

  if (!Number.isFinite(x0) || !Number.isFinite(x1) || x1 === x0) {
    return y0
  }

  const t = (xTarget - x0) / (x1 - x0)
  return y0 + t * (y1 - y0)
}

function parseRegionBound(value: string): number | null {
  const parsed = Number(value.trim())
  return Number.isFinite(parsed) ? parsed : null
}

function parseAnnotationOffsetUpdates(
  relayout: Readonly<Record<string, unknown>>,
): Map<number, PeakLabelOffsetDraft> {
  const updatesByIndex = new Map<number, PeakLabelOffsetDraft>()
  const upsert = (index: number, axis: 'ax' | 'ay', value: unknown) => {
    const numericValue = Number(value)
    if (!Number.isFinite(numericValue)) {
      return
    }

    const existing = updatesByIndex.get(index) ?? {}
    existing[axis] = numericValue
    updatesByIndex.set(index, existing)
  }

  for (const [key, value] of Object.entries(relayout)) {
    const match = key.match(/^annotations\[(\d+)\]\.(ax|ay)$/)
    if (match) {
      upsert(Number(match[1]), match[2] as 'ax' | 'ay', value)
      continue
    }

    const fullAnnotationMatch = key.match(/^annotations\[(\d+)\]$/)
    if (
      fullAnnotationMatch &&
      typeof value === 'object' &&
      value !== null &&
      ('ax' in value || 'ay' in value)
    ) {
      const index = Number(fullAnnotationMatch[1])
      const annotationPatch = value as { ax?: unknown; ay?: unknown }
      if (annotationPatch.ax !== undefined) {
        upsert(index, 'ax', annotationPatch.ax)
      }
      if (annotationPatch.ay !== undefined) {
        upsert(index, 'ay', annotationPatch.ay)
      }
    }
  }

  return updatesByIndex
}

function parseAnnotationTextClears(
  relayout: Readonly<Record<string, unknown>>,
): Set<number> {
  const clearedIndexes = new Set<number>()

  for (const [key, value] of Object.entries(relayout)) {
    const textMatch = key.match(/^annotations\[(\d+)\]\.text$/)
    if (textMatch) {
      if (value === '' || value === null) {
        clearedIndexes.add(Number(textMatch[1]))
      }
      continue
    }

    const fullAnnotationMatch = key.match(/^annotations\[(\d+)\]$/)
    if (!fullAnnotationMatch) {
      continue
    }

    const index = Number(fullAnnotationMatch[1])
    if (value === null) {
      clearedIndexes.add(index)
      continue
    }

    if (
      typeof value === 'object' &&
      value !== null &&
      'text' in value &&
      ((value as { text?: unknown }).text === '' ||
        (value as { text?: unknown }).text === null)
    ) {
      clearedIndexes.add(index)
    }
  }

  return clearedIndexes
}

function isElement(value: unknown): value is Element {
  return typeof Element !== 'undefined' && value instanceof Element
}

function isAnnotationClickTarget(target: EventTarget | null | undefined): boolean {
  if (!isElement(target)) {
    return false
  }

  // Plotly annotation text/arrow groups are rendered under .annotation in SVG layers.
  return target.closest('.annotation') !== null
}

function isTypingElement(value: unknown): boolean {
  if (!isElement(value)) {
    return false
  }

  const tagName = value.tagName.toLowerCase()
  if (tagName === 'input' || tagName === 'textarea' || tagName === 'select') {
    return true
  }

  const asHtmlElement =
    typeof HTMLElement !== 'undefined' && value instanceof HTMLElement
      ? value
      : null

  return (
    Boolean(asHtmlElement?.isContentEditable) ||
    value.closest('[contenteditable="true"]') !== null
  )
}

function parseAnnotationIndexFromPayload(payload: PlotlyAnnotationClickPayload): number | null {
  const indexRaw =
    payload.index ?? payload.annotation?.index ?? payload.annotation?._index
  const index = Number(indexRaw)
  return Number.isInteger(index) ? index : null
}

function parseBindingFromCustomData(customData: unknown): PeakAnnotationBinding | null {
  if (typeof customData !== 'object' || customData === null) {
    return null
  }

  const value = customData as {
    spectrumId?: unknown
    peakId?: unknown
    source?: unknown
    x?: unknown
  }

  if (
    typeof value.spectrumId !== 'string' ||
    value.spectrumId.length === 0 ||
    typeof value.peakId !== 'string' ||
    value.peakId.length === 0 ||
    (value.source !== 'auto' && value.source !== 'manual')
  ) {
    return null
  }

  const x = Number(value.x)
  return {
    spectrumId: value.spectrumId,
    peakId: value.peakId,
    source: value.source,
    ...(Number.isFinite(x) ? { x } : {}),
  }
}

function detachPlotlyAnnotationListener(
  graphDiv: PlotlyAnnotationEmitter | null,
  handler: (payload: unknown) => void,
) {
  if (!graphDiv) {
    return
  }

  if (typeof graphDiv.off === 'function') {
    graphDiv.off('plotly_clickannotation', handler)
    return
  }

  if (typeof graphDiv.removeListener === 'function') {
    graphDiv.removeListener('plotly_clickannotation', handler)
  }
}

export function PlotArea({ plotDivRef }: PlotAreaProps) {
  const {
    spectra,
    activeSpectrumId,
    plot,
    graphics,
    peaks,
    peaksAutoById,
    peaksManualById,
    peakLabelOffsetsById,
    baseline,
    cosmicCleanYById,
    manualCleanYById,
    processedYById,
    baselineYById,
    smoothedYById,
  } = useAppState()
  const dispatch = useAppDispatch()
  const annotationIndexMapRef = useRef<Record<number, PeakAnnotationBinding>>({})
  const [selectedPeak, setSelectedPeak] = useState<PeakAnnotationBinding | null>(
    null,
  )
  const selectedPeakRef = useRef<PeakAnnotationBinding | null>(null)
  const boundAnnotationGraphDivRef = useRef<PlotlyAnnotationEmitter | null>(null)
  const onPlotlyClickAnnotationRef = useRef<(payload: unknown) => void>(() => {})
  const onPlotlyClickAnnotationBridgeRef = useRef<
    ((payload: unknown) => void) | null
  >(null)
  const shiftDownRef = useRef(false)
  const spectrumIds = new Set(spectra.map((spectrum) => spectrum.id))

  const resolvedActiveSpectrum =
    spectra.find((spectrum) => spectrum.id === activeSpectrumId) ?? spectra[0]
  const resolvedActiveId = resolvedActiveSpectrum?.id
  const overlayMode = spectra.length > 0 && plot.showAllSpectra
  const overlaySpectra = plot.reverseOverlayOrder
    ? [...spectra].slice().reverse()
    : spectra
  const useInlineLabels = overlayMode && graphics.inlineSpectrumLabels

  const plottedSpectra: Spectrum[] =
    spectra.length === 0
      ? []
      : overlayMode
        ? overlaySpectra
        : [resolvedActiveSpectrum]
  const xAxisLabelStyled = styleFormattedText(
    formatAxisLabel(graphics.xLabel.trim() || 'X'),
    graphics.axisLabelBold,
    graphics.axisLabelItalic,
  )
  const yAxisLabelStyled = styleFormattedText(
    formatAxisLabel(graphics.yLabel.trim() || 'Y'),
    graphics.axisLabelBold,
    graphics.axisLabelItalic,
  )
  const traceLineWidth = Math.max(1, graphics.traceLineWidth)
  const previewW = clampInt(Math.round(graphics.exportWidth), 300, 8000)
  const previewH = clampInt(Math.round(graphics.exportHeight), 300, 8000)
  const shouldPreviewCanvasSize = graphics.previewCanvasSize
  const uiRevision = plot.uiRevision ?? 1
  const editRevision = useMemo(() => {
    const serializePeaks = (records: Record<string, Peak[]>) =>
      Object.entries(records)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([spectrumId, spectrumPeaks]) =>
          `${spectrumId}:${spectrumPeaks.map((peak) => peak.id).join(',')}`,
        )
        .join('|')

    const serializeOffsets = (
      records: Record<string, Record<string, { ax: number; ay: number }>>,
    ) =>
      Object.entries(records)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([spectrumId, spectrumOffsets]) => {
          const serializedSpectrumOffsets = Object.entries(spectrumOffsets)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(
              ([peakId, offset]) =>
                `${peakId}:${Math.round(offset.ax * 1000) / 1000},${
                  Math.round(offset.ay * 1000) / 1000
                }`,
            )
            .join(';')
          return `${spectrumId}:${serializedSpectrumOffsets}`
        })
        .join('|')

    return `auto:${serializePeaks(peaksAutoById)}|manual:${serializePeaks(
      peaksManualById,
    )}|offsets:${serializeOffsets(peakLabelOffsetsById)}`
  }, [peakLabelOffsetsById, peaksAutoById, peaksManualById])
  const titleStandoff = shouldPreviewCanvasSize
    ? Math.max(12, Math.round(graphics.baseFontSize * 0.9))
    : Math.max(8, Math.round(graphics.baseFontSize * 0.8))
  const isBox = graphics.frameMode === 'box'
  const activeTraceLineWidth = Math.max(
    traceLineWidth + 1,
    traceLineWidth,
  )

  const series: PlotSeries[] =
    plottedSpectra.length > 0
      ? plottedSpectra.map((spectrum, index) => {
          const yRawOrCosmic = cosmicCleanYById[spectrum.id] ?? spectrum.y
          const yBase = processedYById[spectrum.id] ?? yRawOrCosmic
          const ySmoothed = smoothedYById[spectrum.id] ?? yBase
          const yToPlot = manualCleanYById[spectrum.id] ?? ySmoothed

          return toSeries(
            spectrum,
            yToPlot,
            resolvedActiveId,
            overlayMode ? index * plot.stackOffset : 0,
          )
        })
      : [
          {
            id: 'dummy',
            name: 'Dummy',
            x: fallbackX,
            y: fallbackY,
            isActive: false,
          },
        ]
  const allX = series.flatMap((entry) => entry.x)
  const allY = series.flatMap((entry) => entry.y)
  const xRange = getRange(allX)
  const yRange = getRange(allY)
  const hasXRange = plot.xMin != null && plot.xMax != null
  const primaryTraceCount = series.length
  const paletteColors = getPaletteColors(graphics.palette, primaryTraceCount)
  const getSpectrumColor = (spectrumId: string): string => {
    const seriesIndex = series.findIndex((entry) => entry.id === spectrumId)
    if (seriesIndex < 0) {
      return '#ef4444'
    }

    if (paletteColors !== null && paletteColors.length > 0) {
      return (
        paletteColors[seriesIndex] ??
        paletteColors[seriesIndex % paletteColors.length]
      )
    }

    return DEFAULT_COLORWAY[seriesIndex % DEFAULT_COLORWAY.length]
  }
  const peaksEnabled = peaks.enabled
  const peakSpectrumIds =
    !peaksEnabled
      ? []
      : peaks.mode === 'active'
        ? resolvedActiveId
          ? [resolvedActiveId]
          : []
        : plottedSpectra.map((spectrum) => spectrum.id)
  const hasAnyPeaksForTable = (() => {
    if (!peaks.enabled) {
      return false
    }

    const countForSpectrum = (spectrumId: string): number =>
      (peaksAutoById[spectrumId]?.length ?? 0) +
      (peaksManualById[spectrumId]?.length ?? 0)

    if (peaks.mode === 'active') {
      const targetSpectrumId = resolvedActiveId ?? spectra[0]?.id
      return targetSpectrumId ? countForSpectrum(targetSpectrumId) > 0 : false
    }

    return spectra.some((spectrum) => countForSpectrum(spectrum.id) > 0)
  })()
  const regionMinInput = parseRegionBound(peaks.regionXMin)
  const regionMaxInput = parseRegionBound(peaks.regionXMax)
  const hasRegionFilter =
    peaks.useRegion &&
    regionMinInput !== null &&
    regionMaxInput !== null
  const regionMin = hasRegionFilter
    ? Math.min(regionMinInput, regionMaxInput)
    : Number.NaN
  const regionMax = hasRegionFilter
    ? Math.max(regionMinInput, regionMaxInput)
    : Number.NaN
  const peakDecimals = Math.max(0, Math.round(peaks.decimals))
  const peakMarkerX: number[] = []
  const peakMarkerY: number[] = []
  const peakMarkerText: string[] = []
  const peakAnnotations: NonNullable<Layout['annotations']> = []
  const peakAnnotationBindings: PeakAnnotationBinding[] = []

  for (const spectrumId of peakSpectrumIds) {
    const spectrum = plottedSpectra.find((entry) => entry.id === spectrumId)
    if (!spectrum) {
      continue
    }

    const yRawOrCosmic = cosmicCleanYById[spectrum.id] ?? spectrum.y
    const yBaseline = processedYById[spectrum.id] ?? yRawOrCosmic
    const ySmoothed = smoothedYById[spectrum.id] ?? yBaseline
    const yDisplayed = manualCleanYById[spectrum.id] ?? ySmoothed
    const yProcessed = processedYById[spectrum.id]
    const offset =
      overlayMode
        ? plottedSpectra.findIndex((entry) => entry.id === spectrum.id) *
          plot.stackOffset
        : 0

    const pointCount = Math.min(spectrum.x.length, yDisplayed.length)
    if (pointCount <= 0) {
      continue
    }

    const xSource = spectrum.x.slice(0, pointCount)
    const yDisplayedSource = yDisplayed
      .slice(0, pointCount)
      .map((value) => value + offset)
    const yProcessedSource =
      Array.isArray(yProcessed) && yProcessed.length > 0
        ? yProcessed
            .slice(0, Math.min(spectrum.x.length, yProcessed.length))
            .map((value) => value + offset)
        : yDisplayedSource
    const ySource =
      peaks.source === 'processed'
        ? yProcessedSource
        : yDisplayedSource
    const spectrumColor = getSpectrumColor(spectrum.id)
    const sourceCount = Math.min(xSource.length, ySource.length)
    const xForSource = xSource.slice(0, sourceCount)
    const yForSource = ySource.slice(0, sourceCount)
    const peaksForId = [
      ...(peaksAutoById[spectrum.id] ?? []),
      ...(peaksManualById[spectrum.id] ?? []),
    ]

    for (const peak of peaksForId) {
      let xValue = Number.NaN
      let yValue = Number.NaN

      if (peak.source === 'manual') {
        xValue = peak.x
        const interpolatedY = interpolateYAtX(xForSource, yForSource, xValue)
        yValue = interpolatedY ?? Number.NaN
      } else {
        const peakIndex = resolvePeakIndex(xForSource, peak)
        if (peakIndex === null || peakIndex >= sourceCount) {
          continue
        }
        xValue = xForSource[peakIndex]
        yValue = yForSource[peakIndex]
      }

      if (!Number.isFinite(xValue) || !Number.isFinite(yValue)) {
        continue
      }

      if (hasRegionFilter && (xValue < regionMin || xValue > regionMax)) {
        continue
      }

      const label = xValue.toFixed(peakDecimals)
      const styledLabel = styleText(label, peaks.labelBold, peaks.labelItalic)
      const effectiveLabelColor =
        peaks.labelColorMode === 'trace'
          ? spectrumColor
          : peaks.labelColor || '#111827'
      const effectiveLeaderColor =
        peaks.leaderColorMode === 'trace'
          ? spectrumColor
          : peaks.leaderColor || '#111827'
      const effectiveLeaderLineColor = peaks.showLeaderLines
        ? effectiveLeaderColor
        : 'rgba(0,0,0,0)'
      const effectiveLeaderLineWidth = peaks.showLeaderLines
        ? Math.max(1, Math.min(6, peaks.leaderLineWidth))
        : 0.01

      if (peaks.showMarkers) {
        peakMarkerX.push(xValue)
        peakMarkerY.push(yValue)
        peakMarkerText.push(label)
      }

      if (peaks.showLabels) {
        const offset = peakLabelOffsetsById[spectrum.id]?.[peak.id] ?? {
          ax: 0,
          ay: -40,
        }

        const annotationWithBinding: Record<string, unknown> = {
          x: xValue,
          y: yValue,
          xref: 'x',
          yref: 'y',
          text: styledLabel,
          textangle: `${peaks.labelAngleDeg}`,
          showarrow: true,
          arrowhead: 0,
          arrowwidth: effectiveLeaderLineWidth,
          arrowcolor: effectiveLeaderLineColor,
          ax: offset.ax,
          ay: offset.ay,
          axref: 'pixel',
          ayref: 'pixel',
          captureevents: true,
          xanchor: 'center',
          yanchor: 'middle',
          font: {
            color: effectiveLabelColor,
            size: peaks.labelFontSize,
          },
          bgcolor: 'rgba(0,0,0,0)',
          bordercolor: 'rgba(0,0,0,0)',
          borderwidth: 0,
          customdata: {
            spectrumId: spectrum.id,
            peakId: peak.id,
            source: peak.source,
            x: xValue,
          },
        }
        peakAnnotations.push(
          annotationWithBinding as NonNullable<Layout['annotations']>[number],
        )
        peakAnnotationBindings.push({
          spectrumId: spectrum.id,
          peakId: peak.id,
          source: peak.source,
          x: xValue,
        })
      }
    }
  }

  const primaryTraces: Data[] = series.map((entry, index) => {
    const isSpectrumTrace = spectrumIds.has(entry.id)
    const paletteColor =
      paletteColors !== null
        ? (paletteColors[index] ??
          paletteColors[index % paletteColors.length])
        : undefined

    return {
      type: 'scatter',
      mode: 'lines',
      name: entry.name,
      ...(isSpectrumTrace
        ? {
            meta: {
              spectrumId: entry.id,
              isSpectrum: true,
            } satisfies SpectrumTraceMeta,
            legendgroup: entry.id,
          }
        : {}),
      x: entry.x,
      y: entry.y,
      line: {
        width: entry.isActive ? activeTraceLineWidth : traceLineWidth,
        ...(paletteColor !== undefined ? { color: paletteColor } : {}),
      },
      hovertemplate: `${entry.name}<br>x: %{x}<br>y: %{y}<extra></extra>`,
    }
  })
  const activeBaselineY =
    !overlayMode && resolvedActiveSpectrum
      ? baselineYById[resolvedActiveSpectrum.id]
      : undefined
  const baselineTrace: Data | null =
    !overlayMode &&
    baseline.showOverlay &&
    resolvedActiveSpectrum &&
    Array.isArray(activeBaselineY)
      ? {
          type: 'scatter',
          mode: 'lines',
          name: `${resolvedActiveSpectrum.name} baseline`,
          x: resolvedActiveSpectrum.x.slice(
            0,
            Math.min(resolvedActiveSpectrum.x.length, activeBaselineY.length),
          ),
          y: activeBaselineY.slice(
            0,
            Math.min(resolvedActiveSpectrum.x.length, activeBaselineY.length),
          ),
          line: {
            color: '#94a3b8',
            width: 1.5,
            dash: 'dash',
          },
          hovertemplate: `baseline<br>x: %{x}<br>y: %{y}<extra></extra>`,
        }
      : null
  const peakMarkerTrace: Data | null =
    peaksEnabled && peaks.showMarkers && peakMarkerX.length > 0
      ? {
          type: 'scatter',
          mode: 'markers',
          name: 'Peaks',
          x: peakMarkerX,
          y: peakMarkerY,
          text: peakMarkerText,
          showlegend: false,
          marker: {
            size: 7,
            color: '#ef4444',
            symbol: 'circle',
          },
          hovertemplate: 'Peak x: %{x}<br>y: %{y}<extra></extra>',
        }
      : null
  const traces: Data[] = [
    ...primaryTraces,
    ...(peakMarkerTrace !== null ? [peakMarkerTrace] : []),
    ...(baselineTrace !== null ? [baselineTrace] : []),
  ]
  const plotCanvasMode = graphics.plotCanvas ?? 'auto'
  const canvasColor = getCanvasColor(plotCanvasMode)
  const canvasFrameClass = getCanvasFrameClass(plotCanvasMode)
  const inlineLabelBgColor = getInlineLabelBgColor(canvasColor)
  const inlineAnnotations: NonNullable<Layout['annotations']> = useInlineLabels
    ? series
        .map((entry, index) => {
          const xs = entry.x
          const ys = entry.y
          const pointCount = Math.min(xs.length, ys.length)
          if (pointCount <= 0) {
            return null
          }

          const xTarget = hasXRange
            ? plot.invertX
              ? Number(plot.xMin)
              : Number(plot.xMax)
            : (() => {
                const xMin = Math.min(...xs)
                const xMax = Math.max(...xs)
                return plot.invertX ? xMin : xMax
              })()

          let bestI = 0
          let bestD = Math.abs(xs[0] - xTarget)
          for (let i = 1; i < pointCount; i += 1) {
            const distance = Math.abs(xs[i] - xTarget)
            if (distance < bestD) {
              bestD = distance
              bestI = i
            }
          }

          const labelColor =
            paletteColors !== null
              ? (paletteColors[index] ??
                paletteColors[index % paletteColors.length])
              : DEFAULT_COLORWAY[index % DEFAULT_COLORWAY.length]

          return {
            x: xs[bestI],
            y: ys[bestI],
            xref: 'x' as const,
            yref: 'y' as const,
            text: styleText(
              truncateLabel(entry.name, 24),
              graphics.spectrumLabelBold,
              graphics.spectrumLabelItalic,
            ),
            showarrow: false,
            xanchor: 'left' as const,
            yanchor: 'middle' as const,
            xshift: 10,
            bgcolor: inlineLabelBgColor,
            bordercolor: inlineLabelBgColor,
            borderwidth: 0,
            font: {
              color: labelColor,
              size: graphics.tickFontSize,
            },
          }
        })
        .filter((annotation): annotation is NonNullable<typeof annotation> => annotation !== null)
    : []
  const peakAnnotationsWithCaptureEvents: NonNullable<Layout['annotations']> =
    peakAnnotations.map((annotation) => ({
      ...annotation,
      // Keep annotation clicks reliable for plotly_clickannotation.
      captureevents: true,
    }))
  const mergedAnnotations: NonNullable<Layout['annotations']> = [
    ...inlineAnnotations,
    ...peakAnnotationsWithCaptureEvents,
  ]
  const hasYRange = plot.yMin != null && plot.yMax != null
  const showXMarks = graphics.showXTickLabels && graphics.showXTickMarks
  const showYMarks = graphics.showYTickLabels && graphics.showYTickMarks
  const layoutMargins = computeLayoutMargins(
    shouldPreviewCanvasSize,
    useInlineLabels,
    {
      baseFontSize: graphics.baseFontSize,
      tickFontSize: graphics.tickFontSize,
      showXTickLabels: graphics.showXTickLabels,
      showYTickLabels: graphics.showYTickLabels,
      axisLabelBold: graphics.axisLabelBold,
      axisLabelItalic: graphics.axisLabelItalic,
    },
  )
  const leaderLabelsActive =
    peaks.enabled && peaks.showLabels
  const tickClass = [
    'speclab-plot',
    graphics.tickLabelBold ? 'speclab-tick-bold' : '',
    graphics.tickLabelItalic ? 'speclab-tick-italic' : '',
  ]
    .filter(Boolean)
    .join(' ')

  const handlePlotClick = (event: Readonly<PlotMouseEvent>) => {
    const points = event.points
    if (!Array.isArray(points) || points.length === 0) {
      return
    }

    const clickedSpectrumId = points.reduce<string | null>((found, point) => {
      if (found) {
        return found
      }

      const curveNumber = Number(point.curveNumber)
      if (
        Number.isInteger(curveNumber) &&
        curveNumber >= 0 &&
        curveNumber < series.length
      ) {
        const fromSeries = series[curveNumber]?.id
        if (typeof fromSeries === 'string' && spectrumIds.has(fromSeries)) {
          return fromSeries
        }
      }

      const pointData = point.data as unknown as { meta?: unknown } | undefined
      const meta = pointData?.meta
      if (typeof meta !== 'object' || meta === null) {
        return null
      }

      const metaObj = meta as {
        isSpectrum?: unknown
        spectrumId?: unknown
      }

      if (
        metaObj.isSpectrum === true &&
        typeof metaObj.spectrumId === 'string'
      ) {
        return metaObj.spectrumId
      }

      return null
    }, null)

    if (!clickedSpectrumId || !spectrumIds.has(clickedSpectrumId)) {
      return
    }

    if (clickedSpectrumId !== activeSpectrumId) {
      dispatch({
        type: 'SPECTRUM_SET_ACTIVE',
        id: clickedSpectrumId,
      })
    }

    if (!peaks.enabled || !peaks.manualPickEnabled) {
      return
    }

    const mouseEvent = (event as unknown as { event?: MouseEvent }).event
    if (isAnnotationClickTarget(mouseEvent?.target ?? null)) {
      return
    }

    const graphDiv = plotDivRef.current as
      | (PlotlyHTMLElement & {
          _fullLayout?: {
            xaxis?: {
              _offset?: number
              _length?: number
              p2l?: (xPixel: number) => unknown
              l2d?: (xLinear: number) => unknown
            }
          }
        })
      | null

    let clickedX = Number.NaN
    const fullLayout = graphDiv?._fullLayout
    const xAxis = fullLayout?.xaxis
    if (graphDiv && xAxis && mouseEvent) {
      const rect = graphDiv.getBoundingClientRect()
      const xOffset = Number.isFinite(Number(xAxis._offset))
        ? Number(xAxis._offset)
        : 0
      const xLengthRaw = Number(xAxis._length)
      const hasLength = Number.isFinite(xLengthRaw) && xLengthRaw > 0
      const pxRaw = mouseEvent.clientX - rect.left - xOffset
      const px = hasLength
        ? Math.max(0, Math.min(xLengthRaw, pxRaw))
        : pxRaw

      if (typeof xAxis.p2l === 'function' && Number.isFinite(px)) {
        const xLinear = Number(xAxis.p2l(px))
        if (Number.isFinite(xLinear)) {
          const xDataRaw =
            typeof xAxis.l2d === 'function' ? xAxis.l2d(xLinear) : xLinear
          const xData = Number(xDataRaw)
          if (Number.isFinite(xData)) {
            clickedX = xData
          }
        }
      }
    }

    if (!Number.isFinite(clickedX)) {
      const fallbackX = Number(points[0]?.x)
      if (Number.isFinite(fallbackX)) {
        clickedX = fallbackX
      }
    }

    if (!Number.isFinite(clickedX)) {
      return
    }

    dispatch({
      type: 'PEAKS_MANUAL_ADD',
      spectrumId: clickedSpectrumId,
      x: clickedX,
    })
  }

  const deletePeakByBinding = useCallback(
    (binding: PeakAnnotationBinding) => {
      dispatch({
        type:
          binding.source === 'manual' ? 'PEAKS_MANUAL_DELETE' : 'PEAKS_AUTO_DELETE',
        spectrumId: binding.spectrumId,
        peakId: binding.peakId,
      })
    },
    [dispatch],
  )

  const resolveBindingByFallback = (xRaw: unknown): PeakAnnotationBinding | null => {
    const x = Number(xRaw)
    if (!Number.isFinite(x)) {
      return null
    }

    const fallbackSpectrumId = resolvedActiveId ?? spectra[0]?.id
    if (!fallbackSpectrumId) {
      return null
    }

    const allPeaks = [
      ...(peaksAutoById[fallbackSpectrumId] ?? []),
      ...(peaksManualById[fallbackSpectrumId] ?? []),
    ]
    if (allPeaks.length === 0) {
      return null
    }

    let bestPeak: Peak | null = null
    let bestDistance = Number.POSITIVE_INFINITY
    for (const peak of allPeaks) {
      const distance = Math.abs(peak.x - x)
      if (distance < bestDistance) {
        bestDistance = distance
        bestPeak = peak
      }
    }

    if (!bestPeak) {
      return null
    }

    return {
      spectrumId: fallbackSpectrumId,
      peakId: bestPeak.id,
      source: bestPeak.source,
      x: bestPeak.x,
    }
  }

  const resolveBindingFromAnnotationClick = (
    eventPayload: unknown,
  ): PeakAnnotationBinding | null => {
    if (typeof eventPayload !== 'object' || eventPayload === null) {
      return null
    }

    const payload = eventPayload as PlotlyAnnotationClickPayload
    const annotation = payload.annotation ?? null
    const customDataBinding = parseBindingFromCustomData(annotation?.customdata)
    if (customDataBinding) {
      return customDataBinding
    }

    const annotationIndex = parseAnnotationIndexFromPayload(payload)
    if (annotationIndex !== null) {
      const mapped = annotationIndexMapRef.current[annotationIndex]
      if (mapped) {
        return mapped
      }
    }

    return resolveBindingByFallback(annotation?.x)
  }

  const handleAnnotationClickEvent = (eventPayload: unknown) => {
    if (typeof eventPayload !== 'object' || eventPayload === null) {
      return
    }

    const payload = eventPayload as PlotlyAnnotationClickPayload
    const mouseButton = Number(payload.event?.button)
    if (Number.isFinite(mouseButton) && mouseButton !== 0) {
      return
    }

    const binding = resolveBindingFromAnnotationClick(payload)
    if (!binding) {
      return
    }

    const shiftPressed = shiftDownRef.current || payload.event?.shiftKey === true
    if (shiftPressed) {
      deletePeakByBinding(binding)
      setSelectedPeak((current) =>
        current &&
        current.spectrumId === binding.spectrumId &&
        current.peakId === binding.peakId
          ? null
          : current,
      )
      return
    }

    setSelectedPeak({
      spectrumId: binding.spectrumId,
      peakId: binding.peakId,
      source: binding.source,
      ...(Number.isFinite(binding.x) ? { x: binding.x } : {}),
    })
  }

  const handlePlotRelayout = (relayoutEvent: unknown) => {
    if (!leaderLabelsActive) {
      return
    }

    if (typeof relayoutEvent !== 'object' || relayoutEvent === null) {
      return
    }

    const relayoutPayload = relayoutEvent as Readonly<Record<string, unknown>>
    const clearedAnnotationIndexes = parseAnnotationTextClears(relayoutPayload)
    if (clearedAnnotationIndexes.size > 0) {
      for (const annotationIndex of clearedAnnotationIndexes) {
        const binding = annotationIndexMapRef.current[annotationIndex]
        if (!binding) {
          continue
        }

        deletePeakByBinding(binding)
        setSelectedPeak((current) =>
          current &&
          current.spectrumId === binding.spectrumId &&
          current.peakId === binding.peakId
            ? null
            : current,
        )
      }
    }

    const updatesByIndex = parseAnnotationOffsetUpdates(relayoutPayload)
    if (updatesByIndex.size === 0) {
      return
    }

    for (const [annotationIndex, update] of updatesByIndex) {
      if (clearedAnnotationIndexes.has(annotationIndex)) {
        continue
      }

      const binding = annotationIndexMapRef.current[annotationIndex]
      if (!binding) {
        continue
      }

      const currentOffset =
        peakLabelOffsetsById[binding.spectrumId]?.[binding.peakId] ?? {
          ax: 0,
          ay: -40,
        }
      const nextAx = update.ax ?? currentOffset.ax
      const nextAy = update.ay ?? currentOffset.ay

      dispatch({
        type: 'PEAKS_LABEL_OFFSET_SET',
        spectrumId: binding.spectrumId,
        peakId: binding.peakId,
        ax: nextAx,
        ay: nextAy,
      })
    }
  }

  const setupPlotlyClickAnnotationListener = useCallback(
    (graphDiv: PlotlyHTMLElement | null) => {
      const eventBridge =
        onPlotlyClickAnnotationBridgeRef.current ??
        ((payload: unknown) => {
          onPlotlyClickAnnotationRef.current(payload)
        })
      onPlotlyClickAnnotationBridgeRef.current = eventBridge

      const nextGraphDiv = graphDiv as PlotlyAnnotationEmitter | null
      const previousGraphDiv = boundAnnotationGraphDivRef.current

      if (previousGraphDiv && previousGraphDiv !== nextGraphDiv) {
        detachPlotlyAnnotationListener(previousGraphDiv, eventBridge)
        boundAnnotationGraphDivRef.current = null
      }

      if (!nextGraphDiv || typeof nextGraphDiv.on !== 'function') {
        return
      }

      if (boundAnnotationGraphDivRef.current === nextGraphDiv) {
        return
      }

      nextGraphDiv.on('plotly_clickannotation', eventBridge)
      boundAnnotationGraphDivRef.current = nextGraphDiv
    },
    [],
  )

  useEffect(() => {
    onPlotlyClickAnnotationRef.current = handleAnnotationClickEvent
  })

  useEffect(() => {
    const map: Record<number, PeakAnnotationBinding> = {}
    const peakAnnotationStartIndex = inlineAnnotations.length
    for (let i = 0; i < peakAnnotationBindings.length; i += 1) {
      map[peakAnnotationStartIndex + i] = peakAnnotationBindings[i]
    }
    annotationIndexMapRef.current = map
  })

  useEffect(() => {
    selectedPeakRef.current = selectedPeak
  }, [selectedPeak])

  useEffect(() => {
    const handleDeleteKey = (event: KeyboardEvent) => {
      if (event.key !== 'Delete' && event.key !== 'Backspace') {
        return
      }

      if (
        isTypingElement(event.target) ||
        isTypingElement(document.activeElement)
      ) {
        return
      }

      const selected = selectedPeakRef.current
      if (!selected) {
        return
      }

      event.preventDefault()
      deletePeakByBinding(selected)
      setSelectedPeak(null)
    }

    window.addEventListener('keydown', handleDeleteKey)
    return () => {
      window.removeEventListener('keydown', handleDeleteKey)
    }
  }, [deletePeakByBinding])

  useEffect(() => {
    const handleShiftDown = (event: KeyboardEvent) => {
      if (event.key === 'Shift') {
        shiftDownRef.current = true
      }
    }

    const handleShiftUp = (event: KeyboardEvent) => {
      if (event.key === 'Shift') {
        shiftDownRef.current = false
      }
    }

    const handleWindowBlur = () => {
      shiftDownRef.current = false
    }

    window.addEventListener('keydown', handleShiftDown)
    window.addEventListener('keyup', handleShiftUp)
    window.addEventListener('blur', handleWindowBlur)

    return () => {
      window.removeEventListener('keydown', handleShiftDown)
      window.removeEventListener('keyup', handleShiftUp)
      window.removeEventListener('blur', handleWindowBlur)
    }
  }, [])

  useEffect(() => {
    return () => {
      const eventBridge = onPlotlyClickAnnotationBridgeRef.current
      if (!eventBridge) {
        return
      }

      detachPlotlyAnnotationListener(
        boundAnnotationGraphDivRef.current,
        eventBridge,
      )
      boundAnnotationGraphDivRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!plotDivRef.current) {
      return
    }

    // Ensure export and live view share the same tick text styling.
    applyTickTextInlineStyles(plotDivRef.current, {
      tickLabelBold: graphics.tickLabelBold,
      tickLabelItalic: graphics.tickLabelItalic,
    })
  }, [
    graphics.tickLabelBold,
    graphics.tickLabelItalic,
    plotDivRef,
  ])

  const layout: Partial<Layout> = {
    uirevision: uiRevision,
    editrevision: editRevision,
    autosize: !shouldPreviewCanvasSize,
    ...(shouldPreviewCanvasSize
      ? {
          width: previewW,
          height: previewH,
        }
      : {}),
    margin: layoutMargins,
    showlegend:
      useInlineLabels
        ? false
        : primaryTraces.length + (baselineTrace ? 1 : 0) > 1,
    ...(paletteColors === null ? { colorway: DEFAULT_COLORWAY } : {}),
    ...(mergedAnnotations.length > 0
      ? { annotations: mergedAnnotations }
      : {}),
    font: {
      family: graphics.fontFamily || 'Arial',
      size: graphics.baseFontSize,
      color: '#0f172a',
    },
    paper_bgcolor: canvasColor,
    plot_bgcolor: canvasColor,
    xaxis: {
      title: {
        text: xAxisLabelStyled,
        font: {
          size: graphics.baseFontSize + 2,
        },
        standoff: titleStandoff,
      },
      gridcolor: graphics.gridColor,
      gridwidth: graphics.gridWidth,
      zeroline: false,
      showgrid: graphics.showGrid,
      automargin: true,
      showticklabels: graphics.showXTickLabels,
      showline: true,
      mirror: isBox,
      linewidth: graphics.axisLineWidth,
      linecolor: graphics.axisLineColor,
      ticks: showXMarks ? 'outside' : '',
      ticklen: showXMarks ? 6 : 0,
      tickcolor: graphics.axisLineColor,
      tickfont: {
        size: graphics.tickFontSize,
        color: graphics.axisLineColor,
      },
      ...(hasXRange
        ? {
            autorange: false,
            range: plot.invertX
              ? [plot.xMax, plot.xMin]
              : [plot.xMin, plot.xMax],
          }
        : {
            autorange: plot.invertX ? 'reversed' : true,
          }),
    },
    yaxis: {
      title: {
        text: yAxisLabelStyled,
        font: {
          size: graphics.baseFontSize + 2,
        },
        standoff: titleStandoff,
      },
      gridcolor: graphics.gridColor,
      gridwidth: graphics.gridWidth,
      zeroline: false,
      showgrid: graphics.showGrid,
      automargin: true,
      showticklabels: graphics.showYTickLabels,
      showline: true,
      mirror: isBox,
      linewidth: graphics.axisLineWidth,
      linecolor: graphics.axisLineColor,
      ticks: showYMarks ? 'outside' : '',
      ticklen: showYMarks ? 6 : 0,
      tickcolor: graphics.axisLineColor,
      tickfont: {
        size: graphics.tickFontSize,
        color: graphics.axisLineColor,
      },
      ...(hasYRange
        ? {
            autorange: false,
            range: [plot.yMin, plot.yMax],
          }
        : {
            autorange: true,
          }),
    },
  }

  const config: Partial<Config> & { sanitize?: boolean } = {
    responsive: true,
    scrollZoom: true,
    displaylogo: false,
    sanitize: false,
    editable: leaderLabelsActive,
    ...(leaderLabelsActive
      ? {
          edits: {
            annotationPosition: true,
            annotationText: false,
            titleText: false,
            axisTitleText: false,
            legendText: false,
            shapePosition: false,
          },
        }
      : {}),
  }
  const plotFrameStyle = shouldPreviewCanvasSize
    ? { width: previewW, height: previewH }
    : { height: 'clamp(360px, 70vh, 900px)' }

  return (
    <section>
      <div className="flex min-h-[30rem] flex-col rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Plot</h2>

        <div
          className={`mt-4 min-h-[20rem] flex-none overflow-hidden rounded-lg border border-slate-200 p-2 dark:border-slate-800 ${canvasFrameClass} ${tickClass}`}
          style={plotFrameStyle}
        >
          <Plot
            className={`h-full w-full overflow-hidden ${tickClass}`}
            data={traces}
            layout={layout}
            config={config}
            onInitialized={(_, graphDiv) => {
              plotDivRef.current = graphDiv as PlotlyHTMLElement
              setupPlotlyClickAnnotationListener(
                graphDiv as PlotlyHTMLElement,
              )
              applyTickTextInlineStyles(plotDivRef.current, {
                tickLabelBold: graphics.tickLabelBold,
                tickLabelItalic: graphics.tickLabelItalic,
              })
            }}
            onUpdate={(_, graphDiv) => {
              plotDivRef.current = graphDiv as PlotlyHTMLElement
              setupPlotlyClickAnnotationListener(
                graphDiv as PlotlyHTMLElement,
              )
              applyTickTextInlineStyles(plotDivRef.current, {
                tickLabelBold: graphics.tickLabelBold,
                tickLabelItalic: graphics.tickLabelItalic,
              })
            }}
            onClick={handlePlotClick}
            onRelayout={handlePlotRelayout}
            useResizeHandler
            style={{ width: '100%', height: '100%' }}
          />
        </div>

        <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
          Debug: traces={traces.length}, active={resolvedActiveSpectrum?.name ?? 'none'}, x=[
          {formatRangeValue(xRange.min)}, {formatRangeValue(xRange.max)}], y=[
          {formatRangeValue(yRange.min)}, {formatRangeValue(yRange.max)}]
        </p>

        {hasAnyPeaksForTable ? <PeaksListPanel /> : null}
      </div>
    </section>
  )
}
