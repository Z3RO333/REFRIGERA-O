import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'

export function useWebSocket() {
  const ws = useRef<WebSocket | null>(null)
  const queryClient = useQueryClient()
  const reconnectTimeout = useRef<number | null>(null)

  useEffect(() => {
    let mounted = true

    function connect() {
      if (!mounted) return

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const socket = new WebSocket(`${protocol}//${window.location.host}/ws/updates`)
      ws.current = socket

      socket.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.channel === 'device.reading.new') {
            queryClient.invalidateQueries({ queryKey: ['kpis'] })
            queryClient.invalidateQueries({ queryKey: ['store-devices'] })
          }
          if (msg.channel === 'alert.created' || msg.channel === 'alert.resolved') {
            queryClient.invalidateQueries({ queryKey: ['alerts'] })
            queryClient.invalidateQueries({ queryKey: ['kpis'] })
          }
        } catch {}
      }

      socket.onclose = () => {
        if (mounted) {
          reconnectTimeout.current = window.setTimeout(connect, 5000)
        }
      }

      socket.onerror = () => {
        socket.close()
      }
    }

    connect()

    return () => {
      mounted = false
      if (reconnectTimeout.current) clearTimeout(reconnectTimeout.current)
      ws.current?.close()
    }
  }, [queryClient])
}
