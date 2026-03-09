import type { Spectrum } from '../../app/types/core'

type SpectrumToDelimitedTextOptions = {
  spectrum: Spectrum
  delimiter: ';' | '\t'
  decimalComma: boolean
}

function formatNumber(value: number, decimalComma: boolean): string {
  const serialized = Number.isFinite(value) ? value.toString() : ''
  return decimalComma ? serialized.replace('.', ',') : serialized
}

export function spectrumToDelimitedText(
  options: SpectrumToDelimitedTextOptions,
): string {
  const { spectrum, delimiter, decimalComma } = options
  const dataRows: string[] = []
  const pointCount = Math.min(spectrum.x.length, spectrum.y.length)

  for (let index = 0; index < pointCount; index += 1) {
    const xValue = spectrum.x[index]
    const yValue = spectrum.y[index]

    if (!Number.isFinite(xValue) || !Number.isFinite(yValue)) {
      continue
    }

    dataRows.push(
      `${formatNumber(xValue, decimalComma)}${delimiter}${formatNumber(yValue, decimalComma)}`,
    )
  }

  const lines: string[] = []
  lines.push(`# name: ${spectrum.name}`)
  lines.push(`# points: ${dataRows.length}`)
  lines.push(`# exportedAt: ${new Date().toISOString()}`)
  lines.push(`x${delimiter}y`)
  lines.push(...dataRows)

  return lines.join('\n')
}
