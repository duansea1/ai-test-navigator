import React from 'react'

/** 全局 UI 基件：图标 / Toast / 命令面板 / 骨架屏 / 空状态。
 *  设计参考：Linear（命令面板 + 键盘优先）、Vercel/Stripe（空状态与微交互）。 */

/* ── 图标系统（内联 SVG · 16/18px · currentColor 描边） ──────────────── */
// 图标源参考 Lucide（ISC 开源），统一 24×24 viewBox，stroke=currentColor
function Svg({ d, size = 18, fill = 'none', sw = 2 }: { d: React.ReactNode; size?: number; fill?: string; sw?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke="currentColor"
      strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }} aria-hidden>
      {d}
    </svg>
  )
}
type IconName =
  | 'dashboard' | 'compass' | 'folder' | 'bot' | 'flask' | 'file-text' | 'search-code' | 'settings'
  | 'check' | 'x' | 'alert' | 'info' | 'chevron-right' | 'chevron-down' | 'command' | 'plus'
  | 'zap' | 'clock' | 'trend' | 'git-branch' | 'cpu' | 'inbox' | 'external' | 'panel-left' | 'hash'

const PATHS: Record<IconName, React.ReactNode> = {
  dashboard: <><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></>,
  compass: <><circle cx="12" cy="12" r="9" /><path d="m15.5 8.5-2 5-5 2 2-5 5-2z" /></>,
  folder: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />,
  bot: <><rect x="4" y="8" width="16" height="12" rx="3" /><path d="M12 8V4m-4 8v.5M16 12v.5m-6 3.5h4" /></>,
  flask: <><path d="M9 3h6v5l4.5 8a2.5 2.5 0 0 1-2.2 3.7H6.7A2.5 2.5 0 0 1 4.5 16L9 8V3z" /><path d="M6.6 14h10.8" /></>,
  'file-text': <><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" /><path d="M14 3v5h5M9 13h6M9 17h4" /></>,
  'search-code': <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5M8.5 9 7 11l1.5 2M13.5 9 15 11l-1.5 2" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1.1-1.55 1.7 1.7 0 0 0-1.88.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1.1 1.7 1.7 0 0 0-.34-1.88l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h0a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55h0a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.88v0a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1.15z" /></>,
  check: <path d="m4.5 12.5 5 5 10-11" />,
  x: <path d="M18 6 6 18M6 6l12 12" />,
  alert: <><path d="M12 9v4m0 3.5v.5" /><path d="M10.3 3.9 2.5 17.5A1.9 1.9 0 0 0 4.1 20.4h15.8a1.9 1.9 0 0 0 1.6-2.9L13.7 3.9a1.9 1.9 0 0 0-3.4 0z" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5m0-8.5v.5" /></>,
  'chevron-right': <path d="m9 6 6 6-6 6" />,
  'chevron-down': <path d="m6 9 6 6 6-6" />,
  command: <path d="M9 3a3 3 0 0 1 3 3v12a3 3 0 1 1-3-3h6a3 3 0 1 1-3 3V6a3 3 0 1 1 3 3H9z" />,
  plus: <path d="M12 5v14M5 12h14" />,
  zap: <path d="M13 2 4.7 12.3a.7.7 0 0 0 .53 1.17H11l-1 8.5 8.3-10.3a.7.7 0 0 0-.53-1.17H12l1-8.5z" />,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  trend: <path d="m3 17 5.5-5.5 3.5 3.5L21 6M21 6h-5m5 0v5" />,
  'git-branch': <><circle cx="6" cy="5" r="2.5" /><circle cx="6" cy="19" r="2.5" /><circle cx="18" cy="9" r="2.5" /><path d="M6 7.5v9M18 11.5a9 9 0 0 1-9 9" /></>,
  cpu: <><rect x="6" y="6" width="12" height="12" rx="2" /><rect x="10" y="10" width="4" height="4" /><path d="M9 2v2.5M15 2v2.5M9 19.5V22M15 19.5V22M2 9h2.5M2 15h2.5M19.5 9H22M19.5 15H22" /></>,
  inbox: <><path d="M22 12h-6l-2 3h-4l-2-3H2" /><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z" /></>,
  external: <><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><path d="M15 3h6v6M10 14 21 3" /></>,
  'panel-left': <><rect x="3" y="4" width="18" height="16" rx="2.5" /><path d="M9.5 4v16" /></>,
  hash: <path d="M10 3 8 21M16 3l-2 18M3.5 8.5h17M2.5 15.5h17" />,
}
export function Icon({ name, size, className }: { name: IconName; size?: number; className?: string }) {
  return <span className={`icon ${className ?? ''}`}><Svg d={PATHS[name]} size={size} /></span>
}
export type { IconName }

/* ── 全局 Toast（右下角堆叠 · 参考 Linear/Vercel 通知条） ─────────────── */
type ToastKind = 'ok' | 'err' | 'info'
export interface ToastMsg { id: number; kind: ToastKind; text: string }
type ToastFn = (text: string, kind?: ToastKind) => void
let push: ToastFn = () => {}
/** 任何组件可调用 toast('已保存') —— 无需 context 传递。 */
export const toast: ToastFn = (text, kind = 'info') => push(text, kind)

export function ToastHost() {
  const [items, setItems] = React.useState<ToastMsg[]>([])
  React.useEffect(() => {
    push = (text, kind) => {
      const id = Date.now() + Math.random()
      setItems(prev => [...prev.slice(-3), { id, kind, text }])   // 最多同屏 4 条
      window.setTimeout(() => setItems(prev => prev.filter(t => t.id !== id)), 3400)
    }
    return () => { push = () => {} }
  }, [])
  return (
    <div className="toast-host">
      {items.map(t => (
        <div key={t.id} className={`toast ${t.kind}`}>
          <span className={`ic ${t.kind}`}>
            {t.kind === 'ok' ? <Icon name="check" size={11} /> : t.kind === 'err' ? <Icon name="x" size={11} /> : <Icon name="info" size={11} />}
          </span>
          <span>{t.text}</span>
        </div>
      ))}
    </div>
  )
}

/* ── 骨架屏（加载占位 · 呼吸渐变） ──────────────────────────────────── */
export function Skeleton({ h = 14, w, r = 6, style }: { h?: number; w?: number | string; r?: number; style?: React.CSSProperties }) {
  return <div className="sk" style={{ height: h, width: w, borderRadius: r, ...style }} />
}

/* ── 空状态（插画式图标 + 行动引导 · 参考 Vercel/GitHub 空状态） ──────── */
export function EmptyState({ icon, title, desc, action, onAction }: {
  icon: IconName; title: string; desc?: string; action?: string; onAction?: () => void
}) {
  return (
    <div className="empty-state">
      <div className="es-icon"><Icon name={icon} size={22} /></div>
      <div className="es-title">{title}</div>
      {desc ? <div className="es-desc">{desc}</div> : null}
      {action && onAction ? <button className="btn primary sm es-btn" onClick={onAction}>{action}</button> : null}
    </div>
  )
}

/* ── 命令面板（Ctrl/Cmd+K · 参考 Linear/VSCode 快速导航） ────────────── */
export interface Command {
  id: string
  label: string
  hint?: string                    // 分组标题：导航 / 动作 / 最近任务
  icon: IconName
  hotkey?: string
  run: () => void
}

export function CommandPalette({ open, onClose, commands }: { open: boolean; onClose: () => void; commands: Command[] }) {
  const [q, setQ] = React.useState('')
  const [sel, setSel] = React.useState(0)
  const inputRef = React.useRef<HTMLInputElement>(null)
  const listRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => { if (open) { setQ(''); setSel(0); window.setTimeout(() => inputRef.current?.focus(), 30) } }, [open])

  /** 简易模糊匹配：query 字符按序出现在 label 中即命中，高亮命中间隔。 */
  const fuzzy = React.useCallback((text: string, query: string): number => {
    if (!query) return 1
    const t = text.toLowerCase(), p = query.toLowerCase()
    let score = 0, ti = 0, streak = 0
    for (const ch of p) {
      const idx = t.indexOf(ch, ti)
      if (idx < 0) return -1
      streak = idx === ti ? streak + 2 : 1
      score += streak + (idx === 0 ? 3 : 0)
      ti = idx + 1
    }
    return score
  }, [])

  const hits = React.useMemo(() => {
    const all = commands.map(c => ({ c, s: fuzzy(c.label + ' ' + (c.hint ?? ''), q) }))
      .filter(x => x.s >= 0)
    if (!q) return all.map(x => x.c)
    return all.sort((a, b) => b.s - a.s).map(x => x.c)
  }, [commands, q, fuzzy])

  React.useEffect(() => { setSel(s => Math.min(s, Math.max(0, hits.length - 1))) }, [hits.length])

  const exec = (c?: Command) => {
    if (!c) return
    onClose()
    c.run()
  }
  if (!open) return null
  return (
    <div className="cp-mask" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="cp">
        <div className="cp-input">
          <Icon name="search-code" size={16} />
          <input ref={inputRef} value={q} placeholder="搜索页面、动作或任务…"
            onChange={e => { setQ(e.target.value); setSel(0) }}
            onKeyDown={e => {
              if (e.key === 'ArrowDown') { e.preventDefault(); setSel(s => Math.min(s + 1, hits.length - 1)) }
              else if (e.key === 'ArrowUp') { e.preventDefault(); setSel(s => Math.max(0, s - 1)) }
              else if (e.key === 'Enter') { e.preventDefault(); exec(hits[sel]) }
              else if (e.key === 'Escape') { e.preventDefault(); onClose() }
            }} />
          <span className="cp-esc">ESC</span>
        </div>
        <div className="cp-list" ref={listRef}>
          {hits.length === 0 ? <div className="cp-empty">没有匹配「{q}」的命令</div> :
            hits.map((c, i) => (
              <button key={c.id} className={`cp-item ${i === sel ? 'sel' : ''}`}
                onMouseEnter={() => setSel(i)}
                onMouseDown={e => { e.preventDefault(); exec(c) }}>
                <span className="cp-ic"><Icon name={c.icon} size={15} /></span>
                <span className="cp-label">{c.label}</span>
                {c.hint ? <span className="cp-hint">{c.hint}</span> : null}
                {c.hotkey ? <span className="cp-key">{c.hotkey}</span> : null}
                <span className="cp-go"><Icon name="chevron-right" size={13} /></span>
              </button>
            ))}
          <div className="cp-foot">↑↓ 选择 · ↵ 执行 · ESC 关闭</div>
        </div>
      </div>
    </div>
  )
}
