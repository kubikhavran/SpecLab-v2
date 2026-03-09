import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type MutableRefObject,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import type { PlotlyHTMLElement } from 'plotly.js'
import { PlotArea } from '../features/plot/PlotArea'
import { savePresetsToStorage } from '../features/presets/presetsStorage'
import { Sidebar } from '../ui/Sidebar'
import { AppStoreProvider, useAppState } from './state/AppStore'

const THEME_STORAGE_KEY = 'speclab.theme'
const SIDEBAR_WIDTH_STORAGE_KEY = 'speclab.sidebarWidth'
const SYSTEM_DARK_QUERY = '(prefers-color-scheme: dark)'
const DEFAULT_SIDEBAR_W = 320
const MIN_SIDEBAR_W = 260
const MAX_SIDEBAR_W = 560

type AppLayoutContentProps = {
  plotDivRef: MutableRefObject<PlotlyHTMLElement | null>
}

function clampSidebarWidth(width: number): number {
  return Math.max(MIN_SIDEBAR_W, Math.min(MAX_SIDEBAR_W, width))
}

function getInitialSidebarWidth(): number {
  if (typeof window === 'undefined') {
    return DEFAULT_SIDEBAR_W
  }

  try {
    const storedValue = window.localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY)
    if (!storedValue) {
      return DEFAULT_SIDEBAR_W
    }

    const parsedWidth = Number(storedValue)
    if (!Number.isFinite(parsedWidth)) {
      return DEFAULT_SIDEBAR_W
    }

    return clampSidebarWidth(Math.round(parsedWidth))
  } catch {
    return DEFAULT_SIDEBAR_W
  }
}

function AppLayoutContent({ plotDivRef }: AppLayoutContentProps) {
  const { themeMode, presets, activePresetId } = useAppState()
  const [sidebarW, setSidebarW] = useState<number>(getInitialSidebarWidth)
  const [isResizing, setIsResizing] = useState(false)
  const sidebarWRef = useRef(sidebarW)
  const sidebarScale = Math.max(
    1,
    Math.min(sidebarW / DEFAULT_SIDEBAR_W, 1.35),
  )
  const sidebarStyle: CSSProperties = {
    width: sidebarW,
    flex: '0 0 auto',
  }
  ;(sidebarStyle as Record<string, string | number>)['--sb-scale'] = sidebarScale

  useEffect(() => {
    sidebarWRef.current = sidebarW
  }, [sidebarW])

  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }

    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, themeMode)
    } catch {
      // Ignore persistence failures in restricted browser modes.
    }
  }, [themeMode])

  useEffect(() => {
    savePresetsToStorage(presets, activePresetId)
  }, [presets, activePresetId])

  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }

    const root = document.documentElement
    const mediaQuery = window.matchMedia(SYSTEM_DARK_QUERY)
    const applyTheme = (prefersDark: boolean) => {
      const isDark = themeMode === 'dark' || (themeMode === 'system' && prefersDark)
      root.classList.toggle('dark', isDark)
    }

    applyTheme(mediaQuery.matches)

    if (themeMode !== 'system') {
      return
    }

    const handleThemeChange = (event: MediaQueryListEvent) => {
      applyTheme(event.matches)
    }

    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', handleThemeChange)
      return () => {
        mediaQuery.removeEventListener('change', handleThemeChange)
      }
    }

    mediaQuery.addListener(handleThemeChange)
    return () => {
      mediaQuery.removeListener(handleThemeChange)
    }
  }, [themeMode])

  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }

    try {
      window.localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(sidebarW))
    } catch {
      // Ignore persistence failures in restricted browser modes.
    }
  }, [sidebarW])

  useEffect(() => {
    if (!isResizing) {
      return
    }

    const body = document.body
    const previousUserSelect = body.style.userSelect
    const previousCursor = body.style.cursor

    body.style.userSelect = 'none'
    body.style.cursor = 'col-resize'

    return () => {
      body.style.userSelect = previousUserSelect
      body.style.cursor = previousCursor
    }
  }, [isResizing])

  const handleResizeStart = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) {
      return
    }

    event.preventDefault()
    const startX = event.clientX
    const startWidth = sidebarWRef.current
    const pointerId = event.pointerId

    setIsResizing(true)
    const onPointerMove = (moveEvent: PointerEvent) => {
      if (moveEvent.pointerId !== pointerId) {
        return
      }

      const deltaX = moveEvent.clientX - startX
      setSidebarW(clampSidebarWidth(Math.round(startWidth + deltaX)))
    }

    const stopResize = (endEvent: PointerEvent) => {
      if (endEvent.pointerId !== pointerId) {
        return
      }

      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', stopResize)
      window.removeEventListener('pointercancel', stopResize)
      setIsResizing(false)
    }

    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', stopResize)
    window.addEventListener('pointercancel', stopResize)
  }

  const handleResizeKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      setSidebarW((prev) => clampSidebarWidth(prev - 10))
      return
    }

    if (event.key === 'ArrowRight') {
      event.preventDefault()
      setSidebarW((prev) => clampSidebarWidth(prev + 10))
    }
  }

  return (
    <div className="h-screen bg-slate-100 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <div className="flex h-full">
        <aside
          className="speclab-sidebar relative shrink-0 border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
          style={sidebarStyle}
        >
          <Sidebar plotDivRef={plotDivRef} />
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize sidebar"
            aria-valuemin={MIN_SIDEBAR_W}
            aria-valuemax={MAX_SIDEBAR_W}
            aria-valuenow={sidebarW}
            tabIndex={0}
            className={`group absolute inset-y-0 right-0 z-20 w-2.5 cursor-col-resize touch-none bg-transparent outline-none focus-visible:bg-slate-200/60 focus-visible:ring-1 focus-visible:ring-sky-400 dark:focus-visible:bg-slate-700/60 ${
              isResizing
                ? 'bg-sky-200/50 dark:bg-sky-700/40'
                : 'hover:bg-slate-200/35 dark:hover:bg-slate-700/35'
            }`}
            onPointerDown={handleResizeStart}
            onDoubleClick={() => setSidebarW(DEFAULT_SIDEBAR_W)}
            onKeyDown={handleResizeKeyDown}
          >
            <div
              className={`pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 ${
                isResizing
                  ? 'bg-sky-500/90 dark:bg-sky-400/90'
                  : 'bg-slate-300/70 group-hover:bg-slate-400/90 dark:bg-slate-700/80 dark:group-hover:bg-slate-500/90'
              }`}
            />
          </div>
        </aside>

        <main className="min-w-0 flex-[1_1_auto] overflow-auto p-6 lg:p-8">
          <PlotArea plotDivRef={plotDivRef} />
        </main>
      </div>
    </div>
  )
}

export function AppLayout() {
  const plotDivRef = useRef<PlotlyHTMLElement | null>(null)

  return (
    <AppStoreProvider>
      <AppLayoutContent plotDivRef={plotDivRef} />
    </AppStoreProvider>
  )
}
