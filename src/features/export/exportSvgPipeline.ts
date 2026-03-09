import { saveBlobOutput } from './exportSave'

type TickStyleOptions = {
  tickLabelBold: boolean
  tickLabelItalic: boolean
}

type DownloadPngFromSvgOptions = {
  svgText: string
  filename: string
  width: number
  height: number
  scale: number
  transparentBackground: boolean
  exportFolder: string
}

const TICK_TEXT_SELECTOR = [
  '.xaxislayer-above .xtick text',
  '.xaxislayer-below .xtick text',
  '.yaxislayer-above .ytick text',
  '.yaxislayer-below .ytick text',
  '.xaxislayer-above text.xtick',
  '.xaxislayer-below text.xtick',
  '.yaxislayer-above text.ytick',
  '.yaxislayer-below text.ytick',
].join(', ')

export function decodePlotlySvgDataUrl(dataUrl: string): string {
  const commaIndex = dataUrl.indexOf(',')
  if (commaIndex < 0) {
    return dataUrl
  }

  const meta = dataUrl.slice(0, commaIndex)
  const payload = dataUrl.slice(commaIndex + 1)

  if (/;base64/i.test(meta)) {
    try {
      return atob(payload)
    } catch {
      return ''
    }
  }

  try {
    return decodeURIComponent(payload)
  } catch {
    return payload
  }
}

export function patchTickStyles(
  svgText: string,
  options: TickStyleOptions,
): string {
  const parser = new DOMParser()
  const xmlDocument = parser.parseFromString(svgText, 'image/svg+xml')
  const tickNodes = Array.from(
    xmlDocument.querySelectorAll<SVGTextElement>(TICK_TEXT_SELECTOR),
  )

  tickNodes.forEach((node) => {
    if (options.tickLabelBold) {
      node.setAttribute('font-weight', '700')
    } else {
      node.removeAttribute('font-weight')
    }

    if (options.tickLabelItalic) {
      node.setAttribute('font-style', 'italic')
    } else {
      node.removeAttribute('font-style')
    }
  })

  return new XMLSerializer().serializeToString(xmlDocument)
}

export async function downloadSvg(
  svgText: string,
  filename: string,
  exportFolder: string,
): Promise<void> {
  const svgBlob = new Blob([svgText], {
    type: 'image/svg+xml;charset=utf-8',
  })
  await saveBlobOutput({
    fileName: filename,
    blob: svgBlob,
    mime: 'image/svg+xml;charset=utf-8',
    exportFolder,
  })
}

export async function downloadPngFromSvg({
  svgText,
  filename,
  width,
  height,
  scale,
  transparentBackground,
  exportFolder,
}: DownloadPngFromSvgOptions): Promise<void> {
  const svgBlob = new Blob([svgText], {
    type: 'image/svg+xml;charset=utf-8',
  })
  const svgUrl = URL.createObjectURL(svgBlob)

  try {
    const image = new Image()
    const imageLoaded = new Promise<void>((resolve, reject) => {
      image.onload = () => resolve()
      image.onerror = () =>
        reject(new Error('Failed to load exported SVG for PNG conversion.'))
    })

    image.src = svgUrl
    await imageLoaded

    const outputScale = Math.max(1, scale)
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(width * outputScale))
    canvas.height = Math.max(1, Math.round(height * outputScale))

    const context = canvas.getContext('2d')
    if (!context) {
      throw new Error('Failed to initialize canvas context for PNG export.')
    }

    if (!transparentBackground) {
      context.fillStyle = '#ffffff'
      context.fillRect(0, 0, canvas.width, canvas.height)
    }

    context.drawImage(image, 0, 0, canvas.width, canvas.height)

    const pngBlob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((blob) => {
        if (blob) {
          resolve(blob)
          return
        }

        reject(new Error('Canvas PNG export failed.'))
      }, 'image/png')
    })

    await saveBlobOutput({
      fileName: filename,
      blob: pngBlob,
      mime: 'image/png',
      exportFolder,
    })
  } finally {
    URL.revokeObjectURL(svgUrl)
  }
}
