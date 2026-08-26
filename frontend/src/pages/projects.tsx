import React from 'react'
import { getJson } from '../api'

interface ProjectItem {
  name: string
  is_git: boolean
  branch: string
  commit: string
}

interface ProjectsData {
  workspace: string
  default_branch: string
  projects: ProjectItem[]
}

export function ProjectsPage() {
  const [data, setData] = React.useState<ProjectsData | null>(null)
  const [error, setError] = React.useState('')
  React.useEffect(() => {
    getJson<ProjectsData>('/api/projects').then(setData).catch(e => setError(String(e)))
  }, [])
  if (error) return <div className="status danger">加载失败：{error}</div>
  if (!data) return <div className="empty">加载中...</div>
  return (
    <>
      <div className="card">
        <h3>工作区</h3>
        <dl className="kv">
          <dt>工作区路径</dt><dd><code>{data.workspace}</code></dd>
          <dt>默认分析分支</dt><dd><code>{data.default_branch}</code></dd>
          <dt>项目数量</dt><dd>{data.projects.length}</dd>
        </dl>
      </div>
      <div className="card">
        <h3>项目列表</h3>
        {data.projects.length === 0 ? <div className="empty">工作区内没有项目目录</div> : (
          <table>
            <thead><tr><th>项目</th><th>Git</th><th>分支</th><th>Commit</th></tr></thead>
            <tbody>
              {data.projects.map(p => (
                <tr key={p.name}>
                  <td><b>{p.name}</b></td>
                  <td>{p.is_git ? <span className="badge ok">git</span> : <span className="badge neutral">非 git</span>}</td>
                  <td>{p.branch ? <code>{p.branch}</code> : '-'}</td>
                  <td>{p.commit ? <code>{p.commit}</code> : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="hint">commit 快照已随分析任务入库；结构化代码索引（符号级检索）排期 M5。</p>
      </div>
    </>
  )
}
