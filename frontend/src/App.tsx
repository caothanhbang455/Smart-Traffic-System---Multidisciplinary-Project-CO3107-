import { useMemo, useState } from 'react'
import axios from 'axios'
import './App.css'
import { CameraCard, type CameraDirection } from './components/CameraCard'
import { Pill } from './components/Pill'
import { useTrafficApi } from './hooks/useTrafficApi'
import logo from './assets/logo.png'
import { SystemDashboardPage } from './pages/SystemDashboardPage'
import { ConfigPage } from './pages/ConfigPage'

type Page = 'dashboard' | 'system' | 'config'

const directions: CameraDirection[] = ['north', 'south', 'east', 'west']
const backendUrl = import.meta.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:5000'

// ==================== TYPES ====================

type VehicleBreakdown = {
  bicycle?: number
  motorcycle?: number
  car?: number
  bus?: number
  truck?: number
  [key: string]: number | undefined
}

type AiResults = {
  north: { vehicle_count: number; vehicle_breakdown: VehicleBreakdown; weighted_vehicle_score: number; density_ratio: number; annotated_image_base64?: string }
  south: { vehicle_count: number; vehicle_breakdown: VehicleBreakdown; weighted_vehicle_score: number; density_ratio: number; annotated_image_base64?: string }
  east:  { vehicle_count: number; vehicle_breakdown: VehicleBreakdown; weighted_vehicle_score: number; density_ratio: number; annotated_image_base64?: string }
  west:  { vehicle_count: number; vehicle_breakdown: VehicleBreakdown; weighted_vehicle_score: number; density_ratio: number; annotated_image_base64?: string }
}

type DecisionResult = {
  phase: 'NS' | 'EW'
  green_duration: number
  ai_results?: AiResults
  light_states?: {
    north: 'green' | 'red'
    south: 'green' | 'red'
    east: 'green' | 'red'
    west: 'green' | 'red'
  }
  details?: {
    NS: { color: 'green' | 'red'; duration: number }
    EW: { color: 'green' | 'red'; duration: number }
  }
}

type LogEntry = {
  t: string
  msg: string
}

// ==================== HELPERS ====================

function formatTime(d: Date) {
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  return `${hh}:${mm}:${ss}`
}

// ==================== COMPONENT ====================

function App() {
  const { data, status, lastUpdatedAt } = useTrafficApi({
    baseUrl: backendUrl,
    pollMs: 4000,
  })

  const [currentPage, setCurrentPage] = useState<Page>('dashboard')

  const sendManualControl = async (intersection_1: 'green' | 'red', intersection_2: 'green' | 'red') => {
    try {
      const res = await axios.post(`${backendUrl}/api/manual_control`, {
        override: true,
        intersection_1,
        intersection_2,
      })
      console.log('Manual control response:', res.data)
    } catch (error) {
      console.error('Manual control error:', error)
    }
  }

  const [decisionLog, setDecisionLog] = useState<LogEntry[]>([])

  const fallbackIntersections = useMemo(() => ({
    intersection_1: { vehicles: 12, light: 'green' as const, last_update: '—' },
    intersection_2: { vehicles: 7,  light: 'red'   as const, last_update: '—' },
  }), [])

  const intersections = useMemo(() => data ?? fallbackIntersections, [data, fallbackIntersections])

  const [cameraImages, setCameraImages] = useState<Record<CameraDirection, string | null>>({
    north: null, south: null, east: null, west: null,
  })
  const [cameraFiles, setCameraFiles] = useState<Record<CameraDirection, File | null>>({
    north: null, south: null, east: null, west: null,
  })

  const [decision, setDecision]                   = useState<DecisionResult | null>(null)
  const [isRunningDecision, setIsRunningDecision] = useState(false)
  const [decisionError, setDecisionError]         = useState<string | null>(null)

  // ==================== HANDLERS ====================

  const handleImageSelected = (direction: CameraDirection, file: File) => {
    const url = URL.createObjectURL(file)
    setCameraImages((prev) => {
      const existing = prev[direction]
      if (existing) URL.revokeObjectURL(existing)
      return { ...prev, [direction]: url }
    })
    setCameraFiles((prev) => ({ ...prev, [direction]: file }))
  }

  const handleRemoveImage = (direction: CameraDirection) => {
    setCameraImages((prev) => {
      const existing = prev[direction]
      if (existing) URL.revokeObjectURL(existing)
      return { ...prev, [direction]: null }
    })
    setCameraFiles((prev) => ({ ...prev, [direction]: null }))
    // Xóa bbox + ai_results của hướng này để ảnh bbox biến mất
    setDecision((prev) => {
      if (!prev?.ai_results) return prev
      const newAiResults = { ...prev.ai_results }
      delete newAiResults[direction]
      const hasAny = Object.keys(newAiResults).length > 0
      return hasAny
        ? { ...prev, ai_results: newAiResults as typeof prev.ai_results }
        : { ...prev, ai_results: undefined }
    })
  }

  const handleRunDecision = async () => {
    const missingDirections = directions.filter(dir => !cameraFiles[dir])
    if (missingDirections.length > 0) {
      setDecisionError(`Thiếu ảnh cho hướng: ${missingDirections.join(', ')}`)
      return
    }
    setIsRunningDecision(true)
    setDecisionError(null)
    try {
      const formData = new FormData()
      formData.append('north', cameraFiles.north!)
      formData.append('south', cameraFiles.south!)
      formData.append('east',  cameraFiles.east!)
      formData.append('west',  cameraFiles.west!)

      const res = await axios.post(`${backendUrl}/api/run_decision_with_images`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const payload = (res.data?.data ?? res.data) as DecisionResult
      setDecision(payload)

      const now         = formatTime(new Date())
      const winnerLabel = payload.phase === 'NS' ? 'NS' : 'EW'
      const loserLabel  = payload.phase === 'NS' ? 'EW' : 'NS'
      setDecisionLog(prev => [{
        t: now,
        msg: `${winnerLabel} GREEN ${payload.green_duration.toFixed(2)}s => ${loserLabel} RED ${payload.green_duration.toFixed(2)}s`,
      }, ...prev].slice(0, 10))

    } catch (error) {
      console.error(error)
      setDecisionError('Cannot call AI decision from backend.')
    } finally {
      setIsRunningDecision(false)
    }
  }

  // ==================== RENDER ====================

  return (
    <div className="st-app-layout">

      {/* ── Left nav sidebar ── */}
      <nav className="st-nav">
        <div className="st-nav__brand">
          <img src={logo} alt="logo" className="st-nav__brand-logo" />
          <span className="st-nav__brand-name">Smart Traffic</span>
        </div>

        <button
          type="button"
          className={`st-nav__item ${currentPage === 'dashboard' ? 'st-nav__item--active' : ''}`}
          onClick={() => setCurrentPage('dashboard')}
        >
          <svg className="st-nav__item-icon" viewBox="0 0 16 16" fill="currentColor">
            <rect x="1" y="1" width="6" height="6" rx="1"/>
            <rect x="9" y="1" width="6" height="6" rx="1"/>
            <rect x="1" y="9" width="6" height="6" rx="1"/>
            <rect x="9" y="9" width="6" height="6" rx="1"/>
          </svg>
          Intersection Dashboard
        </button>

        <button
          type="button"
          className={`st-nav__item ${currentPage === 'system' ? 'st-nav__item--active' : ''}`}
          onClick={() => setCurrentPage('system')}
        >
          <svg className="st-nav__item-icon" viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 1a7 7 0 100 14A7 7 0 008 1zm0 2a5 5 0 110 10A5 5 0 018 3zm0 2a1 1 0 00-1 1v2.586l-1.707 1.707a1 1 0 001.414 1.414L8.707 10A1 1 0 009 9.293V8a1 1 0 00-1-1z"/>
          </svg>
          System Dashboard
        </button>

        <button
          type="button"
          className={`st-nav__item ${currentPage === 'config' ? 'st-nav__item--active' : ''}`}
          onClick={() => setCurrentPage('config')}
        >
          <svg className="st-nav__item-icon" viewBox="0 0 16 16" fill="currentColor">
            <path d="M6.5 1a.5.5 0 000 1h.5v1.07A5 5 0 003 8a5 5 0 008 4v1a.5.5 0 001 0V8a5 5 0 00-4-4.9V2h.5a.5.5 0 000-1h-2zM8 4.5A3.5 3.5 0 118 11 3.5 3.5 0 018 4.5zm0 1a2.5 2.5 0 100 5 2.5 2.5 0 000-5zm0 1a1.5 1.5 0 110 3 1.5 1.5 0 010-3z"/>
          </svg>
          System Configuration
        </button>
      </nav>

      {/* ── Main content area ── */}
      <div className="st-content">
        {currentPage === 'system' ? (
          <SystemDashboardPage />
        ) : currentPage === 'config' ? (
          <ConfigPage />
        ) : (
          <div className="st-page">

            {/* ── Status bar ── */}
            <header style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '12px 20px',
              borderBottom: '1px solid rgba(255,255,255,0.07)',
            }}>
              <div>
                <div style={{ fontSize: 11, letterSpacing: '0.06em', color: 'rgba(255,255,255,0.4)', marginBottom: 2 }}>
                  OVERALL JUNCTION STATE
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="st-trafficlight" aria-hidden>
                    <span className="st-trafficlight__dot st-trafficlight__dot--red" />
                    <span className="st-trafficlight__dot st-trafficlight__dot--yellow" />
                    <span className="st-trafficlight__dot st-trafficlight__dot--green" />
                  </span>
                  <span style={{ fontSize: 13, fontWeight: 500, color: 'rgba(255,255,255,0.85)' }}>
                    AUTOMATIC MODE ACTIVE
                  </span>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <Pill tone={status === 'connected' ? 'success' : status === 'loading' ? 'info' : 'danger'}>
                  {status === 'connected' ? 'CONNECTED' : status === 'loading' ? 'CONNECTING' : 'OFFLINE'}
                </Pill>
                <span className="st-muted" style={{ fontSize: 12 }}>Last update: {lastUpdatedAt ?? '—'}</span>
                <Pill tone="neutral">Admin</Pill>
              </div>
            </header>

            <main className="st-main">
              <section className="st-grid">
                <div className="st-cameras">
                  {directions.map((dir) => (
                    <CameraCard
                      key={dir}
                      direction={dir}
                      traffic={intersections[dir === 'north' || dir === 'south' ? 'intersection_1' : 'intersection_2']}
                      imageUrl={cameraImages[dir]}
                      onImageSelected={(file) => handleImageSelected(dir, file)}
                      onRemoveImage={() => handleRemoveImage(dir)}
                      aiData={decision?.ai_results?.[dir] ?? null}
                      greenDuration={decision?.green_duration ?? null}
                      bboxImageUrl={
                        decision?.ai_results?.[dir]?.annotated_image_base64
                          ? 'data:image/jpeg;base64,' + decision.ai_results[dir].annotated_image_base64
                          : null
                      }
                    />
                  ))}
                </div>

                {/* ── Sidebar ── */}
                <aside className="st-sidebar" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>

                  {/* Panel 1: AI Decision Log */}
                  <div className="st-panel" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                    <div className="st-panel__header">
                      <div className="st-panel__title">AI DECISION LOG</div>
                      <button type="button" className="st-btn st-btn--ghost"
                        onClick={handleRunDecision}
                        disabled={isRunningDecision || status === 'loading'}>
                        {isRunningDecision ? 'RUNNING...' : 'RUN'}
                      </button>
                    </div>

                    {decision && (
                      <p className="st-decision">
                        Next green phase:{' '}
                        <strong>{decision.phase === 'NS' ? 'NORTH & SOUTH' : 'EAST & WEST'}</strong> for{' '}
                        <strong>{decision.green_duration.toFixed(2)}s</strong>.{' '}
                        {decision.light_states && (
                          <span>
                            Lights — N: {decision.light_states.north}, S: {decision.light_states.south},{' '}
                            E: {decision.light_states.east}, W: {decision.light_states.west}.
                          </span>
                        )}
                      </p>
                    )}

                    {decisionError && <p className="st-error">{decisionError}</p>}

                    <div className="st-log" style={{ flex: 1 }}>
                      {decisionLog.length === 0 ? (
                        <div className="st-log__row">
                          <div className="st-log__msg" style={{ color: 'rgba(255,255,255,0.4)' }}>
                            No decisions yet - upload 4 images and press RUN
                          </div>
                        </div>
                      ) : (
                        decisionLog.map((x, i) => (
                          <div className="st-log__row" key={i}>
                            <div className="st-log__msg">{x.msg}</div>
                            <div className="st-log__time">{x.t}</div>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  {/* Panel 2: Manual Override */}
                  <ManualOverridePanel onSendControl={sendManualControl} />

                </aside>
              </section>
            </main>

          </div>
        )}
      </div>
    </div>
  )
}

export default App

// ── ManualOverridePanel ──
function ManualOverridePanel({
  onSendControl,
}: {
  onSendControl: (i1: 'green' | 'red', i2: 'green' | 'red') => Promise<void>
}) {
  const [enabled, setEnabled]         = useState(false)
  const [activePhase, setActivePhase] = useState<'NS' | 'EW' | null>(null)
  const [sending, setSending]         = useState(false)

  async function handleSelect(phase: 'NS' | 'EW') {
    if (!enabled || sending) return
    setSending(true)
    setActivePhase(phase)
    try {
      if (phase === 'NS') await onSendControl('green', 'red')
      else                await onSendControl('red', 'green')
    } catch (e) { console.error(e) }
    finally { setSending(false) }
  }

  const lights = {
    north: activePhase === 'NS' ? 'green' : activePhase === 'EW' ? 'red' : null,
    south: activePhase === 'NS' ? 'green' : activePhase === 'EW' ? 'red' : null,
    east:  activePhase === 'EW' ? 'green' : activePhase === 'NS' ? 'red' : null,
    west:  activePhase === 'EW' ? 'green' : activePhase === 'NS' ? 'red' : null,
  }

  return (
    <div className="st-panel">
      <div className="st-panel__header">
        <div className="st-panel__title">MANUAL OVERRIDE</div>
        <button
          type="button"
          className="st-btn st-btn--ghost"
          onClick={() => { setEnabled(v => !v); if (enabled) setActivePhase(null) }}
          style={{
            borderColor: enabled ? 'rgba(34,197,94,0.6)' : undefined,
            color: enabled ? '#22c55e' : undefined,
            background: enabled ? 'rgba(34,197,94,0.1)' : undefined,
          }}
        >
          {enabled ? 'ON' : 'OFF'}
        </button>
      </div>

      {enabled && (
        <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', width: 36, flexShrink: 0 }}>N / S</span>
            <PhaseBtn label="GREEN" active={activePhase === 'NS'} color="green" disabled={sending} onClick={() => handleSelect('NS')} />
            <PhaseBtn label="RED"   active={activePhase === 'EW'} color="red"   disabled={sending} onClick={() => handleSelect('EW')} />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', width: 36, flexShrink: 0 }}>E / W</span>
            <PhaseBtn label="GREEN" active={activePhase === 'EW'} color="green" disabled={sending} onClick={() => handleSelect('EW')} />
            <PhaseBtn label="RED"   active={activePhase === 'NS'} color="red"   disabled={sending} onClick={() => handleSelect('NS')} />
          </div>
          {activePhase && (
            <div style={{ display: 'flex', gap: 8, marginTop: 4, justifyContent: 'center' }}>
              {(['north', 'south', 'east', 'west'] as const).map(dir => (
                <div key={dir} style={{ textAlign: 'center' }}>
                  <div style={{
                    width: 8, height: 8, borderRadius: '50%', margin: '0 auto 3px',
                    background: lights[dir] === 'green' ? '#22c55e' : '#ef4444',
                  }}/>
                  <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.35)' }}>
                    {dir[0].toUpperCase()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── PhaseBtn ──
function PhaseBtn({
  label, active, color, disabled, onClick,
}: { label: string; active: boolean; color: 'green' | 'red'; disabled: boolean; onClick: () => void }) {
  const isGreen = color === 'green'
  const ac  = isGreen ? '#22c55e' : '#ef4444'
  const abg = isGreen ? 'rgba(34,197,94,0.18)' : 'rgba(239,68,68,0.18)'
  const ab  = isGreen ? 'rgba(34,197,94,0.5)'  : 'rgba(239,68,68,0.5)'
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        flex: 1, height: 30, borderRadius: 6,
        border: `1px solid ${active ? ab : 'rgba(255,255,255,0.08)'}`,
        background: active ? abg : 'rgba(255,255,255,0.03)',
        color: active ? ac : disabled ? 'rgba(255,255,255,0.18)' : 'rgba(255,255,255,0.4)',
        fontSize: 11, fontWeight: 500, letterSpacing: '0.05em',
        cursor: disabled ? 'not-allowed' : 'pointer',
        transition: 'all 0.15s',
        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4,
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: active ? ac : 'rgba(255,255,255,0.15)' }}/>
      {label}
    </button>
  )
}