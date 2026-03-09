import { savgolSmooth } from '../smoothing/savgol'

export type CosmicRemovalOptions = {
  window: number
  threshold: number
  maxWidth: number
  positiveOnly: boolean
  iterations: number
}

type NormalizedOptions = {
  window: number
  threshold: number
  maxWidth: number
  positiveOnly: boolean
  iterations: number
}

function median(values: number[]): number {
  if (values.length === 0) {
    return 0
  }

  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)

  if (sorted.length % 2 === 1) {
    return sorted[middle]
  }

  return (sorted[middle - 1] + sorted[middle]) / 2
}

function normalizeOptions(opts: CosmicRemovalOptions): NormalizedOptions {
  const rawWindow = Number.isFinite(opts.window) ? Math.round(opts.window) : 11
  const minWindow = Math.max(5, rawWindow)
  const oddWindow = minWindow % 2 === 0 ? minWindow + 1 : minWindow
  const threshold =
    Number.isFinite(opts.threshold) && opts.threshold > 0 ? opts.threshold : 6
  const maxWidth =
    Number.isFinite(opts.maxWidth) && opts.maxWidth >= 1
      ? Math.round(opts.maxWidth)
      : 3
  const iterations =
    Number.isFinite(opts.iterations) && opts.iterations >= 1
      ? Math.round(opts.iterations)
      : 1

  return {
    window: oddWindow,
    threshold,
    maxWidth,
    positiveOnly: opts.positiveOnly !== false,
    iterations,
  }
}

function buildSpikeMask(
  residual: number[],
  threshold: number,
  maxWidth: number,
  positiveOnly: boolean,
): boolean[] {
  const residualMedian = median(residual)
  const absDeviation = residual.map((value) => Math.abs(value - residualMedian))
  const sigma = 1.4826 * median(absDeviation)

  if (!Number.isFinite(sigma) || sigma <= 0) {
    return new Array<boolean>(residual.length).fill(false)
  }

  const cut = threshold * sigma
  const candidates = residual.map((value) =>
    positiveOnly ? value > cut : Math.abs(value) > cut,
  )
  const mask = new Array<boolean>(residual.length).fill(false)

  // Only keep narrow candidate groups as cosmic spikes.
  for (let i = 0; i < candidates.length; i += 1) {
    if (!candidates[i]) {
      continue
    }

    const start = i
    while (i + 1 < candidates.length && candidates[i + 1]) {
      i += 1
    }
    const end = i

    if (end - start + 1 <= maxWidth) {
      for (let j = start; j <= end; j += 1) {
        mask[j] = true
      }
    }
  }

  return mask
}

function interpolateMaskedSegments(
  ySource: number[],
  ySmooth: number[],
  mask: boolean[],
): number[] {
  const output = ySource.slice()

  for (let i = 0; i < mask.length; i += 1) {
    if (!mask[i]) {
      continue
    }

    const start = i
    while (i + 1 < mask.length && mask[i + 1]) {
      i += 1
    }
    const end = i

    let left = start - 1
    while (left >= 0 && mask[left]) {
      left -= 1
    }

    let right = end + 1
    while (right < mask.length && mask[right]) {
      right += 1
    }

    const hasNeighbors = left >= 0 && right < mask.length
    const leftValue = hasNeighbors ? ySource[left] : Number.NaN
    const rightValue = hasNeighbors ? ySource[right] : Number.NaN

    if (
      hasNeighbors &&
      Number.isFinite(leftValue) &&
      Number.isFinite(rightValue) &&
      right > left
    ) {
      const span = right - left
      for (let index = start; index <= end; index += 1) {
        const t = (index - left) / span
        output[index] = leftValue + t * (rightValue - leftValue)
      }
      continue
    }

    for (let index = start; index <= end; index += 1) {
      const smoothValue = ySmooth[index]
      output[index] = Number.isFinite(smoothValue) ? smoothValue : ySource[index]
    }
  }

  return output
}

export function removeCosmicRays(
  y: number[],
  opts: CosmicRemovalOptions,
): { yClean: number[]; mask: boolean[]; removedCount: number } {
  if (y.length === 0) {
    return {
      yClean: [],
      mask: [],
      removedCount: 0,
    }
  }

  const normalized = normalizeOptions(opts)
  const polyOrder = Math.max(2, Math.min(3, normalized.window - 2))
  const globalMask = new Array<boolean>(y.length).fill(false)
  let yClean = y.slice()

  for (let iteration = 0; iteration < normalized.iterations; iteration += 1) {
    const ySmooth = savgolSmooth(yClean, normalized.window, polyOrder)
    const residual = yClean.map((value, index) => {
      const source = Number.isFinite(value) ? value : 0
      const smooth = Number.isFinite(ySmooth[index]) ? ySmooth[index] : 0

      return source - smooth
    })
    const iterationMask = buildSpikeMask(
      residual,
      normalized.threshold,
      normalized.maxWidth,
      normalized.positiveOnly,
    )

    if (!iterationMask.some(Boolean)) {
      break
    }

    for (let index = 0; index < iterationMask.length; index += 1) {
      if (iterationMask[index]) {
        globalMask[index] = true
      }
    }

    yClean = interpolateMaskedSegments(yClean, ySmooth, iterationMask)
  }

  const removedCount = globalMask.reduce(
    (count, isRemoved) => count + (isRemoved ? 1 : 0),
    0,
  )

  return {
    yClean,
    mask: globalMask,
    removedCount,
  }
}
