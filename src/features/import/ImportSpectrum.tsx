import type { ChangeEvent } from 'react'
import { useRef, useState } from 'react'
import { useAppDispatch } from '../../app/state/AppStore'
import { parseSpectrumText } from './parseSpectrumText'

export function ImportSpectrum() {
  const dispatch = useAppDispatch()
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [errors, setErrors] = useState<string[]>([])

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = event.currentTarget.files

    if (!selectedFiles || selectedFiles.length === 0) {
      return
    }

    setErrors([])
    const files = Array.from(selectedFiles)
    const nextErrors: string[] = []

    for (const file of files) {
      try {
        const text = await file.text()
        const parsedSpectrum = parseSpectrumText(text, file.name)
        const spectrum = {
          ...parsedSpectrum,
          meta: {
            ...(parsedSpectrum.meta ?? {}),
            sourceName: file.name,
          },
        }

        dispatch({
          type: 'SPECTRUM_ADD',
          spectrum,
        })
      } catch (importError) {
        const message =
          importError instanceof Error
            ? importError.message
            : 'Spectrum import failed.'

        nextErrors.push(`${file.name}: ${message}`)
      }
    }

    setErrors(nextErrors)

    if (inputRef.current) {
      inputRef.current.value = ''
    } else {
      event.currentTarget.value = ''
    }
  }

  return (
    <div className="space-y-2">
      <label className="inline-flex cursor-pointer items-center rounded-md border border-slate-300 bg-slate-50 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100">
        Import .txt/.csv
        <input
          ref={inputRef}
          className="hidden"
          type="file"
          multiple
          accept=".txt,.csv,text/plain"
          onChange={handleFileChange}
        />
      </label>

      <p className="text-[11px] text-slate-500">
        First two numeric columns are used as x/y points. You can select
        multiple files (Ctrl/Shift).
      </p>

      {errors.length > 0 ? (
        <ul className="space-y-1 text-[11px] text-red-600">
          {errors.map((error, index) => (
            <li key={`${error}-${index}`}>{error}</li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
