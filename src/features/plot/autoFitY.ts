import type { Spectrum } from '../../app/types/core'

type ComputeAutoFitYOptions = {
  spectra: Spectrum[]
  activeSpectrumId?: string
  showAllSpectra: boolean
  stackOffset: number
  xMin: number | null
  xMax: number | null
}

type YRange = {
  yMin: number
  yMax: number
}

function getPlottedSpectra(
  spectra: Spectrum[],
  activeSpectrumId: string | undefined,
  showAllSpectra: boolean,
): Spectrum[] {
  if (spectra.length === 0) {
    return []
  }

  if (showAllSpectra) {
    return spectra
  }

  const activeSpectrum =
    activeSpectrumId !== undefined
      ? spectra.find((spectrum) => spectrum.id === activeSpectrumId)
      : undefined

  return [activeSpectrum ?? spectra[0]]
}

function getXWindow(
  spectra: Spectrum[],
  xMin: number | null,
  xMax: number | null,
): { min: number; max: number } | null {
  if (xMin != null && xMax != null) {
    return {
      min: Math.min(xMin, xMax),
      max: Math.max(xMin, xMax),
    }
  }

  let globalMin = Number.POSITIVE_INFINITY
  let globalMax = Number.NEGATIVE_INFINITY

  for (const spectrum of spectra) {
    const pointCount = Math.min(spectrum.x.length, spectrum.y.length)

    for (let index = 0; index < pointCount; index += 1) {
      const xValue = spectrum.x[index]
      const yValue = spectrum.y[index]

      if (!Number.isFinite(xValue) || !Number.isFinite(yValue)) {
        continue
      }

      if (xValue < globalMin) {
        globalMin = xValue
      }

      if (xValue > globalMax) {
        globalMax = xValue
      }
    }
  }

  if (!Number.isFinite(globalMin) || !Number.isFinite(globalMax)) {
    return null
  }

  return { min: globalMin, max: globalMax }
}

export function computeAutoFitY(options: ComputeAutoFitYOptions): YRange | null {
  const { spectra, activeSpectrumId, showAllSpectra, stackOffset, xMin, xMax } =
    options
  const plottedSpectra = getPlottedSpectra(
    spectra,
    activeSpectrumId,
    showAllSpectra,
  )

  if (plottedSpectra.length === 0) {
    return null
  }

  const xWindow = getXWindow(plottedSpectra, xMin, xMax)

  if (!xWindow) {
    return null
  }

  let yMin = Number.POSITIVE_INFINITY
  let yMax = Number.NEGATIVE_INFINITY

  for (let spectrumIndex = 0; spectrumIndex < plottedSpectra.length; spectrumIndex += 1) {
    const spectrum = plottedSpectra[spectrumIndex]
    const pointCount = Math.min(spectrum.x.length, spectrum.y.length)
    const yOffset = spectrumIndex * stackOffset

    for (let pointIndex = 0; pointIndex < pointCount; pointIndex += 1) {
      const xValue = spectrum.x[pointIndex]
      const yValue = spectrum.y[pointIndex]

      if (!Number.isFinite(xValue) || !Number.isFinite(yValue)) {
        continue
      }

      if (xValue < xWindow.min || xValue > xWindow.max) {
        continue
      }

      const stackedY = yValue + yOffset

      if (stackedY < yMin) {
        yMin = stackedY
      }

      if (stackedY > yMax) {
        yMax = stackedY
      }
    }
  }

  if (!Number.isFinite(yMin) || !Number.isFinite(yMax)) {
    return null
  }

  return { yMin, yMax }
}
