import { type FormEvent, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { type CompanySummary, fetchCompanies } from '../api';
import { NewsSlider } from '../components/NewsSlider';
import { StatusChip } from '../components/StatusChip';
import { STATUS_ORDER, companyName, formatMonth, marketLabel } from '../format';

type Tab = 'scored' | 'watching';

function isScored(company: CompanySummary): boolean {
  return Object.keys(company.status_counts).length > 0;
}

function ProgressCell({ company }: { company: CompanySummary }) {
  if (!isScored(company)) return <StatusChip status={null} />;
  return (
    <div className="chip-row">
      {STATUS_ORDER.filter((status) => company.status_counts[status]).map(
        (status) => (
          <StatusChip
            key={status}
            status={status}
            count={company.status_counts[status]}
          />
        ),
      )}
    </div>
  );
}

export function HomePage() {
  const [companies, setCompanies] = useState<CompanySummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedTab, setSelectedTab] = useState<Tab | null>(null);
  const [input, setInput] = useState('');
  const [query, setQuery] = useState('');

  useEffect(() => {
    fetchCompanies()
      .then(setCompanies)
      .catch((reason: Error) => setError(reason.message));
  }, []);

  const scored = useMemo(() => companies?.filter(isScored) ?? [], [companies]);
  const watching = useMemo(
    () => companies?.filter((company) => !isScored(company)) ?? [],
    [companies],
  );
  const tab = selectedTab ?? (scored.length > 0 ? 'scored' : 'watching');
  const visible = (tab === 'scored' ? scored : watching).filter((company) =>
    companyName(company.corp_name)
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  );

  function handleSearch(event: FormEvent) {
    event.preventDefault();
    setQuery(input);
  }

  return (
    <main className="page">
      <section className="hero">
        <p className="eyebrow">기업가치 제고 계획 이행 추적</p>
        <h1>
          기업이 세운 목표,
          <br />
          실제 숫자로 채점합니다
        </h1>
        <p className="hero-copy">
          계획 공시에서 AI가 목표를 뽑고, DART 공시 실적으로 달성 여부를
          계산합니다. 모든 숫자는 원문 공시로 연결됩니다.
        </p>
        <form
          className="search"
          role="search"
          onSubmit={handleSearch}>
          <input
            aria-label="기업명 검색"
            placeholder="기업명을 입력하세요 (예: 이마트)"
            value={input}
            onChange={(event) => setInput(event.target.value)}
          />
          <button type="submit">검색</button>
        </form>
      </section>

      <NewsSlider />

      <section>
        <div className="section-header">
          <h2>기업 목록</h2>
          <div
            className="tabs"
            role="tablist"
            aria-label="기업 구분">
            <button
              role="tab"
              aria-selected={tab === 'scored'}
              onClick={() => setSelectedTab('scored')}>
              채점 완료 {scored.length}
            </button>
            <button
              role="tab"
              aria-selected={tab === 'watching'}
              onClick={() => setSelectedTab('watching')}>
              지켜볼 기업 {watching.length}
            </button>
          </div>
        </div>

        {error && (
          <p
            className="message"
            role="alert">
            {error}
          </p>
        )}
        {!error && companies === null && (
          <p className="message">불러오는 중입니다.</p>
        )}
        {companies && visible.length === 0 && (
          <p className="message">
            {query
              ? `'${query}' 검색 결과가 없습니다.`
              : '해당하는 기업이 없습니다.'}
          </p>
        )}
        {visible.length > 0 && (
          <div className="table-card">
            <table>
              <thead>
                <tr>
                  <th>기업</th>
                  <th>제시한 목표</th>
                  <th>이행 현황</th>
                  <th>최근 계획 공시</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((company) => (
                  <tr key={company.corp_code}>
                    <td>
                      <Link
                        className="company-link"
                        to={`/companies/${company.corp_code}`}>
                        {companyName(company.corp_name)}
                      </Link>
                      <span className="subtle">
                        {marketLabel(company.market)}
                        {company.is_low_pbr === 1 && ' · 저PBR 명단'}
                      </span>
                    </td>
                    <td>{company.kpi_count}개</td>
                    <td>
                      <ProgressCell company={company} />
                    </td>
                    <td className="muted">
                      {company.latest_plan
                        ? formatMonth(company.latest_plan.disclosed_at)
                        : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="footnote">
          실적과 비교할 수 있는 기업만 채점합니다. 아직 실적이 없는 기업은
          '지켜볼 기업'에서 목표 내용을 보여줍니다.
        </p>
      </section>
    </main>
  );
}
