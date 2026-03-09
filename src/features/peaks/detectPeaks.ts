export type DetectedPeak = {
  x: number
  i: number
  prominence: number
  y: number
}

type DetectPeaksOptions = {
  minProminence: number
  minDistanceX: number
  maxPeaks: number
  xMin?: number
  xMax?: number
}

function inRange(x: number, minValue?: number, maxValue?: number): boolean {
  if (minValue === undefined || maxValue === undefined) {
    return true
  }

  const low = Math.min(minValue, maxValue)
  const high = Math.max(minValue, maxValue)
  return x >= low && x <= high
}

function findLocalMaximaIndices(y: number[]): number[] {
  const peaks: number[] = []
  if (y.length < 3) {
    return peaks
  }

  let i = 1
  while (i < y.length - 1) {
    const prev = y[i - 1]
    const curr = y[i]
    const next = y[i + 1]

    if (curr > prev && curr > next) {
      peaks.push(i)
      i += 1
      continue
    }

    if (curr > prev && curr === next) {
      const start = i
      let end = i + 1
      while (end < y.length - 1 && y[end] === y[end + 1]) {
        end += 1
      }

      if (y[end] > y[end + 1]) {
        peaks.push(Math.floor((start + end) / 2))
      }

      i = end + 1
      continue
    }

    i += 1
  }

  return peaks
}

function computeProminenceAt(
  x: number[],
  y: number[],
  index: number,
  windowX: number,
): number {
  const xPeak = x[index]
  const yPeak = y[index]
  let leftMin = yPeak
  let rightMin = yPeak

  for (let i = index; i >= 0; i -= 1) {
    if (Math.abs(xPeak - x[i]) > windowX) {
      break
    }
    leftMin = Math.min(leftMin, y[i])
  }

  for (let i = index; i < y.length; i += 1) {
    if (Math.abs(xPeak - x[i]) > windowX) {
      break
    }
    rightMin = Math.min(rightMin, y[i])
  }

  return yPeak - Math.max(leftMin, rightMin)
}

export function detectPeaks(
  x: number[],
  y: number[],
  opts: DetectPeaksOptions,
): DetectedPeak[] {
  const pointCount = Math.min(x.length, y.length)
  if (pointCount < 3) {
    return []
  }

  const maxPeaks = Math.max(1, Math.floor(opts.maxPeaks))
  const minProminence = Math.max(0, opts.minProminence)
  const minDistanceX = Math.max(0, opts.minDistanceX)
  const windowX = Math.max(minDistanceX, 1e-12)

  const filteredX: number[] = []
  const filteredY: number[] = []
  const originalIndices: number[] = []

  for (let i = 0; i < pointCount; i += 1) {
    const xi = x[i]
    const yi = y[i]
    if (!Number.isFinite(xi) || !Number.isFinite(yi)) {
      continue
    }
    if (!inRange(xi, opts.xMin, opts.xMax)) {
      continue
    }

    filteredX.push(xi)
    filteredY.push(yi)
    originalIndices.push(i)
  }

  if (filteredX.length < 3) {
    return []
  }

  const candidateIndices = findLocalMaximaIndices(filteredY)
  const candidates: DetectedPeak[] = []

  for (const candidateIndex of candidateIndices) {
    const prominence = computeProminenceAt(
      filteredX,
      filteredY,
      candidateIndex,
      windowX,
    )
    if (prominence < minProminence) {
      continue
    }

    candidates.push({
      x: filteredX[candidateIndex],
      y: filteredY[candidateIndex],
      i: originalIndices[candidateIndex],
      prominence,
    })
  }

  if (candidates.length === 0) {
    return []
  }

  const byProminence = [...candidates].sort((a, b) => b.prominence - a.prominence)
  const selected: DetectedPeak[] = []

  for (const candidate of byProminence) {
    const tooClose = selected.some(
      (picked) => Math.abs(candidate.x - picked.x) < minDistanceX,
    )
    if (tooClose) {
      continue
    }

    selected.push(candidate)
    if (selected.length >= maxPeaks) {
      break
    }
  }

  return selected.sort((a, b) => a.x - b.x)
}
