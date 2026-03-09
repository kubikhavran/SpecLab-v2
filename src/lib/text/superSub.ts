const SUPER_MAP: Record<string, string> = {
  '0': '\u2070',
  '1': '\u00B9',
  '2': '\u00B2',
  '3': '\u00B3',
  '4': '\u2074',
  '5': '\u2075',
  '6': '\u2076',
  '7': '\u2077',
  '8': '\u2078',
  '9': '\u2079',
  '+': '\u207A',
  '-': '\u207B',
  '(': '\u207D',
  ')': '\u207E',
}

const SUB_MAP: Record<string, string> = {
  '0': '\u2080',
  '1': '\u2081',
  '2': '\u2082',
  '3': '\u2083',
  '4': '\u2084',
  '5': '\u2085',
  '6': '\u2086',
  '7': '\u2087',
  '8': '\u2088',
  '9': '\u2089',
  '+': '\u208A',
  '-': '\u208B',
  '(': '\u208D',
  ')': '\u208E',
}

function mapChars(value: string, map: Record<string, string>): string {
  return Array.from(value).map((char) => map[char] ?? char).join('')
}

export function toSuperscript(str: string): string {
  return mapChars(str, SUPER_MAP)
}

export function toSubscript(str: string): string {
  return mapChars(str, SUB_MAP)
}

