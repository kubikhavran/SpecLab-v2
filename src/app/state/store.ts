import {
  DEFAULT_DATA_LABELING_SETTINGS,
  DEFAULT_PEAKS_SETTINGS,
  type AppState,
  type ThemeMode,
} from '../types/core'
import { loadPresetsFromStorage } from '../../features/presets/presetsStorage'

const THEME_STORAGE_KEY = 'speclab.theme'
const EXPORT_FOLDER_STORAGE_KEY = 'speclab.exportFolder'

function getInitialThemeMode(): ThemeMode {
  if (typeof window === 'undefined') {
    return 'system'
  }

  try {
    const storedValue = window.localStorage.getItem(THEME_STORAGE_KEY)

    if (
      storedValue === 'system' ||
      storedValue === 'light' ||
      storedValue === 'dark'
    ) {
      return storedValue
    }
  } catch {
    // Fall back to system theme when localStorage is unavailable.
  }

  return 'system'
}

function getInitialExportFolder(): string {
  if (typeof window === 'undefined') {
    return ''
  }

  try {
    const storedValue = window.localStorage.getItem(EXPORT_FOLDER_STORAGE_KEY)
    return typeof storedValue === 'string' ? storedValue : ''
  } catch {
    return ''
  }
}

export const initialState: AppState = {
  themeMode: getInitialThemeMode(),
  spectra: [],
  activeSpectrumId: undefined,
  plot: {
    showGrid: true,
    showAllSpectra: false,
    reverseOverlayOrder: false,
    stackOffset: 0,
    uiRevision: 1,
    xMin: null,
    xMax: null,
    yMin: null,
    yMax: null,
    invertX: false,
  },
  dataLabeling: { ...DEFAULT_DATA_LABELING_SETTINGS },
  ...loadPresetsFromStorage(),
  cosmicCleanYById: {},
  manualCleanYById: {},
  manualUndoStackById: {},
  peaks: { ...DEFAULT_PEAKS_SETTINGS },
  peaksAutoById: {},
  peaksManualById: {},
  peakLabelOffsetsById: {},
  processedYById: {},
  baselineYById: {},
  smoothedYById: {},
  cosmic: {
    window: 11,
    threshold: 6,
    maxWidth: 3,
    positiveOnly: true,
    iterations: 1,
    manualEnabled: false,
  },
  baseline: {
    enabled: false,
    showOverlay: true,
    lambda: 1e6,
    p: 0.01,
    iterations: 10,
  },
  smoothing: {
    window: 11,
    polyOrder: 3,
  },
  graphics: {
    xLabel: 'X',
    yLabel: 'Y',
    axisLabelBold: false,
    axisLabelItalic: false,
    tickLabelBold: false,
    tickLabelItalic: false,
    showXTickMarks: true,
    showYTickMarks: true,
    spectrumLabelBold: false,
    spectrumLabelItalic: false,
    axisLineWidth: 4,
    traceLineWidth: 4,
    fontFamily: 'Arial',
    baseFontSize: 32,
    tickFontSize: 30,
    palette: 'auto',
    exportWidth: 1600,
    exportHeight: 900,
    showXTickLabels: true,
    showYTickLabels: false,
    axisLineColor: '#000000',
    frameMode: 'open',
    showGrid: false,
    gridColor: '#e2e8f0',
    gridWidth: 1,
    inlineSpectrumLabels: true,
    plotCanvas: 'auto',
    previewCanvasSize: false,
  },
  export: {
    filename: '',
    folder: getInitialExportFolder(),
  },
}
