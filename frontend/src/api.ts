/** REST / SSE 客户端。 */
export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
  return res.json() as Promise<T>
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
  return res.json() as Promise<T>
}

/** 消费 SSE 流（data: 行），逐事件回调。 */
export async function streamSse(path: string, onEvent: (event: any) => void): Promise<void> {
  const res = await fetch(path)
  if (!res.ok || !res.body) throw new Error(`${path}: HTTP ${res.status}`)
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''
    for (const block of blocks) {
      const line = block.split('\n').find(l => l.startsWith('data: '))
      if (line) onEvent(JSON.parse(line.slice(6)))
    }
  }
}

/** POST 表单并消费 SSE 流（/api/chat/stream：意图帧 + delta 增量 + done 终帧）。 */
export async function postFormSse(path: string, form: FormData,
  onEvent: (event: any) => void): Promise<void> {
  const res = await fetch(path, { method: 'POST', body: form })
  if (!res.ok || !res.body) throw new Error(`${path}: HTTP ${res.status}`)
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''
    for (const block of blocks) {
      const line = block.split('\n').find(l => l.startsWith('data: '))
      if (line) onEvent(JSON.parse(line.slice(6)))
    }
  }
}

/** 上传分析表单（需求分析页）。 */
export async function uploadAnalyze(form: FormData): Promise<any> {
  const res = await fetch('/api/analyze', { method: 'POST', body: form })
  return res.json()
}

/** 通用表单 POST（multipart）。 */
export async function postForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(path, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
  return res.json() as Promise<T>
}

/** 通用表单 PATCH（multipart，会话重命名等）。 */
export async function patchForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(path, { method: 'PATCH', body: form })
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
  return res.json() as Promise<T>
}

/** 通用 DELETE。 */
export async function delJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { method: 'DELETE' })
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
  return res.json() as Promise<T>
}
