import { type ReactNode, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { type NewsItem, fetchNews } from '../api'
import { companyName } from '../format'

const INTERVAL_MS = 6000

type Slide = {
  key: string
  date: string
  title: ReactNode
  action: ReactNode
}

// 거래소 공표는 직접 확인한 소식이라 뉴스와 상관없이 항상 첫 장에 둔다.
const PINNED: Slide = {
  key: 'low-pbr',
  date: '2026.11.1',
  title: '거래소 저PBR 기업 151개사 첫 공표 · 개선계획을 공시한 34개사는 1년간 공표 면제',
  action: <Link to="/low-pbr">명단 보기</Link>,
}

function formatDate(iso: string): string {
  const date = new Date(iso)
  return `${date.getFullYear()}.${date.getMonth() + 1}.${date.getDate()}`
}

function toSlide(news: NewsItem): Slide {
  return {
    key: news.url,
    date: formatDate(news.published_at),
    title: (
      <a href={news.url} target="_blank" rel="noopener noreferrer">
        {news.title}
        <span className="news-source">{news.source}</span>
      </a>
    ),
    action: news.corp_code && news.corp_name && (
      <Link to={`/companies/${news.corp_code}`}>{companyName(news.corp_name)} 채점 보기</Link>
    ),
  }
}

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function NewsSlider() {
  const [news, setNews] = useState<NewsItem[]>([])
  const [index, setIndex] = useState(0)
  const [paused, setPaused] = useState(false)

  useEffect(() => {
    // 뉴스를 못 불러와도 고정 소식은 보여준다.
    fetchNews()
      .then(setNews)
      .catch(() => setNews([]))
  }, [])

  const slides = [PINNED, ...news.map(toSlide)]
  const count = slides.length
  const current = slides[index % count]

  useEffect(() => {
    if (count < 2 || paused || prefersReducedMotion()) return
    const timer = window.setInterval(() => setIndex((value) => (value + 1) % count), INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [count, paused])

  function move(step: number) {
    setIndex((value) => (value + step + count) % count)
  }

  return (
    <aside
      className="notice news-slider"
      aria-roledescription="carousel"
      aria-label="밸류업 소식"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <div className="news-slide" key={current.key} aria-live={paused ? 'polite' : 'off'}>
        <span className="notice-date">{current.date}</span>
        <p className="news-title">{current.title}</p>
        {current.action && <span className="news-action">{current.action}</span>}
      </div>
      {count > 1 && (
        <div className="slider-controls">
          <button type="button" aria-label="이전 소식" onClick={() => move(-1)}>
            ‹
          </button>
          <span className="slider-count">
            {(index % count) + 1} / {count}
          </span>
          <button type="button" aria-label="다음 소식" onClick={() => move(1)}>
            ›
          </button>
        </div>
      )}
    </aside>
  )
}
