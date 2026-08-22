/**
 * 前端构建：esbuild 打包 React + TSX 单页应用到 frontend/dist。
 *
 * 产物：
 *   dist/index.html        （由源 index.html 复制）
 *   dist/assets/app.js     （bundle + minify，JSX 自动转换）
 *   dist/assets/styles.css （源样式复制）
 *
 * 用法：node scripts/build-frontend.mjs（在 frontend/ 目录下经 npm run build 调用）
 */
import { cp, mkdir, rm } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { createRequire } from 'node:module'

const src = process.cwd() // 经 npm run build 调用时 cwd = frontend/
const require = createRequire(join(src, 'package.json')) // 依赖从 frontend/node_modules 解析
const dist = join(src, 'dist')

async function main() {
  const esbuild = require('esbuild')
  await rm(dist, { recursive: true, force: true })
  await mkdir(join(dist, 'assets'), { recursive: true })

  await esbuild.build({
    entryPoints: [join(src, 'src', 'main.tsx')],
    bundle: true,
    minify: true,
    format: 'iife',
    target: ['es2020'],
    jsx: 'automatic',
    outfile: join(dist, 'assets', 'app.js'),
    legalComments: 'none',
    logLevel: 'info',
  })

  await cp(join(src, 'index.html'), join(dist, 'index.html'))
  await cp(join(src, 'src', 'styles.css'), join(dist, 'assets', 'styles.css'))
  console.log(`[build-frontend] 完成：${dist}`)
}

await main()
