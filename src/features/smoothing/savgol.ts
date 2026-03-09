function reflectIndex(index: number, length: number): number {
  let reflected = index

  while (reflected < 0 || reflected >= length) {
    if (reflected < 0) {
      reflected = -reflected - 1
    } else {
      reflected = 2 * length - reflected - 1
    }
  }

  return reflected
}

function solveLinearSystem(matrix: number[][], rhs: number[]): number[] {
  const size = matrix.length
  const augmented = matrix.map((row, index) => [...row, rhs[index]])

  for (let pivotIndex = 0; pivotIndex < size; pivotIndex += 1) {
    let bestRow = pivotIndex

    for (let rowIndex = pivotIndex + 1; rowIndex < size; rowIndex += 1) {
      if (
        Math.abs(augmented[rowIndex][pivotIndex]) >
        Math.abs(augmented[bestRow][pivotIndex])
      ) {
        bestRow = rowIndex
      }
    }

    if (bestRow !== pivotIndex) {
      ;[augmented[pivotIndex], augmented[bestRow]] = [
        augmented[bestRow],
        augmented[pivotIndex],
      ]
    }

    const pivot = augmented[pivotIndex][pivotIndex]

    if (!Number.isFinite(pivot) || Math.abs(pivot) < 1e-12) {
      throw new Error('Savitzky-Golay system is singular.')
    }

    for (let columnIndex = pivotIndex; columnIndex <= size; columnIndex += 1) {
      augmented[pivotIndex][columnIndex] /= pivot
    }

    for (let rowIndex = 0; rowIndex < size; rowIndex += 1) {
      if (rowIndex === pivotIndex) {
        continue
      }

      const factor = augmented[rowIndex][pivotIndex]

      if (factor === 0) {
        continue
      }

      for (let columnIndex = pivotIndex; columnIndex <= size; columnIndex += 1) {
        augmented[rowIndex][columnIndex] -=
          factor * augmented[pivotIndex][columnIndex]
      }
    }
  }

  return augmented.map((row) => row[size])
}

function buildSavgolCoefficients(window: number, polyOrder: number): number[] {
  const half = Math.floor(window / 2)
  const order = polyOrder
  const normalSize = order + 1
  const normal = Array.from({ length: normalSize }, () =>
    new Array<number>(normalSize).fill(0),
  )

  for (let i = -half; i <= half; i += 1) {
    const powers = new Array<number>(normalSize)
    powers[0] = 1

    for (let p = 1; p < normalSize; p += 1) {
      powers[p] = powers[p - 1] * i
    }

    for (let row = 0; row < normalSize; row += 1) {
      for (let col = 0; col < normalSize; col += 1) {
        normal[row][col] += powers[row] * powers[col]
      }
    }
  }

  const target = new Array<number>(normalSize).fill(0)
  target[0] = 1
  const weights = solveLinearSystem(normal, target)
  const coefficients: number[] = []

  for (let i = -half; i <= half; i += 1) {
    let coefficient = 0
    let power = 1

    for (let p = 0; p < normalSize; p += 1) {
      coefficient += weights[p] * power
      power *= i
    }

    coefficients.push(coefficient)
  }

  return coefficients
}

export function savgolSmooth(
  y: number[],
  window: number,
  polyOrder: number,
): number[] {
  if (y.length === 0) {
    return []
  }

  const safeWindow = Math.max(5, Math.floor(window))
  const oddWindow = safeWindow % 2 === 0 ? safeWindow + 1 : safeWindow

  if (polyOrder >= oddWindow) {
    throw new Error('Savitzky-Golay requires polyOrder < window.')
  }

  if (oddWindow > y.length) {
    return y.slice()
  }

  const coefficients = buildSavgolCoefficients(oddWindow, polyOrder)
  const half = Math.floor(oddWindow / 2)
  const output = new Array<number>(y.length)

  for (let index = 0; index < y.length; index += 1) {
    let sum = 0

    for (let offset = -half; offset <= half; offset += 1) {
      const coeff = coefficients[offset + half]
      const sampleIndex = reflectIndex(index + offset, y.length)
      const sample = Number.isFinite(y[sampleIndex]) ? y[sampleIndex] : 0

      sum += coeff * sample
    }

    output[index] = sum
  }

  return output
}
