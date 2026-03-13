import { useMemo, useState } from 'react'
import axios from 'axios'
import './App.css'
import { CameraCard, type CameraDirection } from './components/CameraCard'
import { DonutChart } from './components/DonutChart'
import { Pill } from './components/Pill'
import { useTrafficApi } from './hooks/useTrafficApi'

const directions: CameraDirection[] = ['north', 'south', 'east', 'west']
const backendUrl = import.meta.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:5000'

type DecisionResult = {
  phase: 'NS' | 'EW'
  green_duration: number
  details?: {
    NS: { color: 'green' | 'red'; duration: number }
    EW: { color: 'green' | 'red'; duration: number }
  }
}

function App() {
  const { data, status, lastUpdatedAt, changeLight } = useTrafficApi({
    baseUrl: backendUrl,
    pollMs: 4000,
  })

  const [overrideAutomatic, setOverrideAutomatic] = useState(false)
  const [activeIntersection, setActiveIntersection] = useState<'intersection_1' | 'intersection_2'>('intersection_1')

  const fallbackIntersections = useMemo(
    () => ({
      intersection_1: { vehicles: 12, light: 'green' as const, last_update: '—' },
      intersection_2: { vehicles: 7, light: 'red' as const, last_update: '—' },
    }),
    [],
  )

  const intersections = useMemo(() => data ?? fallbackIntersections, [data, fallbackIntersections])

  const [cameraImages, setCameraImages] = useState<Record<CameraDirection, string | null>>({
    north: null,
    south: null,
    east: null,
    west: null,
  })
  const [cameraFiles, setCameraFiles] = useState<Record<CameraDirection, File | null>>({
    north: null,
    south: null,
    east: null,
    west: null,
  })
  const [decision, setDecision] = useState<DecisionResult | null>(null)
  const [isRunningDecision, setIsRunningDecision] = useState(false)
  const [decisionError, setDecisionError] = useState<string | null>(null)

  const totals = useMemo(() => {
    const vehicles1 = intersections.intersection_1?.vehicles ?? 0
    const vehicles2 = intersections.intersection_2?.vehicles ?? 0
    const total = vehicles1 + vehicles2
    return { vehicles1, vehicles2, total }
  }, [intersections])

  const composition = useMemo(() => {
    // Mock composition. Replace with real model output when available.
    const cars = Math.max(1, Math.round(totals.total * 0.58))
    const trucks = Math.max(0, Math.round(totals.total * 0.22))
    const buses = Math.max(0, Math.round(totals.total * 0.11))
    const bikes = Math.max(0, totals.total - cars - trucks - buses)
    return [
      { label: 'Cars', value: cars, color: '#4dabff' },
      { label: 'Trucks', value: trucks, color: '#f59e0b' },
      { label: 'Buses', value: buses, color: '#ef4444' },
      { label: 'Bikes', value: bikes, color: '#22c55e' },
    ]
  }, [totals.total])

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
  }

  const handleRunDecision = async () => {
    // Kiểm tra có đủ 4 ảnh không
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
      formData.append('east', cameraFiles.east!)
      formData.append('west', cameraFiles.west!)

      const res = await axios.post(`${backendUrl}/api/run_decision_with_images`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })
      const payload = (res.data?.data ?? res.data) as DecisionResult
      setDecision(payload)
    } catch (error) {
      console.error(error)
      setDecisionError('Không gọi được AI decision từ backend.')
    } finally {
      setIsRunningDecision(false)
    }
  }

  return (
    <div className="st-page">
      <header className="st-topbar">
        <div className="st-topbar__left">
          <div className="st-appmark">
            <div className="st-appmark__logo" aria-hidden />
            <div className="st-appmark__text">
              <div className="st-appmark__title">SMART TRAFFIC LIGHT CONTROL SYSTEM</div>
              <div className="st-appmark__subtitle">INTERSECTION DASHBOARD</div>
            </div>
          </div>
        </div>

        <div className="st-topbar__center">
          <div className="st-status">
            <div className="st-status__block">
              <div className="st-status__label">TRAFFIC DENSITY</div>
              <div className="st-status__value">{Math.min(99, Math.round((totals.total / 40) * 100))}%</div>
              <div className="st-meter">
                <div className="st-meter__bar" style={{ width: `${Math.min(100, (totals.total / 40) * 100)}%` }} />
              </div>
              <div className="st-status__hint">CURRENT GREEN TIME: 45s</div>
            </div>

            <div className="st-status__block st-status__block--wide">
              <div className="st-status__label">OVERALL JUNCTION STATE</div>
              <div className="st-status__headline">
                <span className="st-trafficlight" aria-hidden>
                  <span className="st-trafficlight__dot st-trafficlight__dot--red" />
                  <span className="st-trafficlight__dot st-trafficlight__dot--yellow" />
                  <span className="st-trafficlight__dot st-trafficlight__dot--green" />
                </span>
                <span className="st-status__mode">AUTOMATIC MODE ACTIVE</span>
              </div>
              <div className="st-status__sub">
                <Pill tone={status === 'connected' ? 'success' : status === 'loading' ? 'info' : 'danger'}>
                  {status === 'connected' ? 'CONNECTED' : status === 'loading' ? 'CONNECTING' : 'OFFLINE'}
                </Pill>
                <span className="st-dotsep" />
                <span className="st-muted">
                  Last update: {lastUpdatedAt ?? '—'}
                </span>
              </div>
            </div>

            <div className="st-status__block st-status__map" aria-label="Mini map panel">
              <div className="st-map" aria-hidden />
              {/* map overlay removed */}
            </div>
          </div>
        </div>

        <div className="st-topbar__right">
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
              />
            ))}
          </div>

          <aside className="st-sidebar">
            <div className="st-panel">
              <div className="st-panel__title">CONFIGURATION</div>

              <div className="st-accordion">
                <div className="st-accordion__item">
                  <div className="st-accordion__head">AI THRESHOLDS</div>
                  <div className="st-accordion__body st-muted">
                    Tune detection thresholds to reduce false positives and stabilize decisions.
                  </div>
                </div>
                <div className="st-accordion__item">
                  <div className="st-accordion__head">TIMING RULES</div>
                  <div className="st-accordion__body st-muted">
                    Base green time and max change constraints for anti-oscillation control.
                  </div>
                </div>
                <div className="st-accordion__item">
                  <div className="st-accordion__head">DATASET MANAGEMENT</div>
                  <div className="st-accordion__body st-muted">
                    Manage dataset annotations and model versions used for inference.
                  </div>
                </div>
              </div>
            </div>

            <div className="st-panel">
              <div className="st-panel__title">MANUAL CONTROL</div>

              <div className="st-formrow">
                <label className="st-label" htmlFor="intersectionSelect">
                  Intersection
                </label>
                <select
                  id="intersectionSelect"
                  className="st-select"
                  value={activeIntersection}
                  onChange={(e) => setActiveIntersection(e.target.value as 'intersection_1' | 'intersection_2')}
                >
                  <option value="intersection_1">Intersection 1 (North/South)</option>
                  <option value="intersection_2">Intersection 2 (East/West)</option>
                </select>
              </div>

              <div className="st-controlgrid">
                <button
                  className="st-btn st-btn--green"
                  onClick={() => changeLight(activeIntersection, 'green')}
                  disabled={!overrideAutomatic}
                >
                  NORTH/EAST GREEN
                </button>
                <button
                  className="st-btn st-btn--yellow"
                  onClick={() => changeLight(activeIntersection, 'yellow')}
                  disabled={!overrideAutomatic}
                >
                  YELLOW
                </button>
                <button
                  className="st-btn st-btn--red"
                  onClick={() => changeLight(activeIntersection, 'red')}
                  disabled={!overrideAutomatic}
                >
                  SOUTH/WEST RED
                </button>
              </div>

              <div className="st-toggleRow">
                <div>
                  <div className="st-label">OVERRIDE AUTOMATIC</div>
                  <div className="st-muted" style={{ fontSize: 12 }}>
                    Enable manual light control for the selected intersection.
                  </div>
                </div>
                <button
                  className={`st-toggle ${overrideAutomatic ? 'st-toggle--on' : ''}`}
                  onClick={() => setOverrideAutomatic((v) => !v)}
                  aria-pressed={overrideAutomatic}
                >
                  <span className="st-toggle__knob" />
                </button>
              </div>
            </div>
          </aside>
        </section>

        <section className="st-bottom">
          <div className="st-panel">
            <div className="st-panel__title">SYSTEM OVERVIEW</div>
            <div className="st-metrics">
              <div className="st-metric">
                <div className="st-metric__label">AVERAGE WAIT TIME</div>
                <div className="st-metric__value">
                  {Math.max(8, Math.round(38 - totals.total * 0.7))}s <span className="st-metric__trend">trend up</span>
                </div>
              </div>
              <div className="st-metric">
                <div className="st-metric__label">TRAFFIC FLOW</div>
                <div className="st-metric__value st-metric__value--good">OPTIMAL</div>
              </div>
              <div className="st-metric">
                <div className="st-metric__label">ACTIVE VEHICLES</div>
                <div className="st-metric__value">{totals.total}</div>
              </div>
            </div>
          </div>

          <div className="st-panel">
            <div className="st-panel__title">TRAFFIC COMPOSITION</div>
            <div className="st-composition">
              <DonutChart items={composition} />
            </div>
          </div>

          <div className="st-panel">
            <div className="st-panel__header">
              <div className="st-panel__title">AI DECISION LOG</div>
              <button
                type="button"
                className="st-btn st-btn--ghost"
                onClick={handleRunDecision}
                disabled={isRunningDecision || status === 'loading'}
              >
                {isRunningDecision ? 'RUNNING...' : 'RUN'}
              </button>
            </div>
            {decision && (
              <p className="st-decision">
                Next green phase:{' '}
                <strong>{decision.phase === 'NS' ? 'NORTH & SOUTH' : 'EAST & WEST'}</strong> for{' '}
                <strong>{decision.green_duration.toFixed(2)}s</strong>. Other directions stay red for the same time.
              </p>
            )}
            {decisionError && <p className="st-error">{decisionError}</p>}
            <div className="st-log">
              {[
                { t: '10:38 AM', msg: 'VEHICLE DETECTED: Lane NS (+3)' },
                { t: '10:38 AM', msg: 'ADJUST GREEN TIME: 45s → 50s' },
                { t: '11:33 PM', msg: 'VEHICLE DETECTED: Lane EW (+1)' },
              ].map((x, i) => (
                <div className="st-log__row" key={i}>
                  <div className="st-log__msg">{x.msg}</div>
                  <div className="st-log__time">{x.t}</div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </main>
    </div>
  )
}

export default App