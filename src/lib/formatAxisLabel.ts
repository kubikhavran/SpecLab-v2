function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (char) => {
    switch (char) {
      case '&':
        return '&amp;'
      case '<':
        return '&lt;'
      case '>':
        return '&gt;'
      case '"':
        return '&quot;'
      case "'":
        return '&#39;'
      default:
        return char
    }
  })
}

function findMatchingBrace(input: string, openIndex: number): number {
  let depth = 0

  for (let i = openIndex; i < input.length; i += 1) {
    const char = input[i]
    if (char === '{') {
      depth += 1
      continue
    }
    if (char !== '}') {
      continue
    }

    depth -= 1
    if (depth === 0) {
      return i
    }
  }

  return -1
}

function formatSegment(input: string): string {
  let output = ''

  for (let i = 0; i < input.length; i += 1) {
    const char = input[i]
    const isSup = char === '^'
    const isSub = char === '_'
    if (!isSup && !isSub) {
      output += escapeHtml(char)
      continue
    }

    const tag = isSup ? 'sup' : 'sub'
    const nextChar = input[i + 1]

    if (nextChar === '{') {
      const closingIndex = findMatchingBrace(input, i + 1)
      if (closingIndex !== -1) {
        const innerRaw = input.slice(i + 2, closingIndex)
        const innerFormatted = formatSegment(innerRaw)
        output += `<${tag}>${innerFormatted}</${tag}>`
        i = closingIndex
        continue
      }
    }

    if (typeof nextChar === 'string' && nextChar.length > 0 && !/\s/.test(nextChar)) {
      output += `<${tag}>${escapeHtml(nextChar)}</${tag}>`
      i += 1
      continue
    }

    output += escapeHtml(char)
  }

  return output
}

export function formatAxisLabel(raw: string): string {
  return formatSegment(raw ?? '')
}

