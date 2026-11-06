import type { Claim } from '../api'
import { displayQuote, formatClaimActual } from '../format'

export function ClaimsSection({ claims }: { claims: Claim[] }) {
  if (claims.length === 0) return null

  return (
    <section>
      <h2 className="section-title">회사 자기평가 vs 실제 숫자</h2>
      <p className="section-note">
        회사가 이행현황 공시에 쓴 표현과 같은 연도 표준 실적을 비교합니다. 차이는 계산 기준의 차이일
        수 있습니다.
      </p>
      <div className="claim-list">
        {claims.map((claim) => (
          <div className="claim-row" key={claim.id}>
            <div className="claim-metric">{claim.metric}</div>
            <div className="claim-company">
              <span className="claim-label">회사 표현 · {claim.period_year}</span>“
              {displayQuote(claim.quote)}”
              <a className="claim-note" href={claim.source_url} target="_blank" rel="noreferrer">
                {claim.report_name}
              </a>
            </div>
            <div>
              <span className="claim-label">공시 실적 · {claim.period_year}</span>
              <span className={`claim-${claim.comparison}`}>{formatClaimActual(claim)}</span>
              {claim.qualifier && (
                <span className="claim-note">회사 기준: {claim.qualifier}</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
