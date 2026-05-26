import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import type { KPISummary } from '../../types'
import { STATUS_CONFIG } from '../../lib/utils'

interface Props {
  kpis: KPISummary
}

export default function StatusDonut({ kpis }: Props) {
  const data = [
    { name: 'Normal', value: kpis.devices_normal, color: STATUS_CONFIG.NORMAL.color },
    { name: 'Atenção', value: kpis.devices_warning, color: STATUS_CONFIG.ATENÇÃO.color },
    { name: 'Crítico', value: kpis.devices_critical, color: STATUS_CONFIG.CRÍTICO.color },
    { name: 'Baixa Efic.', value: kpis.devices_low_efficiency, color: STATUS_CONFIG.BAIXA_EFICIÊNCIA.color },
    { name: 'Sem Leitura', value: kpis.devices_no_reading, color: STATUS_CONFIG.SEM_LEITURA.color },
    { name: 'Defasada', value: kpis.devices_stale ?? 0, color: STATUS_CONFIG.LEITURA_STALE.color },
    { name: 'Desligado', value: kpis.devices_off, color: STATUS_CONFIG.DESLIGADO.color },
  ].filter(d => d.value > 0)

  return (
    <ResponsiveContainer width="100%" height={220}>
      <PieChart>
        <Pie data={data} cx="50%" cy="50%" innerRadius={55} outerRadius={80} paddingAngle={2} dataKey="value">
          {data.map((entry, i) => <Cell key={i} fill={entry.color} />)}
        </Pie>
        <Tooltip
          contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: '8px', color: '#f9fafb' }}
        />
        <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: '12px', color: '#9ca3af' }} />
      </PieChart>
    </ResponsiveContainer>
  )
}
