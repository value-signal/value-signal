import type { Status } from '../api'

const STATUS_LABELS: Record<Status, string> = {
  achieved: '달성',
  on_track: '진행 중',
  delayed: '주의',
  unverifiable: '확인 불가',
}

type Props = {
  status: Status | null
  count?: number
}

export function StatusChip({ status, count }: Props) {
  const label = status ? STATUS_LABELS[status] : '실적 대기'
  return (
    <span className={`chip chip-${status ?? 'waiting'}`}>
      {label}
      {count !== undefined && ` ${count}`}
    </span>
  )
}
