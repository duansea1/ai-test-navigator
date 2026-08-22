/**
 * 离线装配前端构建依赖：从 deepseek-harness 仓库的 hoisted node_modules
 * 复制 react / react-dom / esbuild（含平台二进制）到 frontend/node_modules。
 *
 * 网络不可用时 npm install 无法完成，DSH 仓库已 pnpm install（hoisted 布局），
 * 直接复用其依赖即可满足 esbuild 打包需求。
 *
 * 用法：node scripts/setup-frontend-deps.mjs [deepseek-harness 仓库根目录]
 */
import { cp, mkdir, access } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'

const root = resolve(process.argv[2] ?? 'C:/AppsAi/deepseek-harness')
const target = resolve('node_modules')
const source = join(root, 'node_modules')

const PACKAGES = [
  'react',
  'react-dom',
  'scheduler',
  'esbuild',
  join('@esbuild', 'win32-x64'),
  join('@types', 'react'),
  join('@types', 'react-dom'),
]

async function exists(p) {
  try {
    await access(p)
    return true
  } catch {
    return false
  }
}

async function main() {
  console.log(`[setup-frontend-deps] 来源：${source}`)
  if (!existsSync(source)) throw new Error(`缺少 ${source}，请先在 deepseek-harness 内执行 pnpm install`)
  await mkdir(target, { recursive: true })
  for (const name of PACKAGES) {
    const from = join(source, name)
    const to = join(target, name)
    if (!existsSync(from)) {
      console.log(`[setup-frontend-deps] 跳过（源缺失，非必需）：${name}`)
      continue
    }
    if (await exists(to)) {
      console.log(`[setup-frontend-deps] 已存在：${name}`)
      continue
    }
    await cp(from, to, { recursive: true, dereference: true })
    console.log(`[setup-frontend-deps] 复制：${name}`)
  }
  console.log('[setup-frontend-deps] 完成')
}

await main()
