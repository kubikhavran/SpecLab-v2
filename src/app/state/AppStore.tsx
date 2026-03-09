/* eslint-disable react-refresh/only-export-components */
import type { Dispatch, ReactNode } from 'react'
import { createContext, useContext, useReducer } from 'react'
import type { AppState } from '../types/core'
import type { Action } from './reducer'
import { reducer } from './reducer'
import { initialState } from './store'

const AppStateContext = createContext<AppState | undefined>(undefined)
const AppDispatchContext = createContext<Dispatch<Action> | undefined>(undefined)

type AppStoreProviderProps = {
  children: ReactNode
}

export function AppStoreProvider({ children }: AppStoreProviderProps) {
  const [state, dispatch] = useReducer(reducer, initialState)

  return (
    <AppStateContext.Provider value={state}>
      <AppDispatchContext.Provider value={dispatch}>
        {children}
      </AppDispatchContext.Provider>
    </AppStateContext.Provider>
  )
}

export function useAppState(): AppState {
  const state = useContext(AppStateContext)

  if (state === undefined) {
    throw new Error('useAppState must be used within an AppStoreProvider.')
  }

  return state
}

export function useAppDispatch(): Dispatch<Action> {
  const dispatch = useContext(AppDispatchContext)

  if (dispatch === undefined) {
    throw new Error('useAppDispatch must be used within an AppStoreProvider.')
  }

  return dispatch
}
