function dot(left: number[], right: number[]): number {
  let sum = 0

  for (let index = 0; index < left.length; index += 1) {
    sum += left[index] * right[index]
  }

  return sum
}

function applySecondDiffTransposeDiff(values: number[]): number[] {
  const length = values.length
  const output = new Array<number>(length).fill(0)

  for (let index = 0; index <= length - 3; index += 1) {
    const diff = values[index] - 2 * values[index + 1] + values[index + 2]

    output[index] += diff
    output[index + 1] -= 2 * diff
    output[index + 2] += diff
  }

  return output
}

function multiplySystem(
  vector: number[],
  weights: number[],
  lambda: number,
): number[] {
  const output = new Array<number>(vector.length)

  for (let index = 0; index < vector.length; index += 1) {
    output[index] = weights[index] * vector[index]
  }

  if (lambda === 0 || vector.length < 3) {
    return output
  }

  const smoothTerm = applySecondDiffTransposeDiff(vector)

  for (let index = 0; index < output.length; index += 1) {
    output[index] += lambda * smoothTerm[index]
  }

  return output
}

function solveWeightedSystem(
  y: number[],
  weights: number[],
  lambda: number,
  initial: number[],
): number[] {
  const length = y.length
  const rhs = new Array<number>(length)

  for (let index = 0; index < length; index += 1) {
    rhs[index] = weights[index] * y[index]
  }

  const x = initial.slice()
  const ax = multiplySystem(x, weights, lambda)
  const residual = new Array<number>(length)

  for (let index = 0; index < length; index += 1) {
    residual[index] = rhs[index] - ax[index]
  }

  const direction = residual.slice()
  let rsOld = dot(residual, residual)
  const rhsNorm = Math.sqrt(dot(rhs, rhs))
  const tolerance = 1e-8 * (rhsNorm + 1)

  if (!Number.isFinite(rsOld) || Math.sqrt(rsOld) <= tolerance) {
    return x
  }

  const maxIterations = Math.min(1000, Math.max(50, length))

  for (let iteration = 0; iteration < maxIterations; iteration += 1) {
    const ad = multiplySystem(direction, weights, lambda)
    const denominator = dot(direction, ad)

    if (!Number.isFinite(denominator) || Math.abs(denominator) < 1e-20) {
      break
    }

    const alpha = rsOld / denominator

    if (!Number.isFinite(alpha)) {
      break
    }

    for (let index = 0; index < length; index += 1) {
      x[index] += alpha * direction[index]
      residual[index] -= alpha * ad[index]
    }

    const rsNew = dot(residual, residual)

    if (!Number.isFinite(rsNew) || Math.sqrt(rsNew) <= tolerance) {
      break
    }

    const beta = rsNew / rsOld

    for (let index = 0; index < length; index += 1) {
      direction[index] = residual[index] + beta * direction[index]
    }

    rsOld = rsNew
  }

  return x
}

export function aslsBaseline(
  y: number[],
  lambda: number,
  p: number,
  iterations: number,
): number[] {
  if (y.length === 0) {
    return []
  }

  const safeY = y.map((value) => (Number.isFinite(value) ? value : 0))

  if (safeY.length < 3) {
    return safeY.slice()
  }

  const safeLambda = Number.isFinite(lambda) ? Math.max(0, lambda) : 0
  const safeP = Number.isFinite(p) ? Math.min(0.999999, Math.max(0.000001, p)) : 0.01
  const safeIterations = Number.isFinite(iterations)
    ? Math.max(1, Math.floor(iterations))
    : 10

  const weights = new Array<number>(safeY.length).fill(1)
  let baseline = safeY.slice()

  for (let iteration = 0; iteration < safeIterations; iteration += 1) {
    baseline = solveWeightedSystem(safeY, weights, safeLambda, baseline)

    for (let index = 0; index < weights.length; index += 1) {
      weights[index] = safeY[index] > baseline[index] ? safeP : 1 - safeP
    }
  }

  return baseline
}
