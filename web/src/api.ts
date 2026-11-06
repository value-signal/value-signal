export type Company = {
  corp_code: string
  stock_code: string
  corp_name: string
  market: 'KOSPI' | 'KOSDAQ'
  is_exempt: 0 | 1
}

export async function fetchCompanies(): Promise<Company[]> {
  const response = await fetch('/api/companies')
  if (!response.ok) {
    throw new Error(`기업 목록 조회 실패: ${response.status}`)
  }
  return response.json()
}
