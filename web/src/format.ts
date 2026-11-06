import type { Company, ExcludedKpi, Kpi, Status } from './api'

export const STATUS_ORDER: Status[] = ['achieved', 'on_track', 'delayed', 'unverifiable']

const MARKET_LABELS: Record<Company['market'], string> = {
  KOSPI: '코스피',
  KOSDAQ: '코스닥',
}

export function marketLabel(market: Company['market']): string {
  return MARKET_LABELS[market]
}

export function companyName(corpName: string): string {
  return corpName.replace(/\(주\)|㈜/g, '').trim()
}

export function formatMonth(compactDate: string): string {
  return `${compactDate.slice(0, 4)}.${compactDate.slice(4, 6)}`
}

export function formatDay(compactDate: string): string {
  return `${formatMonth(compactDate)}.${compactDate.slice(6, 8)}`
}

export function displayQuote(quote: string): string {
  return quote.replace(/^[-*→○●ㅇ\s]+/, '')
}

export function deadlineYear(deadline: string): string {
  return deadline.slice(0, 4)
}

function formatValue(value: number, unit: string): string {
  const number = value.toLocaleString('ko-KR', { maximumFractionDigits: 2 })
  return `${number}${unit}`
}

export function formatActual(kpi: Kpi): string | null {
  if (kpi.actual_value === null || kpi.actual_unit === null) return null
  return formatValue(kpi.actual_value, kpi.actual_unit)
}

export function formatTarget(kpi: ExcludedKpi): string {
  const { target_min: min, target_max: max, unit } = kpi
  if (min !== null && max !== null) {
    if (min === max) return formatValue(min, unit)
    return `${min.toLocaleString('ko-KR')}~${formatValue(max, unit)}`
  }
  if (min !== null) return `${formatValue(min, unit)} 이상`
  return `${formatValue(max ?? 0, unit)} 이하`
}
