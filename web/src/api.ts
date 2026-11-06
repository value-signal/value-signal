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
  is_exempt: 0 | 1
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
  source_url: string
  status: Status | null
  achievement_rate: number | null
  elapsed_rate: number | null
  reason: string | null
  evaluated_at: string | null
}

export type Scorecard = {
  company: Company
  plan: Plan | null
  kpis: Kpi[]
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

export function fetchScorecard(corpCode: string): Promise<Scorecard> {
  return getJson(`/api/companies/${corpCode}/scorecard`)
}
