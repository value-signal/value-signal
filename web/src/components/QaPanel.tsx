import { type FormEvent, useState } from 'react'
import { type QaAnswer, askQuestion } from '../api'

const PRESET_QUESTIONS = [
  '주주환원 목표를 지키고 있나요?',
  '뒤처지고 있는 목표가 있나요?',
  '확인할 수 없는 목표는 무엇인가요?',
]

export function QaPanel({ corpCode }: { corpCode: string }) {
  const [input, setInput] = useState('')
  const [asked, setAsked] = useState<string | null>(null)
  const [answer, setAnswer] = useState<QaAnswer | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function ask(question: string) {
    setAsked(question)
    setAnswer(null)
    setError(null)
    setLoading(true)
    try {
      setAnswer(await askQuestion(corpCode, question))
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setLoading(false)
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const question = input.trim()
    if (question.length >= 2) ask(question)
  }

  return (
    <section className="qa-panel" id="qa">
      <h2 className="section-title">근거로 묻고 답하기</h2>
      <div className="qa-card">
        <div className="qa-presets">
          {PRESET_QUESTIONS.map((question) => (
            <button key={question} disabled={loading} onClick={() => ask(question)}>
              {question}
            </button>
          ))}
        </div>

        <form className="search" onSubmit={handleSubmit}>
          <input
            aria-label="질문 입력"
            maxLength={300}
            placeholder="이 기업의 목표와 실적에 대해 물어보세요"
            value={input}
            onChange={(event) => setInput(event.target.value)}
          />
          <button type="submit" disabled={loading}>
            질문
          </button>
        </form>

        <div aria-live="polite">
          {asked && (loading || answer || error) && <p className="qa-question">Q. {asked}</p>}
          {loading && <p className="muted">공시를 확인하고 있습니다.</p>}
          {error && (
            <p className="qa-error" role="alert">
              {error}
            </p>
          )}
          {answer && (
            <div className="qa-answer">
              <p>{answer.answer}</p>
              {answer.sources.length > 0 && (
                <ul className="qa-sources">
                  {answer.sources.map((source) => (
                    <li key={`${source.label}-${source.quote}`}>
                      <a href={source.url} target="_blank" rel="noreferrer">
                        {source.label}
                      </a>
                      {source.quote && <span>“{source.quote}”</span>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        <p className="footnote">
          AI가 공시와 채점 결과만 근거로 답합니다. 근거가 없으면 답하지 않으며, 투자 판단의 근거로
          사용할 수 없습니다.
        </p>
      </div>
    </section>
  )
}
