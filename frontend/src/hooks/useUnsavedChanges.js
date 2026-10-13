import { useContext, useEffect, useRef, useState } from 'react'
import { UNSAFE_NavigationContext } from 'react-router-dom'

export function useUnsavedChanges({ isDirty, isSubmittedRef, onSaveDraft }) {
  const navigationContext = useContext(UNSAFE_NavigationContext)
  const navigator = navigationContext?.navigator

  const [blockedTarget, setBlockedTarget] = useState(null)
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState('')

  const isDirtyRef = useRef(isDirty)
  isDirtyRef.current = isDirty

  const isRestoringRef = useRef(false)
  const currentIndexRef = useRef(typeof window !== 'undefined' ? (window.history.state?.idx ?? 0) : 0)

  const shouldBlock = () => {
    if (isSubmittedRef?.current) return false
    return Boolean(isDirtyRef.current)
  }

  // Track history index whenever location or render updates
  useEffect(() => {
    if (typeof window !== 'undefined') {
      currentIndexRef.current = window.history.state?.idx ?? 0
    }
  })

  // Browser navigation protection: beforeunload for reload / close / external nav
  useEffect(() => {
    if (!isDirty || isSubmittedRef?.current) return

    const handleBeforeUnload = (event) => {
      if (isSubmittedRef?.current) return
      event.preventDefault()
      event.returnValue = ''
      return ''
    }

    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
    }
  }, [isDirty, isSubmittedRef])

  // Native browser Back/Forward (POP navigation) protection
  useEffect(() => {
    const handlePopState = (event) => {
      if (isRestoringRef.current) {
        isRestoringRef.current = false
        currentIndexRef.current = window.history.state?.idx ?? 0
        return
      }

      if (shouldBlock()) {
        event.stopImmediatePropagation()

        const nextIndex = event.state?.idx ?? window.history.state?.idx ?? 0
        const delta = nextIndex - currentIndexRef.current

        setSaveError('')
        setBlockedTarget({
          type: 'pop',
          delta: delta || -1,
          targetLocation: window.location.pathname + window.location.search + window.location.hash,
        })
      } else {
        currentIndexRef.current = window.history.state?.idx ?? 0
      }
    }

    window.addEventListener('popstate', handlePopState, true)
    return () => {
      window.removeEventListener('popstate', handlePopState, true)
    }
  }, [isSubmittedRef])

  // React Router internal navigation protection (Links, NavLinks, navigate())
  useEffect(() => {
    if (!navigator) return

    const originalPush = navigator.push
    const originalReplace = navigator.replace
    const originalGo = navigator.go

    navigator.push = (...args) => {
      if (shouldBlock()) {
        setSaveError('')
        setBlockedTarget({ type: 'push', args })
        return
      }
      return originalPush.apply(navigator, args)
    }

    navigator.replace = (...args) => {
      if (shouldBlock()) {
        setSaveError('')
        setBlockedTarget({ type: 'replace', args })
        return
      }
      return originalReplace.apply(navigator, args)
    }

    if (originalGo) {
      navigator.go = (...args) => {
        if (shouldBlock()) {
          setSaveError('')
          setBlockedTarget({ type: 'go', args })
          return
        }
        return originalGo.apply(navigator, args)
      }
    }

    return () => {
      navigator.push = originalPush
      navigator.replace = originalReplace
      if (originalGo) {
        navigator.go = originalGo
      }
    }
  }, [navigator])

  const proceedNavigation = (target) => {
    if (isSubmittedRef) isSubmittedRef.current = true
    isDirtyRef.current = false
    setBlockedTarget(null)
    setSaveError('')

    if (target.type === 'pop') {
      if (navigator) {
        navigator.replace(target.targetLocation)
      }
    } else if (target.type === 'push') {
      navigator.push(...target.args)
    } else if (target.type === 'replace') {
      navigator.replace(...target.args)
    } else if (target.type === 'go' && navigator.go) {
      navigator.go(...target.args)
    }
  }

  const handleLeaveWithoutSaving = () => {
    if (blockedTarget) {
      proceedNavigation(blockedTarget)
    }
  }

  const handleCancel = () => {
    if (blockedTarget?.type === 'pop') {
      const { delta } = blockedTarget
      setBlockedTarget(null)
      setSaveError('')
      if (delta !== 0) {
        isRestoringRef.current = true
        window.history.go(-delta)
      }
    } else {
      setBlockedTarget(null)
      setSaveError('')
    }
  }

  const handleSaveDraft = async () => {
    if (!onSaveDraft) return
    setIsSaving(true)
    setSaveError('')
    try {
      const result = await onSaveDraft()
      if (result === false) {
        // Validation or draft save indicated failure
        return
      }
      if (blockedTarget) {
        proceedNavigation(blockedTarget)
      }
    } catch (err) {
      setSaveError(err?.message || 'Failed to save draft.')
    } finally {
      setIsSaving(false)
    }
  }

  return {
    isOpen: Boolean(blockedTarget),
    isSaving,
    saveError,
    setSaveError,
    handleSaveDraft,
    handleLeaveWithoutSaving,
    handleCancel,
  }
}
