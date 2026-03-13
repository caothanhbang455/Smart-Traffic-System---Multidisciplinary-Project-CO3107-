import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import axios from 'axios'
import type { LightColor } from '../components/CameraCard'

type TrafficData = Record<
  string,
  {
    vehicles: number
    light: LightColor
    last_update: string
  }
>

type Status = 'loading' | 'connected' | 'offline'

function formatTime(d: Date) {
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  return `${hh}:${mm}:${ss}`
}

export function useTrafficApi({ baseUrl, pollMs }: { baseUrl: string; pollMs: number }) {
  const [data, setData] = useState<TrafficData | null>(null)
  const [status, setStatus] = useState<Status>('loading')
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null)
  const pollRef = useRef<number | null>(null)

  const api = useMemo(
    () =>
      axios.create({
        baseURL: baseUrl,
        timeout: 4000,
      }),
    [baseUrl],
  )

  const fetchTraffic = useCallback(async () => {
    try {
      const res = await api.get('/api/traffic')
      setData(res.data as TrafficData)
      setStatus('connected')
      setLastUpdatedAt(formatTime(new Date()))
    } catch {
      setStatus('offline')
      // keep last data for UI stability
    }
  }, [api])

  const changeLight = useCallback(
    async (intersection: string, light: LightColor) => {
      await api.post('/api/control', { intersection, light })
      await fetchTraffic()
    },
    [api, fetchTraffic],
  )

  useEffect(() => {
    const kickoff = window.setTimeout(() => {
      void fetchTraffic()
    }, 0)

    pollRef.current = window.setInterval(() => {
      void fetchTraffic()
    }, pollMs)
    return () => {
      window.clearTimeout(kickoff)
      if (pollRef.current) window.clearInterval(pollRef.current)
    }
  }, [fetchTraffic, pollMs])

  return { data, status, lastUpdatedAt, changeLight }
}

