import type { PlotlyHTMLElement } from 'plotly.js'
import type { GraphicsSettings } from '../../app/types/core'

type TickTextNode = SVGTextElement & {
  style: CSSStyleDeclaration
}

type TickTextStyleSnapshotEntry = {
  node: TickTextNode
  fontWeight: string
  fontStyle: string
}

export type TickTextStyleSnapshot = TickTextStyleSnapshotEntry[]

const TICK_TEXT_SELECTOR = [
  '.xtick text',
  '.ytick text',
  '.xaxislayer-above text',
  '.yaxislayer-above text',
  '.xaxislayer-above .xtick text',
  '.yaxislayer-above .ytick text',
  '.xaxislayer-below text',
  '.yaxislayer-below text',
  '.xaxislayer-below .xtick text',
  '.yaxislayer-below .ytick text',
].join(', ')

function getTickTextNodes(graphDiv: PlotlyHTMLElement): TickTextNode[] {
  const raw = Array.from(
    graphDiv.querySelectorAll<TickTextNode>(TICK_TEXT_SELECTOR),
  )

  return Array.from(new Set(raw))
}

export function captureTickTextInlineStyles(
  graphDiv: PlotlyHTMLElement,
): TickTextStyleSnapshot {
  return getTickTextNodes(graphDiv).map((node) => ({
    node,
    fontWeight: node.style.fontWeight,
    fontStyle: node.style.fontStyle,
  }))
}

export function applyTickTextInlineStyles(
  graphDiv: PlotlyHTMLElement,
  graphics: Pick<GraphicsSettings, 'tickLabelBold' | 'tickLabelItalic'>,
): void {
  const fontWeight = graphics.tickLabelBold ? '700' : ''
  const fontStyle = graphics.tickLabelItalic ? 'italic' : ''

  getTickTextNodes(graphDiv).forEach((node) => {
    if (fontWeight) {
      node.style.fontWeight = fontWeight
    } else {
      node.style.removeProperty('font-weight')
    }

    if (fontStyle) {
      node.style.fontStyle = fontStyle
    } else {
      node.style.removeProperty('font-style')
    }
  })
}

export function restoreTickTextInlineStyles(
  snapshot: TickTextStyleSnapshot,
): void {
  snapshot.forEach(({ node, fontWeight, fontStyle }) => {
    if (!node.isConnected) {
      return
    }

    if (fontWeight) {
      node.style.fontWeight = fontWeight
    } else {
      node.style.removeProperty('font-weight')
    }

    if (fontStyle) {
      node.style.fontStyle = fontStyle
    } else {
      node.style.removeProperty('font-style')
    }
  })
}
