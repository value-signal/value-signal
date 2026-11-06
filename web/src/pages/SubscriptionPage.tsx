import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { confirmSubscription, unsubscribe } from '../api'

const ACTIONS = {
  confirm: { title: '구독 확인', run: confirmSubscription },
  unsubscribe: { title: '구독 해지', run: unsubscribe },
}

export function SubscriptionPage() {
  const [params] = useSearchParams()
  const action = ACTIONS[params.get('action') as keyof typeof ACTIONS]
  const token = params.get('token')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!action || !token) return
    action
      .run(token)
      .then((result) => setMessage(result.detail))
      .catch((reason: Error) => setError(reason.message))
  }, [action, token])

  const isInvalid = !action || !token

  return (
    <main className="page page-narrow">
      <h1 className="page-title">{action?.title ?? '구독'}</h1>
      {isInvalid && (
        <p className="message" role="alert">
          유효하지 않은 링크입니다.
        </p>
      )}
      {!isInvalid && !message && !error && <p className="message">처리하고 있습니다.</p>}
      {message && (
        <p className="message" role="status">
          {message}
        </p>
      )}
      {error && (
        <p className="message" role="alert">
          {error}
        </p>
      )}
      <p className="footnote">
        <Link to="/">기업 목록으로 돌아가기</Link>
      </p>
    </main>
  )
}
