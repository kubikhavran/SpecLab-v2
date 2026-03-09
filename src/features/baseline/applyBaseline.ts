export function applyBaseline(y: number[], baseline: number[]): number[] {
  const pointCount = Math.min(y.length, baseline.length)
  const output = y.slice()

  for (let index = 0; index < pointCount; index += 1) {
    output[index] = y[index] - baseline[index]
  }

  return output
}
