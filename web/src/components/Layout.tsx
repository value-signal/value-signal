import type { ReactNode } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'

export function Logo() {
  return (
    <Link className="logo" to="/">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="10" />
        <path d="m7.5 12.5 3 3 6-6.5" />
      </svg>
      Value Signal
    </Link>
  )
}

export function Layout({ actions }: { actions?: ReactNode }) {
  return (
    <>
      <header className="site-header">
        <div className="site-header-inner">
          <Logo />
          {actions ?? (
            <nav aria-label="주요 메뉴">
              <NavLink to="/" end>
                기업 찾기
              </NavLink>
              <NavLink to="/low-pbr">저PBR 명단</NavLink>
              <NavLink to="/method">채점 방법</NavLink>
            </nav>
          )}
        </div>
      </header>
      <Outlet />
    </>
  )
}
