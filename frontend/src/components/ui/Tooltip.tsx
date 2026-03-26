import React, { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'

interface TooltipProps {
  content: string
  children: React.ReactElement
  delay?: number
}

export function Tooltip({ content, children, delay = 400 }: TooltipProps) {
  const [visible, setVisible] = useState(false)
  const [coords, setCoords] = useState({ top: 0, left: 0 })
  const triggerRef = useRef<HTMLElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  function show() {
    timerRef.current = setTimeout(() => {
      if (triggerRef.current) {
        const rect = triggerRef.current.getBoundingClientRect()
        setCoords({
          top: rect.top + window.scrollY - 6,
          left: rect.left + window.scrollX + rect.width / 2,
        })
      }
      setVisible(true)
    }, delay)
  }

  function hide() {
    if (timerRef.current) clearTimeout(timerRef.current)
    setVisible(false)
  }

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  const trigger = React.cloneElement(children, {
    ref: triggerRef,
    onMouseEnter: show,
    onMouseLeave: hide,
    onFocus: show,
    onBlur: hide,
  })

  return (
    <>
      {trigger}
      {visible &&
        createPortal(
          <div
            role="tooltip"
            style={{ top: coords.top, left: coords.left }}
            className="pointer-events-none fixed z-[9999] -translate-x-1/2 -translate-y-full animate-fade-in"
          >
            <div className="bg-slate-800 text-white text-xs font-medium px-2 py-1 rounded-md shadow-lg whitespace-nowrap">
              {content}
            </div>
            <div className="mx-auto w-0 h-0 border-x-4 border-x-transparent border-t-4 border-t-slate-800" />
          </div>,
          document.body,
        )}
    </>
  )
}
