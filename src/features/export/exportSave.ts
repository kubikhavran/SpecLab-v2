import { downloadBlobFile } from '../../lib/downloadBlobFile'
import { downloadTextFile } from '../../lib/downloadTextFile'

export const EXPORT_FOLDER_STORAGE_KEY = 'speclab.exportFolder'

type SaveBlobOptions = {
  fileName: string
  blob: Blob
  mime: string
  exportFolder: string
}

type SaveTextOptions = {
  fileName: string
  text: string
  mime: string
  exportFolder: string
}

function trimFolderPath(folder: string): string {
  return folder.trim()
}

function joinFolderPath(folder: string, fileName: string): string {
  const trimmedFolder = trimFolderPath(folder).replace(/[\\/]+$/, '')
  if (trimmedFolder.length === 0) {
    return fileName
  }

  const separator = trimmedFolder.includes('\\') ? '\\' : '/'
  return `${trimmedFolder}${separator}${fileName}`
}

export function isTauriRuntime(): boolean {
  if (typeof window === 'undefined') {
    return false
  }

  const maybeTauriWindow = window as Window & {
    __TAURI_INTERNALS__?: unknown
  }
  return typeof maybeTauriWindow.__TAURI_INTERNALS__ === 'object'
}

export async function chooseExportFolder(
  currentFolder: string,
): Promise<string | null> {
  if (!isTauriRuntime()) {
    return null
  }

  const { open } = await import('@tauri-apps/plugin-dialog')
  const selected = await open({
    directory: true,
    multiple: false,
    defaultPath: trimFolderPath(currentFolder) || undefined,
    title: 'Choose export folder',
  })

  return typeof selected === 'string' ? selected : null
}

export async function saveBlobOutput(options: SaveBlobOptions): Promise<void> {
  const { fileName, blob, mime, exportFolder } = options
  const folder = trimFolderPath(exportFolder)

  if (isTauriRuntime() && folder.length > 0) {
    const { writeFile } = await import('@tauri-apps/plugin-fs')
    const filePath = joinFolderPath(folder, fileName)
    const bytes = new Uint8Array(await blob.arrayBuffer())
    await writeFile(filePath, bytes)
    return
  }

  downloadBlobFile(fileName, blob, mime)
}

export async function saveTextOutput(options: SaveTextOptions): Promise<void> {
  const { fileName, text, mime, exportFolder } = options
  const folder = trimFolderPath(exportFolder)

  if (isTauriRuntime() && folder.length > 0) {
    const { writeTextFile } = await import('@tauri-apps/plugin-fs')
    const filePath = joinFolderPath(folder, fileName)
    await writeTextFile(filePath, text)
    return
  }

  downloadTextFile(fileName, text, mime)
}

