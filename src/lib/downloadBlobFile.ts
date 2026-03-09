export function downloadBlobFile(
  filename: string,
  blob: Blob,
  mime = 'application/octet-stream',
) {
  const normalizedBlob = blob.type ? blob : blob.slice(0, blob.size, mime)
  const url = URL.createObjectURL(normalizedBlob)
  const anchor = document.createElement('a')

  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}
