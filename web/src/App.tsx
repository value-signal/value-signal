import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { CompanyPage } from './pages/CompanyPage'
import { HomePage } from './pages/HomePage'
import { LowPbrPage } from './pages/LowPbrPage'
import { MethodPage } from './pages/MethodPage'
import { SubscriptionPage } from './pages/SubscriptionPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="low-pbr" element={<LowPbrPage />} />
          <Route path="method" element={<MethodPage />} />
          <Route path="subscription" element={<SubscriptionPage />} />
        </Route>
        <Route
          element={
            <Layout
              actions={
                <a className="primary-button" href="#qa">
                  이 기업에 대해 질문하기
                </a>
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
