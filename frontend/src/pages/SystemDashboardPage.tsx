import { useEffect, useState } from 'react'
import axios from 'axios'
import { useSensorData } from '../hooks/useSensorData'

const backendUrl = import.meta.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:5000'

type TrafficData = {
  intersection_1: { vehicles: number; light: 'green' | 'red' | 'yellow'; last_update: string }
  intersection_2: { vehicles: number; light: 'green' | 'red' | 'yellow'; last_update: string }
}

function useTrafficStatus(pollMs = 3000) {
  const [data, setData] = useState<TrafficData | null>(null)
  useEffect(() => {
    let mounted = true
    const load = async () => {
      try {
        const res = await axios.get(`${backendUrl}/api/traffic`)
        if (mounted) setData(res.data as TrafficData)
      } catch { /* silent */ }
    }
    void load()
    const timer = setInterval(() => { void load() }, pollMs)
    return () => { mounted = false; clearInterval(timer) }
  }, [pollMs])
  return data
}

function LightDot({ color }: { color: 'green' | 'red' | 'yellow' }) {
  const bg = color === 'green' ? '#22c55e' : color === 'red' ? '#ef4444' : '#f59e0b'
  return (
    <span style={{
      display: 'inline-block',
      width: 10, height: 10, borderRadius: '50%',
      background: bg,
      boxShadow: `0 0 6px ${bg}99`,
      flexShrink: 0,
    }}/>
  )
}

function StatCard({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div style={{
      background: 'rgba(255,255,255,0.04)',
      border: '1px solid rgba(255,255,255,0.08)',
      borderRadius: 10,
      padding: '14px 18px',
    }}>
      <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: '0.05em', marginBottom: 6 }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 600, color: color ?? '#fff', lineHeight: 1 }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)', marginTop: 4 }}>{sub}</div>
      )}
    </div>
  )
}

function SectionCard({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div style={{
      background: 'rgba(255,255,255,0.04)',
      border: '1px solid rgba(255,255,255,0.08)',
      borderRadius: 12,
      overflow: 'hidden',
      marginBottom: 16,
    }}>
      <div style={{
        padding: '12px 20px',
        borderBottom: '1px solid rgba(255,255,255,0.07)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <span style={{ fontSize: 12, fontWeight: 500, letterSpacing: '0.05em', color: 'rgba(255,255,255,0.6)' }}>
          {title}
        </span>
        <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)' }}>{subtitle}</span>
      </div>
      <div style={{ padding: '16px 20px' }}>
        {children}
      </div>
    </div>
  )
}

export function SystemDashboardPage() {
  const traffic = useTrafficStatus(3000)
  const { items, loading, error } = useSensorData({ limit: 20, pollMs: 5000 })

  const latestSensor  = items[0] ?? null
  const phase         = traffic
    ? (traffic.intersection_1.light === 'green' ? 'NS' : 'EW')
    : null
  const totalVehicles = traffic
    ? traffic.intersection_1.vehicles + traffic.intersection_2.vehicles
    : null

  return (
    <div style={{ padding: '28px 32px', maxWidth: 960 }}>

      {/* Page header */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: 20, fontWeight: 500, color: 'rgba(255,255,255,0.92)', margin: 0, marginBottom: 4 }}>
          System Dashboard
        </h2>
        <p style={{ fontSize: 13, color: 'rgba(255,255,255,0.4)', margin: 0 }}>
          Monitor real-time traffic conditions and system status.
        </p>
      </div>

      {/* -- Card 1: Signal Status -- */}
      <SectionCard title="SIGNAL STATUS" subtitle="Current phase and light states · auto-refresh every 3s">
        {!traffic ? (
          <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.35)' }}>Connecting to backend...</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

            {/* Active phase banner */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '12px 16px',
              background: phase === 'NS' ? 'rgba(34,197,94,0.08)' : 'rgba(77,171,255,0.08)',
              border: `1px solid ${phase === 'NS' ? 'rgba(34,197,94,0.2)' : 'rgba(77,171,255,0.2)'}`,
              borderRadius: 8,
            }}>
              <div style={{
                width: 36, height: 36, borderRadius: '50%',
                background: phase === 'NS' ? 'rgba(34,197,94,0.15)' : 'rgba(77,171,255,0.15)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 13, fontWeight: 600,
                color: phase === 'NS' ? '#22c55e' : '#4dabff',
                flexShrink: 0,
              }}>
                {phase}
              </div>
              <div>
                <div style={{ fontSize: 13, fontWeight: 500, color: 'rgba(255,255,255,0.85)' }}>
                  {phase === 'NS' ? 'North & South' : 'East & West'} - GREEN phase active
                </div>
                <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)', marginTop: 2 }}>
                  Last updated: {traffic.intersection_1.last_update || '-'}
                </div>
              </div>
            </div>

            {/* Per-direction light grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
              {([
                { label: 'North', light: traffic.intersection_1.light },
                { label: 'South', light: traffic.intersection_1.light },
                { label: 'East',  light: traffic.intersection_2.light },
                { label: 'West',  light: traffic.intersection_2.light },
              ] as const).map(({ label, light }) => (
                <div key={label} style={{
                  textAlign: 'center', padding: '12px 0',
                  background: 'rgba(255,255,255,0.03)',
                  borderRadius: 8,
                  border: '1px solid rgba(255,255,255,0.06)',
                }}>
                  <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', marginBottom: 8, letterSpacing: '0.04em' }}>
                    {label.toUpperCase()}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'center' }}>
                    <LightDot color={light} />
                  </div>
                  <div style={{
                    fontSize: 11, fontWeight: 500, marginTop: 6, letterSpacing: '0.05em',
                    color: light === 'green' ? '#22c55e' : '#ef4444',
                  }}>
                    {light.toUpperCase()}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </SectionCard>

      {/* - Card 2: Traffic Summary - */}
      <SectionCard title="TRAFFIC SUMMARY" subtitle="Vehicle counts from API · auto-refresh every 3s">
        {!traffic ? (
          <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.35)' }}>Waiting for data...</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
              <StatCard
                label="TOTAL VEHICLES"
                value={totalVehicles ?? '—'}
                sub="All 4 directions"
              />
              <StatCard
                label="NORTH / SOUTH"
                value={traffic.intersection_1.vehicles}
                sub={`Signal: ${traffic.intersection_1.light.toUpperCase()}`}
                color={traffic.intersection_1.light === 'green' ? '#22c55e' : '#ef4444'}
              />
              <StatCard
                label="EAST / WEST"
                value={traffic.intersection_2.vehicles}
                sub={`Signal: ${traffic.intersection_2.light.toUpperCase()}`}
                color={traffic.intersection_2.light === 'green' ? '#22c55e' : '#ef4444'}
              />
            </div>

            {/* Environmental data from latest sensor reading */}
            {latestSensor && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
                <StatCard
                  label="LIGHT INTENSITY"
                  value={`${latestSensor.light_intensity.toFixed(1)} lux`}
                  sub={latestSensor.light_intensity < 50 ? 'Low light condition' : 'Normal light condition'}
                  color="#f59e0b"
                />
                <StatCard
                  label="TEMPERATURE"
                  value={`${latestSensor.temperature.toFixed(1)} °C`}
                  sub={latestSensor.temperature > 35 ? 'High temperature' : 'Normal temperature'}
                  color="#4dabff"
                />
              </div>
            )}
          </div>
        )}
      </SectionCard>

      {/* ── Card 3: Sensor History ── */}
      <SectionCard title="SENSOR HISTORY" subtitle="Latest 20 records · auto-refresh every 5s">
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: 'rgba(255,255,255,0.03)' }}>
                {['Timestamp', 'Light intensity (lux)', 'Temperature (°C)', 'Source'].map(h => (
                  <th key={h} style={{
                    padding: '10px 20px', textAlign: 'left',
                    fontSize: 11, fontWeight: 500, letterSpacing: '0.04em',
                    color: 'rgba(255,255,255,0.4)',
                    borderBottom: '1px solid rgba(255,255,255,0.07)',
                  }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={4} style={{ padding: 20, textAlign: 'center', color: 'rgba(255,255,255,0.3)' }}>Loading...</td></tr>
              )}
              {error && (
                <tr><td colSpan={4} style={{ padding: 20, textAlign: 'center', color: '#ef4444' }}>{error}</td></tr>
              )}
              {!loading && !error && items.length === 0 && (
                <tr><td colSpan={4} style={{ padding: 20, textAlign: 'center', color: 'rgba(255,255,255,0.3)' }}>No sensor records yet.</td></tr>
              )}
              {!loading && !error && items.map((s, i) => (
                <tr key={s.id} style={{
                  background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)',
                  borderBottom: '1px solid rgba(255,255,255,0.04)',
                }}>
                  <td style={{ padding: '10px 20px', color: 'rgba(255,255,255,0.55)', fontVariantNumeric: 'tabular-nums' }}>
                    {s.created_at
                      ? new Date(s.created_at).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh', hour12: false })
                      : '—'}
                  </td>
                  <td style={{ padding: '10px 20px', color: '#f59e0b', fontVariantNumeric: 'tabular-nums' }}>
                    {s.light_intensity.toFixed(1)}
                  </td>
                  <td style={{ padding: '10px 20px', color: '#4dabff', fontVariantNumeric: 'tabular-nums' }}>
                    {s.temperature.toFixed(1)}
                  </td>
                  <td style={{ padding: '10px 20px' }}>
                    <span style={{
                      fontSize: 11, padding: '2px 8px', borderRadius: 4,
                      background: s.source.includes('fallback') ? 'rgba(239,68,68,0.1)' : 'rgba(34,197,94,0.1)',
                      color: s.source.includes('fallback') ? '#ef4444' : '#22c55e',
                      border: `1px solid ${s.source.includes('fallback') ? 'rgba(239,68,68,0.2)' : 'rgba(34,197,94,0.2)'}`,
                    }}>
                      {s.source.includes('fallback') ? 'fallback' : 'iot'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

    </div>
  )
}