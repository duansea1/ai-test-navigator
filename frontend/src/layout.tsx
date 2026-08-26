import React from 'react'
import { Icon, CommandPalette, ToastHost, type Command, type IconName, toast } from './components/ui'

const MENU: Array<{ path: string; label: string; icon: IconName; tag?: string; group: string }> = [
  { path: '/dashboard', label: '工作台', icon: 'dashboard', group: '分析' },
  { path: '/requirements', label: '需求分析', icon: 'compass', group: '分析' },
  { path: '/projects', label: '项目管理', icon: 'folder', group: '分析' },
  { path: '/agents', label: 'Agent 编排', icon: 'bot', tag: 'DSH', group: '分析' },
  { path: '/testing', label: '测试中心', icon: 'flask', tag: 'M3', group: '质量' },
  { path: '/reports', label: '报告中心', icon: 'file-text', group: '质量' },
  { path: '/evidence', label: '证据中心', icon: 'search-code', tag: 'M1', group: '质量' },
  { path: '/settings', label: '系统设置', icon: 'settings', group: '系统' },
]

/** 侧边栏折叠状态全局共享（刷新保持）。 */
const COLLAPSE_KEY = 'atn.sidebar.collapsed'
function useCollapsed(): [boolean, (v: boolean) => void] {
  const [v, setV] = React.useState(() => {
    try { return localStorage.getItem(COLLAPSE_KEY) === '1' } catch { return false }
  })
  const set = (nv: boolean) => {
    setV(nv)
    try { localStorage.setItem(COLLAPSE_KEY, nv ? '1' : '0') } catch { /* 无痕模式忽略 */ }
  }
  return [v, set]
}

/** 最近任务（命令面板快速打开，最多 5 条，10 秒刷新）。 */
interface RecentTask { task_id: string; title: string; status: string }
function useRecentTasks(): RecentTask[] {
  const [tasks, setTasks] = React.useState<RecentTask[]>([])
  React.useEffect(() => {
    let alive = true
    const load = () => {
      fetch('/api/requirements/tasks?limit=5')
        .then(r => r.ok ? r.json() : null)
        .then((d: { tasks?: RecentTask[] } | null) => {
          if (alive && d?.tasks) setTasks(d.tasks)
        })
        .catch(() => { /* 面板打开时才用，静默失败 */ })
    }
    load()
    const timer = setInterval(load, 10000)
    return () => { alive = false; clearInterval(timer) }
  }, [])
  return tasks
}

const TASK_STATUS_LABEL: Record<string, string> = { completed: '已完成', failed: '失败', running: '进行中', pending: '排队中' }

export function Layout({ route, title, crumb, children }: { route: string; title: string; crumb: string; children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useCollapsed()
  const [cpOpen, setCpOpen] = React.useState(false)
  const recent = useRecentTasks()

  // 全局快捷键：Ctrl/Cmd+K 命令面板；Ctrl/Cmd+B 折叠侧边栏（与主流 IDE 一致）
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey
      if (mod && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); setCpOpen(o => !o) }
      else if (mod && (e.key === 'b' || e.key === 'B')) { e.preventDefault(); setCollapsed(!collapsed) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [collapsed, setCollapsed])

  const go = (path: string) => { location.hash = path }

  const commands: Command[] = React.useMemo(() => {
    const nav = MENU.map(m => ({
      id: `nav-${m.path}`, label: `前往 ${m.label}`, hint: '导航', icon: m.icon, run: () => go(m.path),
    }))
    const recents: Command[] = recent.map(t => ({
      id: `task-${t.task_id}`, label: t.title || t.task_id,
      hint: `最近任务 · ${TASK_STATUS_LABEL[t.status] ?? t.status}`, icon: 'clock', run: () => go('/requirements'),
    }))
    const actions: Command[] = [
      { id: 'act-new-analysis', label: '新建需求分析', hint: '动作', icon: 'plus', hotkey: '', run: () => go('/requirements') },
      { id: 'act-toggle-sidebar', label: collapsed ? '展开侧边栏' : '折叠侧边栏', hint: '动作', icon: 'panel-left', hotkey: 'Ctrl B', run: () => setCollapsed(!collapsed) },
      { id: 'act-copy-path', label: '复制当前页面路径', hint: '动作', icon: 'hash', run: () => {
        navigator.clipboard?.writeText(location.href).then(() => toast('页面链接已复制', 'ok')).catch(() => {})
      } },
    ]
    return [...actions, ...recents, ...nav]
  }, [collapsed, setCollapsed, recent])

  return (
    <div className={`app ${collapsed ? 'side-collapsed' : ''}`}>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-logo" title="AI Test Navigator">⌘</div>
          {!collapsed ? (
            <div className="brand-text">
              <h1>AI Test Navigator</h1>
              <small>FDE 质量分析平台</small>
            </div>
          ) : null}
        </div>
        {!collapsed ? (
          <button className="cmdk" onClick={() => setCpOpen(true)}>
            <Icon name="search-code" size={14} />
            <span>搜索或跳转…</span>
            <kbd>Ctrl K</kbd>
          </button>
        ) : (
          <button className="cmdk mini" onClick={() => setCpOpen(true)} title="命令面板 Ctrl+K">
            <Icon name="search-code" size={14} />
          </button>
        )}
        <nav className="menu">
          {MENU.map((m, i) => {
            const showGroup = !collapsed && (i === 0 || MENU[i - 1].group !== m.group)
            return (
              <React.Fragment key={m.path}>
                {showGroup ? <div className="menu-group">{m.group}</div> : null}
                <a href={`#${m.path}`} className={route === m.path ? 'active' : ''}
                  title={collapsed ? m.label : undefined}>
                  <Icon name={m.icon} size={16} />
                  {!collapsed ? <span className="m-label">{m.label}</span> : null}
                  {!collapsed && m.tag ? <span className="tag">{m.tag}</span> : null}
                </a>
              </React.Fragment>
            )
          })}
        </nav>
        <div className="sidebar-foot">
          <button className="side-toggle" onClick={() => setCollapsed(!collapsed)}
            title={collapsed ? '展开侧边栏 (Ctrl+B)' : '折叠侧边栏 (Ctrl+B)'}>
            <Icon name="panel-left" size={15} />
            {!collapsed ? <span>收起</span> : null}
          </button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <h2>{title}</h2>
          {crumb ? <span className="crumb">{crumb}</span> : null}
          <span className="spacer" />
          <button className="topbar-cmdk" onClick={() => setCpOpen(true)} title="命令面板">
            <Icon name="command" size={14} /><span>Ctrl K</span>
          </button>
        </header>
        <main className="content">{children}</main>
      </div>
      <CommandPalette open={cpOpen} onClose={() => setCpOpen(false)} commands={commands} />
      <ToastHost />
    </div>
  )
}
