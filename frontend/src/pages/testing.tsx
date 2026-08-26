import React from 'react'
import { getJson } from '../api'
import { EmptyState } from '../components/ui'

interface TestingData {
  status: string
  milestone: string
  planned: string[]
  message: string
}

export function TestingPage() {
  const [data, setData] = React.useState<TestingData | null>(null)
  const [error, setError] = React.useState('')
  React.useEffect(() => {
    getJson<TestingData>('/api/testing').then(setData).catch(e => setError(String(e)))
  }, [])
  if (error) return <div className="status danger">加载失败：{error}</div>
  if (!data) return <div className="empty">加载中...</div>
  return (
    <div className="card">
      <h3>测试执行引擎 <span className="badge neutral">{data.milestone}</span></h3>
      <EmptyState icon="flask" title="测试执行引擎排期 M4"
        desc={data.message}
        action="前往需求分析" onAction={() => { location.hash = '/requirements' }} />
      <h3 style={{ marginTop: 18 }}>规划能力</h3>
      <table>
        <thead><tr><th>#</th><th>能力</th></tr></thead>
        <tbody>
          {data.planned.map((p, i) => (
            <tr key={p}><td>{i + 1}</td><td>{p}</td></tr>
          ))}
        </tbody>
      </table>
      <p className="hint" style={{ marginTop: 12 }}>设计原则：白名单命令 + dry-run 先行，测试执行默认只读，失败自动归因到需求条目。</p>
    </div>
  )
}
