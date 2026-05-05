import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer } from 'recharts'
import { format, parseISO } from 'date-fns'
import { ptBR } from 'date-fns/locale'
import type { HistoryPoint } from '../../types'

interface Props {
  data: HistoryPoint[]
  setpoint?: number
}

export default function TemperatureChart({ data, setpoint }: Props) {
  const chartData = data.map(d => ({
    time: d.time,
    temp: d.temperature,
    label: format(parseISO(d.time), 'HH:mm', { locale: ptBR }),
  }))

  return (
    <ResponsiveContainer width="100%" height={250}>
      <LineChart data={chartData} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
        <XAxis dataKey="label" tick={{ fill: '#9ca3af', fontSize: 11 }} interval="preserveStartEnd" />
        <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} domain={['auto', 'auto']} unit="°C" />
        <Tooltip
          contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: '8px', color: '#f9fafb' }}
          formatter={(value: number) => [`${value?.toFixed(1)}°C`, 'Temperatura']}
        />
        {setpoint && (
          <ReferenceLine y={setpoint} stroke="#3b82f6" strokeDasharray="6 3" label={{ value: `SP ${setpoint}°C`, fill: '#60a5fa', fontSize: 11, position: 'right' }} />
        )}
        <Line type="monotone" dataKey="temp" stroke="#ef4444" dot={false} strokeWidth={2} name="Temperatura" />
      </LineChart>
    </ResponsiveContainer>
  )
}
