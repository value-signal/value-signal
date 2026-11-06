import { useEffect, useState } from 'react'
import { type Company, fetchCompanies } from './api'

function App() {
  const [companies, setCompanies] = useState<Company[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchCompanies()
      .then(setCompanies)
      .catch((reason: Error) => setError(reason.message))
  }, [])

  return (
    <main>
      <h1>Value Signal</h1>
      <p className="muted">기업의 밸류업 약속과 실제 실적을 비교합니다.</p>

      {error && <p role="alert">{error}</p>}
      {!error && companies === null && <p className="muted">불러오는 중입니다.</p>}
      {companies?.length === 0 && <p className="muted">등록된 기업이 없습니다.</p>}
      {companies && companies.length > 0 && (
        <ul className="company-list">
          {companies.map((company) => (
            <li key={company.corp_code}>
              {company.corp_name} <span className="muted">{company.market}</span>
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}

export default App
