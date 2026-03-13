import type { ReactNode } from 'react'

export type PillTone = 'success' | 'danger' | 'info' | 'neutral'

export function Pill({ children, tone }: { children: ReactNode; tone: PillTone }) {
  return <span className={`st-pill st-pill--${tone}`}>{children}</span>
}

