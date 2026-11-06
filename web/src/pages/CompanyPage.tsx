import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { type Kpi, type Scorecard, fetchScorecard } from '../api'
import { StatusChip } from '../components/StatusChip'
import {
  STATUS_ORDER,
  companyName,
  deadlineYear,
  displayQuote,
  formatDay,
  formatTarget,
} from '../format'

function PromiseCard({ kpi }: { kpi: Kpi }) {
  const rate = kpi.achievement_rate
  return (
    <article className={`promise-card ${kpi.status === 'delayed' ? 'promise-card-alert' : ''}`}>
      <div className="promise-title">
        <h3>{kpi.metric}</h3>
        <StatusChip status={kpi.status} />
      </div>
      <blockquote>“{displayQuote(kpi.quote)}”</blockquote>
      <dl className="promise-numbers">
        <div>
          <dt>목표 · {deadlineYear(kpi.deadline)}</dt>
          <dd>{formatTarget(kpi)}</dd>
        </div>
        <div>
          <dt>달성률</dt>
          <dd className={rate === null ? 'value-empty' : `value-${kpi.status}`}>
            {rate === null ? '집계 전' : `${Math.round(rate * 100)}%`}
          </dd>
        </div>
      </dl>
      {rate !== null && (
        <div className="bar" aria-hidden="true">
          <span
            className={`bar-fill bar-${kpi.status}`}
            style={{ width: `${Math.min(Math.max(rate, 0), 1) * 100}%` }}
          />
        </div>
      )}
      {kpi.reason && <p className="promise-note">{kpi.reason}</p>}
      {kpi.definition && <p className="promise-note">기준: {kpi.definition}</p>}
      <div className="promise-footer">
        <a href={kpi.source_url} target="_blank" rel="noreferrer">
          원문 보기
        </a>
        {kpi.review_status === 'pending' && <span className="review-tag">검수 대기</span>}
      </div>
    </article>
  )
}

export function CompanyPage() {
  const { corpCode = '' } = useParams()
  const [scorecard, setScorecard] = useState<Scorecard | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchScorecard(corpCode)
      .then(setScorecard)
      .catch((reason: Error) => setError(reason.message))
  }, [corpCode])

  if (error) {
    return (
      <main className="page">
        <Link to="/">← 기업 목록</Link>
        <p className="message" role="alert">
          {error}
        </p>
      </main>
    )
  }
  if (!scorecard) {
    return (
      <main className="page">
        <p className="message">불러오는 중입니다.</p>
      </main>
    )
  }

  const { company, plan, kpis } = scorecard
  const scoredCount = kpis.filter((kpi) => kpi.status).length

  return (
    <main className="page">
      <Link className="back-link" to="/">
        ← 기업 목록
      </Link>
      <div className="company-header">
        <div>
          <h1>{companyName(company.corp_name)}</h1>
          {plan && (
            <p className="muted">
              기준 계획: {plan.report_name} · {formatDay(plan.disclosed_at)} 공시 ·{' '}
              <a href={plan.source_url} target="_blank" rel="noreferrer">
                원문 보기
              </a>
            </p>
          )}
        </div>
        <div className="chip-row">
          {STATUS_ORDER.map((status) => {
            const count = kpis.filter((kpi) => kpi.status === status).length
            return count > 0 && <StatusChip key={status} status={status} count={count} />
          })}
        </div>
      </div>

      <section className="stat-grid" aria-label="요약">
        <div className="stat-card">
          <span>찾아낸 약속</span>
          <strong>{kpis.length}개</strong>
          <small>
            채점 {scoredCount} · 대기 {kpis.length - scoredCount}
          </small>
        </div>
        <div className="stat-card">
          <span>채점 진행</span>
          <strong>
            {scoredCount} / {kpis.length}
          </strong>
          <div className="bar" aria-hidden="true">
            <span
              className="bar-fill bar-neutral"
              style={{ width: kpis.length ? `${(scoredCount / kpis.length) * 100}%` : 0 }}
            />
          </div>
        </div>
        <div className="stat-card">
          <span>실적 기준</span>
          <strong>{scoredCount > 0 ? 'DART 공시' : '수집 전'}</strong>
          <small>DART 정기보고서 · 배당 · 자사주</small>
        </div>
      </section>

      <section>
        <h2 className="section-title">약속 vs 실적</h2>
        {kpis.length === 0 ? (
          <p className="message">
            공시 본문에서 숫자와 기한이 있는 약속을 찾지 못했습니다. 상세 내용은 원문을 확인해
            주세요.
          </p>
        ) : (
          <div className="promise-grid">
            {kpis.map((kpi) => (
              <PromiseCard key={kpi.id} kpi={kpi} />
            ))}
          </div>
        )}
      </section>
    </main>
  )
}
