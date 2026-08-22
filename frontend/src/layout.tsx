import React from 'react'

const MENU: Array<{ path: string; label: string; tag?: string }> = [
  { path: '/dashboard', label: '工作台' },
  { path: '/requirements', label: '需求分析' },
  { path: '/projects', label: '项目管理' },
  { path: '/agents', label: 'Agent 编排', tag: 'DSH' },
  { path: '/testing', label: '测试中心', tag: 'M3' },
  { path: '/reports', label: '报告中心' },
  { path: '/evidence', label: '证据中心', tag: 'M1' },
  { path: '/settings', label: '系统设置' },
]

export function Layout({ route, title, crumb, children }: { route: string; title: string; crumb: string; children: React.ReactNode }) {
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <h1>AI Test Navigator</h1>
          <small>FDE 质量分析平台 v2.0</small>
        </div>
        <nav className="menu">
          {MENU.map(m => (
            <a key={m.path} href={`#${m.path}`} className={route === m.path ? 'active' : ''}>
              {m.label}
              {m.tag ? <span className="tag">{m.tag}</span> : null}
            </a>
          ))}
        </nav>
        <div className="sidebar-foot">商用级架构 · 菜单化扩展</div>
      </aside>
      <div className="main">
        <header className="topbar">
          <h2>{title}</h2>
          <span className="crumb">{crumb}</span>
          <span className="spacer" />
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  )
}
