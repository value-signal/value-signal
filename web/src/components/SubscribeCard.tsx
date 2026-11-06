import { type FormEvent, useState } from 'react'
import { subscribe } from '../api'

type Props = {
  corpCode: string
  corpName: string
}

export function SubscribeCard({ corpCode, corpName }: Props) {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const result = await subscribe(corpCode, email.trim())
      setDone(result.detail)
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="subscribe-card">
      <h2>{corpName} 소식 받기</h2>
      <p>새 계획·이행현황 공시나 채점 상태가 바뀌면 다음 날 아침 이메일로 알려드립니다.</p>
      {done ? (
        <p className="subscribe-success" role="status">
          {done}
        </p>
      ) : (
        <form className="search" onSubmit={handleSubmit}>
          <input
            aria-label="이메일 주소"
            type="email"
            required
            maxLength={254}
            placeholder="이메일 주소"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <button type="submit" disabled={loading}>
            구독
          </button>
        </form>
      )}
      {error && (
        <p className="qa-error" role="alert">
          {error}
        </p>
      )}
      <p>이메일은 알림 발송에만 사용하며, 메일의 링크로 언제든 해지할 수 있습니다.</p>
    </section>
  )
}
