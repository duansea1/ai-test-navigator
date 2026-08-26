import React from 'react'
import { getJson } from '../api'
import { Icon, Skeleton, EmptyState } from '../components/ui'

interface TaskRow {
  task_id: string
  title: string
  projects: string
  branch: string
  status: string
  stage: string
  progress: number
  message: string | null
  report_id: string | null
  created_at: string
}
interface TrendRow { day: string; tasks: number }
interface Dash {
  totals: Record<string, number>
  tasks: TaskRow[]
  trend: TrendRow[]
  recent_reports: Array<{ report_id: string; generated_at: string; branch: string; summary: Record<string, number> }>
  dsh: Record<string, any>
  source: string
}

const STATUS_CLS: Record<string, string> = { completed: 'ok', failed: 'bad', running: 'warn', pending: 'neutral' }
const STATUS_LABEL: Record<string, string> = { completed: '已完成', failed: '失败', running: '进行中', pending: '排队中' }

/* ── SVG 平滑趋势图（Catmull-Rom → Bezier · 参考 D3 curve） ─────────── */
function niceMax(max: number): number {
  /* y 轴自适应：取「好看」的刻度上限（1/2/5×10^n），小值不硬放大到 10 */
  if (max <= 5) return 5
  const exp = Math.pow(10, Math.floor(Math.log10(max)))
  for (const m of [1, 2, 5, 10]) {
    const v = m * exp
    if (v >= max) return v
  }
  return 10 * exp
}
function TrendChart({ data, height = 150 }: { data: TrendRow[]; height?: number }) {
  const W = 720, H = height, P = { t: 14, r: 8, b: 22, l: 30 }
  const vals = data.map(d => d.tasks)
  const top = niceMax(Math.max(1, ...vals))
  const max = top
  const iw = W - P.l - P.r, ih = H - P.t - P.b
  const x = (i: number) => P.l + (data.length <= 1 ? iw / 2 : (i / (data.length - 1)) * iw)
  const y = (v: number) => P.t + ih - (v / max) * ih
  // 刻度线取整数值（top<=5 逐 1，否则 4 等分取整）
  const ticks = top <= 5 ? Array.from({ length: top + 1 }, (_, i) => i)
    : [0, Math.round(top / 4), Math.round(top / 2), Math.round(3 * top / 4), top]
  // Catmull-Rom 平滑曲线
  const pts = vals.map((v, i) => [x(i), y(v)] as const)
  let d = ''
  if (pts.length === 1) d = `M ${pts[0][0]} ${pts[0][1]}`
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)]
    const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6
    const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6
    d += (i === 0 ? `M ${p1[0]} ${p1[1]} ` : '') + `C ${c1x} ${c1y}, ${c2x} ${c2y}, ${p2[0]} ${p2[1]} `
  }
  const area = d ? `${d} L ${pts[pts.length - 1][0]} ${P.t + ih} L ${pts[0][0]} ${P.t + ih} Z` : ''
  const last = vals[vals.length - 1] ?? 0
  const gid = 'trend-grad'
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }} role="img">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#1f3bb3" stopOpacity=".18" />
          <stop offset="100%" stopColor="#1f3bb3" stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* 网格线 + y 轴刻度 */}
      {ticks.map(tv => (
        <g key={tv}>
          <line x1={P.l} x2={W - P.r} y1={y(tv)} y2={y(tv)}
            stroke="#eef1f6" strokeWidth="1" strokeDasharray={tv === 0 ? '' : '3 4'} />
          <text x={P.l - 5} y={y(tv) + 3.5} textAnchor="end" fontSize="10" fill="#98a2b3">{tv}</text>
        </g>
      ))}
      {area ? <path d={area} fill={`url(#${gid})`} /> : null}
      {d ? <path d={d} fill="none" stroke="#1f3bb3" strokeWidth="2.2" strokeLinecap="round" /> : null}
      {/* 数据点 + 悬浮提示 */}
      {pts.map(([px, py], i) => (
        <g key={i} className="trend-dot">
          <circle cx={px} cy={py} r="9" fill="transparent" />
          <circle cx={px} cy={py} r="3" fill="#fff" stroke="#1f3bb3" strokeWidth="2" className="trend-pt" />
          <title>{data[i].day}：{data[i].tasks} 个任务</title>
        </g>
      ))}
      {/* 末值标签 */}
      {pts.length ? (
        <text x={pts[pts.length - 1][0]} y={pts[pts.length - 1][1] - 9} textAnchor="end"
          fontSize="11" fontWeight="700" fill="#1f3bb3">{last}</text>
      ) : null}
      {/* x 轴日期（首/中/尾） */}
      {[0, Math.floor((data.length - 1) / 2), data.length - 1].filter((v, i, a) => a.indexOf(v) === i).map(i => (
        <text key={i} x={x(i)} y={H - 6} textAnchor={i === 0 ? 'start' : i === data.length - 1 ? 'end' : 'middle'}
          fontSize="10.5" fill="#98a2b3">{data[i]?.day?.slice(5)}</text>
      ))}
    </svg>
  )
}

/* ── 环形图（风险/状态分布） ────────────────────────────────────────── */
function Donut({ parts, size = 128 }: { parts: Array<{ label: string; value: number; color: string }>; size?: number }) {
  const total = parts.reduce((s, p) => s + p.value, 0)
  const R = 40, C = 2 * Math.PI * R
  let acc = 0
  return (
    <div className="donut-wrap">
      <svg width={size} height={size} viewBox="0 0 100 100" style={{ transform: 'rotate(-90deg)' }}>
        <circle cx="50" cy="50" r={R} fill="none" stroke="#f2f4f7" strokeWidth="12" />
        {total > 0 && parts.map((p, i) => {
          const frac = p.value / total
          const dash = `${frac * C} ${C}`
          const off = -acc * C
          acc += frac
          return <circle key={i} cx="50" cy="50" r={R} fill="none" stroke={p.color} strokeWidth="12"
            strokeDasharray={dash} strokeDashoffset={off} strokeLinecap="butt" className="donut-seg" />
        })}
      </svg>
      <div className="donut-legend">
        {parts.map(p => (
          <div key={p.label} className="dl-row">
            <span className="dl-dot" style={{ background: p.color }} />
            <span className="dl-label">{p.label}</span>
            <b>{p.value}</b>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── 统计卡（带 sparkline 迷你趋势 · 参考 Stripe Dashboard 卡） ──────── */
function StatCard({ icon, label, value, sub, spark }: {
  icon: React.ReactNode; label: string; value: React.ReactNode; sub?: React.ReactNode; spark?: number[]
}) {
  return (
    <div className="stat-card">
      <div className="sc-top">
        <span className="sc-icon">{icon}</span>
        <span className="sc-label">{label}</span>
      </div>
      <div className="sc-row">
        <b className="sc-value">{value}</b>
        {spark && spark.length > 1 ? <Sparkline data={spark} /> : null}
      </div>
      {sub ? <div className="sc-sub">{sub}</div> : null}
    </div>
  )
}

function Sparkline({ data, w = 76, h = 26 }: { data: number[]; w?: number; h?: number }) {
  const max = Math.max(1, ...data)
  const step = w / (data.length - 1)
  const pts = data.map((v, i) => `${i * step},${h - 2 - (v / max) * (h - 5)}`)
  return (
    <svg width={w} height={h} className="spark" aria-hidden>
      <polyline points={pts.join(' ')} fill="none" stroke="#7c93f0" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={(data.length - 1) * step} cy={h - 2 - (data[data.length - 1] / max) * (h - 5)} r="2" fill="#1f3bb3" />
    </svg>
  )
}

/* ── 主页面 ─────────────────────────────────────────────────────────── */
export function DashboardPage() {
  const [data, setData] = React.useState<Dash | null>(null)
  const [error, setError] = React.useState('')
  const load = React.useCallback(() => {
    getJson<Dash>('/api/dashboard').then(setData).catch(e => setError(String(e)))
  }, [])
  React.useEffect(() => {
    load()
    const timer = setInterval(load, 10000)
    return () => clearInterval(timer)
  }, [load])

  if (error) return <div className="status danger">加载失败：{error}</div>
  if (!data) {
    return (
      <div className="grid cols-4">
        {[0, 1, 2, 3].map(i => <div key={i} className="stat-card"><Skeleton h={12} w={64} /><Skeleton h={30} w={40} style={{ marginTop: 10 }} /></div>)}
      </div>
    )
  }
  const t = data.totals
  const dsh = data.dsh ?? {}
  const trend = data.trend ?? []
  const spark = trend.slice(-14).map(x => x.tasks)
  const statusParts = [
    { label: '已完成', value: t.tasks_completed ?? 0, color: '#12b76a' },
    { label: '进行中', value: t.tasks_running ?? 0, color: '#f79009' },
    { label: '失败', value: (t.tasks_total ?? 0) - (t.tasks_completed ?? 0) - (t.tasks_running ?? 0), color: '#f04438' },
  ]
  const needsReview = t.needs_review ?? 0

  return (
    <>
      {/* 统计卡行 */}
      <div className="grid cols-4">
        <StatCard icon={<Icon name="compass" size={15} />} label="分析任务"
          value={t.tasks_total} spark={spark}
          sub={<span className="sc-up"><Icon name="trend" size={12} /> 近 14 天 {spark.reduce((s, v) => s + v, 0)} 个</span>} />
        <StatCard icon={<Icon name="inbox" size={15} />} label="需求条目" value={t.requirements}
          sub={<span>{t.tasks_running ?? 0} 个任务进行中</span>} />
        <StatCard icon={<Icon name="flask" size={15} />} label="测试用例" value={t.test_cases}
          sub={<span>覆盖 {t.reports ?? 0} 份报告</span>} />
        <StatCard icon={<Icon name="alert" size={15} />} label="待复核" value={needsReview}
          sub={needsReview > 0 ? <span className="sc-warn">needs_review 需人工确认</span> : <span>无待复核项</span>} />
      </div>

      <div className="grid cols-2">
        {/* 趋势图 */}
        <div className="card">
          <h3 className="card-h">
            <Icon name="trend" size={15} /> 近 14 天任务趋势
            {data.source === 'files' ? <span className="badge warn" style={{ marginLeft: 8 }}>DB 降级·文件统计</span> : null}
          </h3>
          {trend.length === 0 ? (
            <EmptyState icon="trend" title="暂无任务数据" desc="创建第一个分析任务后，这里会展示每日任务趋势" />
          ) : <TrendChart data={trend} />}
        </div>
        {/* 任务状态分布 + DSH */}
        <div className="card">
          <h3 className="card-h"><Icon name="cpu" size={15} /> 任务状态与运行时</h3>
          <div className="dash-split">
            <Donut parts={statusParts} />
            <div className="dsh-mini">
              <div className="dsh-badge">
                <span className={`dot ${dsh.ready ? 'on' : 'off'}`} />
                <b>DSH Runtime</b>
                <span className={`badge ${dsh.ready ? 'ok' : 'warn'}`}>{dsh.ready ? '就绪' : '未就绪'}</span>
              </div>
              <dl className="kv kv-compact">
                <dt>模型</dt><dd><code>{String(dsh.model ?? '-')}</code></dd>
                <dt>载体</dt><dd>{dsh.mode ? `${dsh.mode}` : '-'}{dsh.node_carrier_available ? '' : '（未构建）'}</dd>
                <dt>API Key</dt><dd>{dsh.api_key_configured ? '已配置' : '未配置'}</dd>
                <dt>会话</dt><dd>{dsh.running ? `运行中 ${dsh.active_sessions} 个` : '未启动'}</dd>
              </dl>
              {dsh.last_error ? <div className="hint err-text">最近错误：{String(dsh.last_error).slice(0, 120)}</div> : null}
            </div>
          </div>
        </div>
      </div>

      {/* 最近任务 */}
      <div className="card">
        <h3 className="card-h"><Icon name="clock" size={15} /> 最近任务
          <span className="hint" style={{ marginLeft: 'auto', fontWeight: 400 }}>10 秒自动刷新</span>
        </h3>
        {(data.tasks ?? []).length === 0 ? (
          <EmptyState icon="inbox" title="还没有分析任务" desc="粘贴需求描述或接口 URL，让 8 个 FDE Agent 协同完成分析"
            action="前往需求分析" onAction={() => { location.hash = '/requirements' }} />
        ) : (
          <table className="row-hover">
            <thead><tr><th>任务</th><th>状态</th><th>阶段</th><th>进度</th><th>报告</th><th>创建时间</th><th></th></tr></thead>
            <tbody>
              {data.tasks.map(t2 => (
                <tr key={t2.task_id}>
                  <td><div className="tt-cell"><b>{t2.title || t2.task_id}</b><span className="hint">{t2.task_id}</span></div></td>
                  <td><span className={`badge ${STATUS_CLS[t2.status] ?? 'neutral'}`}>{STATUS_LABEL[t2.status] ?? t2.status}</span></td>
                  <td className="hint">{t2.stage || '-'}</td>
                  <td style={{ minWidth: 110 }}>
                    {t2.status === 'running' || t2.status === 'pending' ? (
                      <div className="pbar"><span style={{ width: `${Math.max(4, t2.progress)}%` }} /></div>
                    ) : <span className="hint">-</span>}
                  </td>
                  <td>{t2.report_id ? <code>{t2.report_id}</code> : <span className="hint">-</span>}</td>
                  <td className="hint">{t2.created_at?.slice(0, 19).replace('T', ' ')}</td>
                  <td><a className="row-link" href={`#/requirements`}>打开 <Icon name="chevron-right" size={12} /></a></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
