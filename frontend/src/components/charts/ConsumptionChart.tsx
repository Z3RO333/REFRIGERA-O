import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { format, parseISO } from 'date-fns'
import { ptBR } from 'date-fns/locale'
import type { HistoryPoint } from '../../types'

interface Props {
  data: HistoryPoint[]
}

export default function ConsumptionChart({ data }: Props) {
  const chartData = data.map(d => ({
    time: d.time,
    kw: d.consumption_estimated_kw ?? d.consumption_estimated,
    label: format(parseISO(d.time), 'HH:mm', { locale: ptBR }),
  }))

  return (
    <ResponsiveContainer width="100%" height={230}>
      <AreaChart data={chartData} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
        <XAxis dataKey="label" tick={{ fill: '#9ca3af', fontSize: 11 }} interval="preserveStartEnd" />
        <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} unit=" kW" />
        <Tooltip
          contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: '8px', color: '#f9fafb' }}
          formatter={(value: number) => [`${value?.toFixed(1)} kW`, 'Potência estimada']}
        />
        <Area type="monotone" dataKey="kw" stroke="#0ea5e9" fill="#0ea5e9" fillOpacity={0.18} strokeWidth={2} dot={false} name="Potência estimada" />
      </AreaChart>
    </ResponsiveContainer>
  )
}
