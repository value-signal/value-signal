import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { CompanyPage } from './pages/CompanyPage'
import { HomePage } from './pages/HomePage'
import { MethodPage } from './pages/MethodPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="method" element={<MethodPage />} />
        </Route>
        <Route
          element={
            <Layout
              actions={
                <button className="primary-button" disabled title="준비 중입니다">
                  이 기업에 대해 질문하기
                </button>
              }
            />
          }
        >
          <Route path="companies/:corpCode" element={<CompanyPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
