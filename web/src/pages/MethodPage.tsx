const STEPS = [
  {
    title: '목표 찾기',
    body: 'AI가 기업가치 제고 계획 공시에서 배당, 자사주, 주주환원, 자본효율 목표를 뽑습니다. 숫자와 기한이 없는 표현은 목표로 세지 않습니다.',
  },
  {
    title: '원문 대조',
    body: '인용문이 원문에 그대로 있는지, 목표 숫자가 인용문에 있는지 코드로 확인합니다. 통과하지 못한 항목은 버립니다.',
  },
  {
    title: '실적 채점',
    body: 'AI가 아니라 코드가 DART 공시 실적으로 달성률을 계산합니다. 목표를 넘으면 달성, 달성률이 기간 경과율보다 20%p 이상 뒤처지거나 기한까지 미달이면 주의입니다.',
  },
  {
    title: '확인 불가 표시',
    body: '회사의 지표 정의와 공시 실적의 기준이 다르면 억지로 계산하지 않고 확인 불가로 표시합니다.',
  },
]

export function MethodPage() {
  return (
    <main className="page page-narrow">
      <p className="eyebrow">채점 방법</p>
      <h1 className="page-title">목표는 AI가 뽑고, 숫자는 코드가 계산합니다</h1>
      <ol className="method-list">
        {STEPS.map((step) => (
          <li key={step.title}>
            <h2>{step.title}</h2>
            <p>{step.body}</p>
          </li>
        ))}
      </ol>
      <section className="formula">
        <h2>계산식</h2>
        <p>달성률 = (실적 − 기준값) ÷ (목표 − 기준값)</p>
        <p>기간 경과율 = (실적 기준일 − 시작일) ÷ (기한 − 시작일)</p>
        <p>ROE = 지배주주 순이익 ÷ 평균 지배주주 자본</p>
        <p>주주환원율 = (현금배당 총액 + 자기주식 취득액) ÷ 지배주주 순이익</p>
      </section>
    </main>
  )
}
