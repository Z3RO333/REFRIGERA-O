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
          const msg = JSON.parse(event.data) as { channel: string; data: Record<string, unknown> }
          const ch = msg.channel

          if (ch === 'device.reading.new') {
            queryClient.invalidateQueries({ queryKey: ['kpis'] })
            queryClient.invalidateQueries({ queryKey: ['store-devices'] })
            queryClient.invalidateQueries({ queryKey: ['digital-twin'] })
          }

          if (ch === 'alert.created' || ch === 'alert.resolved') {
            queryClient.invalidateQueries({ queryKey: ['alerts'] })
            queryClient.invalidateQueries({ queryKey: ['kpis'] })
          }

          if (ch === 'zone.automation.mode.changed' || ch === 'zone.action.created') {
            queryClient.invalidateQueries({ queryKey: ['zones-automation'] })
            queryClient.invalidateQueries({ queryKey: ['zone-history'] })
            queryClient.invalidateQueries({ queryKey: ['digital-twin'] })
          }

          if (ch === 'ai.analysis.created') {
            queryClient.invalidateQueries({ queryKey: ['ai-analyses'] })
          }

          if (ch === 'zone.ai_analysis.created') {
            queryClient.invalidateQueries({ queryKey: ['ai-zone-analyses'] })
          }

          if (ch === 'automation.kill_switch.changed') {
            queryClient.invalidateQueries({ queryKey: ['automation-status'] })
            queryClient.invalidateQueries({ queryKey: ['zones-automation'] })
          }

          if (ch === 'device.command.sent' || ch === 'device.command.failed') {
            queryClient.invalidateQueries({ queryKey: ['store-devices'] })
            queryClient.invalidateQueries({ queryKey: ['device'] })
            queryClient.invalidateQueries({ queryKey: ['digital-twin'] })
            queryClient.invalidateQueries({ queryKey: ['zones-automation'] })
            queryClient.invalidateQueries({ queryKey: ['kpis'] })
            queryClient.invalidateQueries({ queryKey: ['automation-status'] })
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
