import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { type LowPbrCompany, fetchLowPbr } from '../api'
import { formatDay, marketLabel } from '../format'

type PlanStatus = LowPbrCompany['plan_status']
type Filter = 'all' | PlanStatus

const KIND_URL = 'https://kind.krx.co.kr/valueup/lowpbr.do?method=valueupLowpbrMain'

const PLAN_LABELS: Record<PlanStatus, string> = {
  pbr_plan: 'PBR 개선 계획',
  general_plan: '일반 계획 공시',
  none: '공시 없음',
}

const FILTERS: { value: Filter; label: string }[] = [
  { value: 'all', label: '전체' },
  { value: 'pbr_plan', label: PLAN_LABELS.pbr_plan },
  { value: 'general_plan', label: PLAN_LABELS.general_plan },
  { value: 'none', label: PLAN_LABELS.none },
]

function CompanyCell({ company }: { company: LowPbrCompany }) {
  if (!company.corp_code) return <strong className="company-name">{company.corp_name}</strong>
  return (
    <Link className="company-link" to={`/companies/${company.corp_code}`}>
      {company.corp_name}
    </Link>
  )
}

export function LowPbrPage() {
  const [companies, setCompanies] = useState<LowPbrCompany[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')

  useEffect(() => {
    fetchLowPbr()
      .then(setCompanies)
      .catch((reason: Error) => setError(reason.message))
  }, [])

  const counts = useMemo(() => {
    const list = companies ?? []
    return {
      all: list.length,
      pbr_plan: list.filter((company) => company.plan_status === 'pbr_plan').length,
      general_plan: list.filter((company) => company.plan_status === 'general_plan').length,
      none: list.filter((company) => company.plan_status === 'none').length,
      tracked: list.filter((company) => company.corp_code).length,
    }
  }, [companies])

  const keyword = query.trim().toLowerCase()
  const visible = (companies ?? []).filter(
    (company) =>
      (filter === 'all' || company.plan_status === filter) &&
      company.corp_name.toLowerCase().includes(keyword),
  )

  return (
    <main className="page">
      <p className="eyebrow">거래소 공표 명단</p>
      <h1 className="page-title">저PBR 기업 명단</h1>
      <p className="page-lead">
        거래소가 공표한 저PBR 기업 중 누가 기업가치 제고 계획을 공시했는지 보여줍니다. Value Signal이
        채점 중인 기업은 이름을 눌러 약속 이행 현황을 볼 수 있습니다.
      </p>

      {error && (
        <p className="message" role="alert">
          {error}
        </p>
      )}
      {!error && companies === null && <p className="message">불러오는 중입니다.</p>}

      {companies && (
        <>
          <section className="stat-grid" aria-label="요약">
            <div className="stat-card">
              <span>공표 기업</span>
              <strong>{counts.all}개</strong>
              <small>{formatDay(companies[0].announced_on.replaceAll('-', ''))} 공표</small>
            </div>
            <div className="stat-card">
              <span>계획 공시 기업</span>
              <strong>{counts.pbr_plan + counts.general_plan}개</strong>
              <small>
                PBR 개선 계획 {counts.pbr_plan} · 일반 계획 {counts.general_plan}
              </small>
            </div>
            <div className="stat-card">
              <span>계획 공시 없음</span>
              <strong>{counts.none}개</strong>
              <small>2024.05 이후 공시 기준</small>
            </div>
            <div className="stat-card">
              <span>Value Signal 채점 중</span>
              <strong>{counts.tracked}개</strong>
              <small>이름을 누르면 상세로 이동</small>
            </div>
          </section>

          <div className="list-filters">
            <div className="tabs" role="tablist" aria-label="계획 공시 구분">
              {FILTERS.map(({ value, label }) => (
                <button
                  key={value}
                  role="tab"
                  aria-selected={filter === value}
                  onClick={() => setFilter(value)}
                >
                  {label} {counts[value]}
                </button>
              ))}
            </div>
            <input
              aria-label="기업명 검색"
              placeholder="기업명 검색"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>

          {visible.length === 0 ? (
            <p className="message">해당하는 기업이 없습니다.</p>
          ) : (
            <div className="table-card">
              <table>
                <thead>
                  <tr>
                    <th>기업</th>
                    <th>PBR</th>
                    <th>업종</th>
                    <th>계획 공시</th>
                    <th>최근 공시일</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((company) => (
                    <tr key={company.stock_code}>
                      <td>
                        <CompanyCell company={company} />
                        <span className="subtle">{marketLabel(company.market)}</span>
                      </td>
                      <td className="number-cell">{company.pbr.toFixed(2)}배</td>
                      <td className="muted">{company.sector}</td>
                      <td>
                        <span className={`plan-chip plan-${company.plan_status}`}>
                          {PLAN_LABELS[company.plan_status]}
                        </span>
                      </td>
                      <td className="muted">
                        {company.latest_plan_on ? formatDay(company.latest_plan_on) : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <p className="footnote">
            출처:{' '}
            <a href={KIND_URL} target="_blank" rel="noreferrer">
              KIND 저PBR기업
            </a>{' '}
            (PBR 기준일 {formatDay(companies[0].base_date.replaceAll('-', ''))}). 공표에서 면제된
            기업은 거래소 명단에 없습니다. 계획 공시 구분은 DART 공시 제목을 기준으로 분류했습니다.
          </p>
        </>
      )}
    </main>
  )
}
