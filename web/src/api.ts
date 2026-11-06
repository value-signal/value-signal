export type Status = 'achieved' | 'on_track' | 'delayed' | 'unverifiable'

export type Plan = {
  report_name: string
  disclosed_at: string
  source_url: string
}

export type Company = {
  corp_code: string
  stock_code: string
  corp_name: string
  market: 'KOSPI' | 'KOSDAQ'
  is_low_pbr: 0 | 1
}

export type CompanySummary = Company & {
  kpi_count: number
  status_counts: Partial<Record<Status, number>>
  latest_plan: Plan | null
}

export type Kpi = {
  id: number
  category: 'dividend' | 'treasury_stock' | 'shareholder_return' | 'capital_efficiency'
  metric: string
  measure_type: 'level' | 'cumulative'
  target_min: number | null
  target_max: number | null
  unit: string
  deadline: string
  definition: string | null
  quote: string
  review_status: 'pending' | 'approved'
  review_note: string | null
  source_url: string
  status: Status | null
  achievement_rate: number | null
  elapsed_rate: number | null
  reason: string | null
  evaluated_at: string | null
  actual_value: number | null
  actual_unit: string | null
  actual_period: string | null
}

export type ExcludedKpi = Pick<
  Kpi,
  'id' | 'metric' | 'target_min' | 'target_max' | 'unit' | 'deadline' | 'review_note'
>

export type Claim = {
  id: number
  metric: string
  claimed_value: number
  unit: string
  period_year: number
  qualifier: string | null
  quote: string
  actual_value: number | null
  actual_unit: string | null
  comparison: 'match' | 'differs' | 'no_standard'
  source_url: string
  report_name: string
}

export type Scorecard = {
  company: Company
  plan: Plan | null
  kpis: Kpi[]
  excluded: ExcludedKpi[]
  claims: Claim[]
}

export type LowPbrCompany = {
  stock_code: string
  corp_name: string
  market: Company['market']
  pbr: number
  sector: string
  announced_on: string
  base_date: string
  plan_status: 'pbr_plan' | 'general_plan' | 'none'
  latest_plan_on: string | null
  corp_code: string | null
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    throw new Error(`데이터를 불러오지 못했습니다 (${response.status})`)
  }
  return response.json()
}

export function fetchCompanies(): Promise<CompanySummary[]> {
  return getJson('/api/companies')
}

export function fetchLowPbr(): Promise<LowPbrCompany[]> {
  return getJson('/api/low-pbr')
}

export function fetchScorecard(corpCode: string): Promise<Scorecard> {
  return getJson(`/api/companies/${corpCode}/scorecard`)
}

export type QaAnswer = {
  answerable: boolean
  answer: string
  sources: { label: string; quote: string | null; url: string }[]
  cached: boolean
}

export async function askQuestion(corpCode: string, question: string): Promise<QaAnswer> {
  const response = await fetch('/api/qa', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ corp_code: corpCode, question }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = typeof body?.detail === 'string' ? body.detail : null
    throw new Error(detail ?? `답변을 불러오지 못했습니다 (${response.status})`)
  }
  return response.json()
}
