export interface SpectrumPoint {
  x: number
  y: number
}

export interface Spectrum {
  id: string
  name: string
  x: number[]
  y: number[]
  meta?: Record<string, unknown>
}

export interface PlotSettings {
  showGrid: boolean
  showAllSpectra: boolean
  reverseOverlayOrder: boolean
  stackOffset: number
  uiRevision: number
  xMin?: number | null
  xMax?: number | null
  yMin?: number | null
  yMax?: number | null
  invertX: boolean
}

export interface BaselineSettings {
  enabled: boolean
  showOverlay: boolean
  lambda: number
  p: number
  iterations: number
}

export interface SmoothingSettings {
  window: number
  polyOrder: number
}

export interface CosmicSettings {
  window: number
  threshold: number
  maxWidth: number
  positiveOnly: boolean
  iterations: number
  manualEnabled: boolean
}

export type PeakKind = 'max' | 'min'
export type PeakSource = 'auto' | 'manual'

// Manual peaks store only X/index; Y is resolved from plotted data at render time.
export type Peak = {
  id: string
  x: number
  source: PeakSource
  i?: number
  kind?: PeakKind
  prominence?: number
  width?: number
}

export type PeaksSettings = {
  enabled: boolean
  mode: 'active' | 'all'
  source: 'displayed' | 'processed'
  useRegion: boolean
  regionXMin: string
  regionXMax: string
  polarity: 'max' | 'min' | 'both'
  minProminence: number
  minDistance: number
  maxPeaks: number
  manualPickEnabled: boolean
  showMarkers: boolean
  showLabels: boolean
  showLeaderLines: boolean
  labelPlacement: 'leader'
  labelAngleDeg: number
  labelFontSize: number
  labelBold: boolean
  labelItalic: boolean
  labelColorMode: 'trace' | 'custom'
  labelColor: string
  leaderColorMode: 'trace' | 'custom'
  leaderColor: string
  leaderLineWidth: number
  decimals: number
}

export const DEFAULT_PEAKS_SETTINGS: PeaksSettings = {
  enabled: false,
  mode: 'active',
  source: 'displayed',
  useRegion: false,
  regionXMin: '',
  regionXMax: '',
  polarity: 'max',
  minProminence: 0,
  minDistance: 10,
  maxPeaks: 20,
  manualPickEnabled: false,
  showMarkers: true,
  showLabels: true,
  showLeaderLines: true,
  labelPlacement: 'leader',
  labelAngleDeg: -90,
  labelFontSize: 24,
  labelBold: false,
  labelItalic: false,
  labelColorMode: 'trace',
  labelColor: '#111827',
  leaderColorMode: 'trace',
  leaderColor: '#111827',
  leaderLineWidth: 1,
  decimals: 0,
}

export type PeakLabelOffset = {
  ax: number
  ay: number
}

export type RenumberMode = 'index' | 'sequence' | 'extract'
export type ExtractPreset = 'mv' | 'firstNumber' | 'lastNumber' | 'regex' | 'slice'
export type LabelExtractMode = 'none' | 'filename'

export type LabelExtractSettings = {
  mode: LabelExtractMode
  preset: ExtractPreset
  start: string
  end: string
  trimResult: boolean
  numbersOnly: boolean
  prefix: string
  suffix: string
  regex: string
}

export type DataLabelingSettings = {
  renumberMode: RenumberMode
  renumberPrefix: string
  invertOrder: boolean
  sequenceStart: string
  sequenceStep: string
  sequenceSuffix: string
  labelExtract: LabelExtractSettings
}

export const DEFAULT_LABEL_EXTRACT_SETTINGS: LabelExtractSettings = {
  mode: 'filename',
  preset: 'mv',
  start: '0',
  end: '10',
  trimResult: true,
  numbersOnly: false,
  prefix: '',
  suffix: ' mV',
  regex: '(\\d+)mV',
}

export const DEFAULT_DATA_LABELING_SETTINGS: DataLabelingSettings = {
  renumberMode: 'index',
  renumberPrefix: '',
  invertOrder: false,
  sequenceStart: '1',
  sequenceStep: '1',
  sequenceSuffix: 'mV',
  labelExtract: DEFAULT_LABEL_EXTRACT_SETTINGS,
}

export type PresetPayload = {
  themeMode: ThemeMode
  plot: PlotSettings
  graphics: GraphicsSettings
  baseline: BaselineSettings
  smoothing: SmoothingSettings
  cosmic: CosmicSettings
  dataLabeling: DataLabelingSettings
  peaksSettings?: PeaksSettings
}

export type Preset = {
  id: string
  name: string
  createdAt: number
  updatedAt: number
  payload: PresetPayload
}

export type ThemeMode = 'system' | 'light' | 'dark'
export type PlotCanvasMode = 'auto' | 'white' | 'dark'

export type GraphicsPalette =
  | 'auto'
  | 'pubBold'
  | 'pubColorblind'
  | 'tolBright'
  | 'tolMuted'
  | 'deepRainbow'
  | 'viridisDark'
  | 'plasmaDark'
  | 'cividisDark'
  | 'colorblind'
  | 'tableau10'
  | 'dark2'
  | 'paired'
  | 'viridis'
  | 'plasma'
  | 'magma'
  | 'cividis'
  | 'electrochem'
  | 'mono'
  | 'neon'

export type GraphicsSettings = {
  xLabel: string
  yLabel: string
  axisLabelBold: boolean
  axisLabelItalic: boolean
  tickLabelBold: boolean
  tickLabelItalic: boolean
  showXTickMarks: boolean
  showYTickMarks: boolean
  spectrumLabelBold: boolean
  spectrumLabelItalic: boolean
  showXTickLabels: boolean
  showYTickLabels: boolean
  showGrid: boolean
  gridColor: string
  gridWidth: number
  previewCanvasSize: boolean
  axisLineWidth: number
  axisLineColor: string
  frameMode: 'open' | 'box'
  traceLineWidth: number
  fontFamily: string
  baseFontSize: number
  tickFontSize: number
  palette: GraphicsPalette
  inlineSpectrumLabels: boolean
  plotCanvas: PlotCanvasMode
  exportWidth: number
  exportHeight: number
}

export type ExportSettings = {
  filename: string
  folder: string
}

export interface AppState {
  themeMode: ThemeMode
  spectra: Spectrum[]
  activeSpectrumId?: string
  plot: PlotSettings
  dataLabeling: DataLabelingSettings
  presets: Preset[]
  activePresetId: string | null
  cosmicCleanYById: Record<string, number[]>
  manualCleanYById: Record<string, number[]>
  manualUndoStackById: Record<string, number[][]>
  peaks: PeaksSettings
  peaksAutoById: Record<string, Peak[]>
  peaksManualById: Record<string, Peak[]>
  peakLabelOffsetsById: Record<string, Record<string, PeakLabelOffset>>
  processedYById: Record<string, number[]>
  baselineYById: Record<string, number[]>
  smoothedYById: Record<string, number[]>
  cosmic: CosmicSettings
  baseline: BaselineSettings
  smoothing: SmoothingSettings
  graphics: GraphicsSettings
  export: ExportSettings
}
