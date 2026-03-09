import type { GraphicsPalette } from '../../app/types/core'

const colorblindPalette = [
  '#0072B2',
  '#D55E00',
  '#009E73',
  '#CC79A7',
  '#F0E442',
  '#56B4E9',
  '#E69F00',
  '#000000',
]

const pubBoldPalette = [
  '#1F77B4',
  '#D62728',
  '#2CA02C',
  '#9467BD',
  '#FF7F0E',
  '#17BECF',
  '#8C564B',
  '#E377C2',
  '#BCBD22',
  '#7F7F7F',
]

const pubColorblindPalette = [
  '#0072B2',
  '#D55E00',
  '#009E73',
  '#CC79A7',
  '#E69F00',
  '#56B4E9',
  '#999933',
  '#000000',
  '#882255',
  '#44AA99',
]

const tolBrightPalette = [
  '#4477AA',
  '#EE6677',
  '#228833',
  '#CCBB44',
  '#66CCEE',
  '#AA3377',
  '#BBBBBB',
  '#000000',
]

const tolMutedPalette = [
  '#332288',
  '#88CCEE',
  '#44AA99',
  '#117733',
  '#999933',
  '#DDCC77',
  '#CC6677',
  '#882255',
  '#AA4499',
]

const deepRainbowPalette = [
  '#7A0403',
  '#B42000',
  '#D84A05',
  '#F07818',
  '#E7A21A',
  '#B7B31A',
  '#6FAF2D',
  '#2C9F50',
  '#008D7A',
  '#007F9F',
  '#2C6DB2',
  '#5A59B0',
  '#7A42A8',
  '#9C2A8F',
]

const tableau10Palette = [
  '#4E79A7',
  '#F28E2B',
  '#E15759',
  '#76B7B2',
  '#59A14F',
  '#EDC948',
  '#B07AA1',
  '#FF9DA7',
  '#9C755F',
  '#BAB0AC',
]

const dark2Palette = [
  '#1B9E77',
  '#D95F02',
  '#7570B3',
  '#E7298A',
  '#66A61E',
  '#E6AB02',
  '#A6761D',
  '#666666',
]

const pairedPalette = [
  '#A6CEE3',
  '#1F78B4',
  '#B2DF8A',
  '#33A02C',
  '#FB9A99',
  '#E31A1C',
  '#FDBF6F',
  '#FF7F00',
  '#CAB2D6',
  '#6A3D9A',
  '#FFFF99',
  '#B15928',
]

const viridisPalette = [
  '#440154',
  '#482878',
  '#3E4989',
  '#31688E',
  '#26828E',
  '#1F9E89',
  '#35B779',
  '#6CCE59',
  '#B4DE2C',
  '#FDE725',
]

const viridisDarkPalette = [
  '#440154',
  '#482475',
  '#414487',
  '#355F8D',
  '#2A788E',
  '#21908C',
  '#22A884',
  '#44BF70',
  '#7AD151',
]

const plasmaPalette = [
  '#0D0887',
  '#41049D',
  '#6A00A8',
  '#8F0DA4',
  '#B12A90',
  '#CC4778',
  '#E16462',
  '#F2844B',
  '#FCA636',
  '#F0F921',
]

const plasmaDarkPalette = [
  '#0D0887',
  '#46039F',
  '#7201A8',
  '#9C179E',
  '#BD3786',
  '#D8576B',
  '#ED7953',
  '#FB9F3A',
  '#FDCA26',
]

const magmaPalette = [
  '#000004',
  '#1B0C41',
  '#4F0A6D',
  '#781C6D',
  '#A52C60',
  '#CF4446',
  '#ED6925',
  '#FB9B06',
  '#F7D13D',
  '#FCFDBF',
]

const cividisPalette = [
  '#00204C',
  '#00306F',
  '#2A3F85',
  '#4A4C8C',
  '#67598E',
  '#81658A',
  '#9A7083',
  '#B37C78',
  '#CC886B',
  '#E69B5E',
]

const cividisDarkPalette = [
  '#00224E',
  '#123570',
  '#3B496C',
  '#575D6D',
  '#707173',
  '#8A8678',
  '#A39B7C',
  '#BCB07E',
  '#D5C57F',
]

const electrochemPalette = [
  '#B40426',
  '#D73027',
  '#F46D43',
  '#FDAE61',
  '#FEE08B',
  '#D9EF8B',
  '#A6D96A',
  '#66C2A5',
  '#3288BD',
  '#5E4FA2',
  '#6A3D9A',
  '#7B3294',
  '#4D004B',
]

const monoPalette = [
  '#111827',
  '#1F2937',
  '#374151',
  '#4B5563',
  '#6B7280',
  '#9CA3AF',
  '#D1D5DB',
  '#E5E7EB',
]

const neonPalette = [
  '#00E5FF',
  '#FF00E5',
  '#7CFF00',
  '#FFD500',
  '#FF3B30',
  '#5E5CE6',
  '#00FF9C',
  '#FF6B00',
]

export function sampleEven(base: string[], count: number): string[] {
  if (base.length === 0) {
    return []
  }

  if (count <= 1) {
    return [base[0]]
  }

  return Array.from({ length: count }, (_, i) => {
    const index = Math.round((i * (base.length - 1)) / (count - 1))
    return base[index]
  })
}

function getGradientColors(base: string[], count: number | undefined): string[] {
  if (typeof count === 'number' && Number.isFinite(count) && count > 0) {
    return sampleEven(base, Math.max(1, Math.floor(count)))
  }

  return base
}

export function getPaletteColors(
  palette: GraphicsPalette,
  count?: number,
): string[] | null {
  switch (palette) {
    case 'auto':
      return null
    case 'pubBold':
      return pubBoldPalette
    case 'pubColorblind':
      return pubColorblindPalette
    case 'tolBright':
      return tolBrightPalette
    case 'tolMuted':
      return tolMutedPalette
    case 'deepRainbow':
      return getGradientColors(deepRainbowPalette, count)
    case 'viridisDark':
      return getGradientColors(viridisDarkPalette, count)
    case 'plasmaDark':
      return getGradientColors(plasmaDarkPalette, count)
    case 'cividisDark':
      return getGradientColors(cividisDarkPalette, count)
    case 'colorblind':
      return colorblindPalette
    case 'tableau10':
      return tableau10Palette
    case 'dark2':
      return dark2Palette
    case 'paired':
      return pairedPalette
    case 'viridis':
      return getGradientColors(viridisPalette, count)
    case 'plasma':
      return getGradientColors(plasmaPalette, count)
    case 'magma':
      return getGradientColors(magmaPalette, count)
    case 'cividis':
      return getGradientColors(cividisPalette, count)
    case 'electrochem':
      return getGradientColors(electrochemPalette, count)
    case 'mono':
      return monoPalette
    case 'neon':
      return neonPalette
    default:
      return null
  }
}
