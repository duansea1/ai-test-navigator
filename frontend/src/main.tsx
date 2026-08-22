import React from 'react'
import { render } from 'react-dom'
import { Layout } from './layout'
import { DashboardPage } from './pages/dashboard'
import { RequirementsPage } from './pages/requirements'
import { ProjectsPage } from './pages/projects'
import { AgentsPage } from './pages/agents'
import { TestingPage } from './pages/testing'
import { ReportsPage } from './pages/reports'
import { EvidencePage } from './pages/evidence'
import { SettingsPage } from './pages/settings'

function useHashRoute(): string {
  const [hash, setHash] = React.useState(() => location.hash.replace(/^#/, '') || '/dashboard')
  React.useEffect(() => {
    const onChange = () => setHash(location.hash.replace(/^#/, '') || '/dashboard')
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return hash
}

const PAGES: Record<string, React.ReactNode> = {
  '/dashboard': <DashboardPage />,
  '/requirements': <RequirementsPage />,
  '/projects': <ProjectsPage />,
  '/agents': <AgentsPage />,
  '/testing': <TestingPage />,
  '/reports': <ReportsPage />,
  '/evidence': <EvidencePage />,
  '/settings': <SettingsPage />,
}

const TITLES: Record<string, [string, string]> = {
  '/dashboard': ['工作台', '任务总览 · 风险分布 · 趋势'],
  '/requirements': ['需求分析', '需求输入 · 结构化解析 · 分析任务'],
  '/projects': ['项目管理', '工作区 · 项目 · 分支 · 代码索引'],
  '/agents': ['Agent 编排', 'Agent 定义 · Skills · DSH Runtime'],
  '/testing': ['测试中心', '用例 · 执行 · 日志 · 归因'],
  '/reports': ['报告中心', '报告列表 · 版本对比 · 导出'],
  '/evidence': ['证据中心', '代码证据 · 调用链 · 知识检索'],
  '/settings': ['系统设置', '密钥 · 权限 · 运行时 · 集成'],
}

function App() {
  const route = useHashRoute()
  const [title, crumb] = TITLES[route] ?? ['工作台', '']
  return (
    <Layout route={route} title={title} crumb={crumb}>
      {PAGES[route] ?? <DashboardPage />}
    </Layout>
  )
}

render(<App />, document.getElementById('root')!)
