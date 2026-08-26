import React from 'react'
import { getJson } from '../api'
import { EmptyState } from '../components/ui'

interface ReportItem {
  report_id: string
  generated_at: string
  branch: string
  projects: string[]
  summary: Record<string, number>
  files: { json: string; markdown: string; html: string }
}

export function ReportsPage() {
  const [data, setData] = React.useState<{ reports: ReportItem[] } | null>(null)
  const [error, setError] = React.useState('')
  React.useEffect(() => {
    getJson<{ reports: ReportItem[] }>('/api/reports').then(setData).catch(e => setError(String(e)))
  }, [])
  if (error) return <div className="status danger">加载失败：{error}</div>
  if (!data) return <div className="empty">加载中...</div>
  return (
    <div className="card">
      <h3>报告列表（{data.reports.length} 份）</h3>
      {data.reports.length === 0 ? (
        <EmptyState icon="file-text" title="暂无报告" desc="先到需求分析创建分析任务，完成后会自动生成 HTML / Markdown / JSON 报告"
          action="前往需求分析" onAction={() => { location.hash = '/requirements' }} />
      ) : (
        <table>
          <thead>
            <tr><th>报告 ID</th><th>生成时间</th><th>分支</th><th>项目</th><th>需求</th><th>证据</th><th>用例</th><th>待评审</th><th>导出</th></tr>
          </thead>
          <tbody>
            {data.reports.map(r => (
              <tr key={r.report_id}>
                <td><code>{r.report_id}</code></td>
                <td>{r.generated_at?.slice(0, 19).replace('T', ' ')}</td>
                <td><code>{r.branch}</code></td>
                <td className="hint">{(r.projects ?? []).join(', ') || '-'}</td>
                <td>{r.summary?.requirements ?? 0}</td>
                <td>{r.summary?.evidence ?? 0}</td>
                <td>{r.summary?.test_cases ?? 0}</td>
                <td>{r.summary?.needs_review ? <span className="badge warn">{r.summary.needs_review}</span> : 0}</td>
                <td>
                  <a href={r.files.html} target="_blank" rel="noreferrer">HTML</a>{' · '}
                  <a href={r.files.markdown} target="_blank" rel="noreferrer">MD</a>{' · '}
                  <a href={r.files.json} target="_blank" rel="noreferrer">JSON</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="hint" style={{ marginTop: 12 }}>needs_review 人工复核流（确认/误报/漏报留痕）排期 M3.2；版本对比为扩展项。</p>
    </div>
  )
}
