/**
 * 构建 DSH Runtime 的 Windows node 载体（离线模式）。
 *
 * 网络不可用时 pnpm deploy 无法完成 registry 元数据/attestations 校验，
 * 因此改为：`pnpm list --prod --depth Infinity` 提取 dsh-jsonrpc-agent-pkg
 * 的生产依赖闭包清单，从 workspace hoisted node_modules 直接复制（dereference
 * workspace 链接），产物与官方 deployStaging 等价。
 *
 * 前置：deepseek-harness 仓库内已执行 `pnpm install`（hoisted 布局）与 `pnpm run build`。
 * 用法：node scripts/build-dsh-node-carrier.mjs [deepseek-harness 仓库根目录]
 */
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { cp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { join, relative, resolve, sep } from 'node:path'

const root = resolve(process.argv[2] ?? 'C:/AppsAi/deepseek-harness')
const DEPLOY_ROOT_PACKAGE = 'dsh-jsonrpc-agent-pkg'
const STAGING = join(root, 'python/sdk-runtime/src/deepseek_harness_runtime/runtime/node')
const ROOT_NODE_MODULES = join(root, 'node_modules')
const DEPLOY_MANIFEST = join(root, 'python/sdk-runtime/package.json')
const ENTRY = 'node_modules/@deepseek-ai/dsh-sdk-jsonrpc-demo/lib/packaged-bin.js'

function log(msg) { console.log(`[dsh-node-carrier] ${msg}`) }

function pnpm(args) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn('pnpm.cmd', args, { cwd: root, stdio: ['ignore', 'pipe', 'inherit'], shell: true, env: { ...process.env, CI: 'true' } })
    let stdout = ''
    child.stdout.on('data', d => { stdout += d })
    child.once('error', e => reject(new Error(`pnpm spawn 失败: ${e.message}`)))
    child.once('exit', code => code === 0 ? resolvePromise(stdout) : reject(new Error(`pnpm ${args.join(' ')} exit ${code}`)))
  })
}

async function closureNames() {
  const out = await pnpm(['--filter', DEPLOY_ROOT_PACKAGE, 'list', '--prod', '--depth', 'Infinity', '--json'])
  const tree = JSON.parse(out)
  const names = new Set()
  const walk = deps => {
    for (const [name, info] of Object.entries(deps ?? {})) {
      names.add(name)
      walk(info.dependencies)
    }
  }
  walk(tree[0]?.dependencies)
  if (names.size === 0) throw new Error('闭包为空：pnpm list 未返回依赖树')
  return [...names].sort()
}

const DEPLOY_SOURCE_NODE_MODULES = join(root, 'python/sdk-runtime/node_modules')
/** 其他平台/架构的 optional 二进制包（Windows x64 载体不需要，未安装是正常的）。 */
const FOREIGN_PLATFORM = /(darwin|linux|freebsd|openbsd|netbsd|android|aix|sunos|win32-ia32|win32-arm64|win32-x86)/

/** 可选扩展包（不在 dsh-jsonrpc-agent-pkg 生产闭包内，满血组合需要）：
 * workspace 源码包（已构建 lib/ 产物），按 package.json 的 name 落位。 */
const EXTRA_WORKSPACE_PACKAGES = ['packages/subagent/subagent-claude-code', 'packages/subagent/tool-subagent-report']
/** 可选扩展的 hoisted 第三方依赖。 */
const EXTRA_HOISTED_PACKAGES = ['@anthropic-ai/claude-agent-sdk', '@anthropic-ai/sdk']

async function copyPackage(source, name) {
  // 跳过包内嵌套 node_modules：hoisted 顶层的 junction 循环链接会导致 ELOOP，
  // 且平铺布局下 Node 向上解析即可命中 STAGING/node_modules 顶层。
  const filter = srcPath => !relative(source, srcPath).split(sep).includes('node_modules')
  await cp(source, join(STAGING, 'node_modules', name), { recursive: true, dereference: true, filter })
}

async function main() {
  log(`仓库：${root}`)
  log(`目标：${STAGING}`)
  if (!existsSync(ROOT_NODE_MODULES)) throw new Error(`缺少 ${ROOT_NODE_MODULES}，请先在 deepseek-harness 内执行 pnpm install`)

  log('提取生产依赖闭包 ...')
  const names = await closureNames()
  log(`闭包 ${names.length} 个包`)

  await rm(STAGING, { recursive: true, force: true })
  await mkdir(join(STAGING, 'node_modules'), { recursive: true })

  const missing = []
  for (const name of names) {
    // hoisted 布局：第三方包在 root，workspace 直接依赖被 hoist 到 sdk-runtime/node_modules
    const source = [join(ROOT_NODE_MODULES, name), join(DEPLOY_SOURCE_NODE_MODULES, name)].find(existsSync)
    if (!source) {
      if (!FOREIGN_PLATFORM.test(name)) missing.push(name)
      continue
    }
    await copyPackage(source, name)
  }
  if (missing.length > 0) log(`警告：${missing.length} 个包缺失：${missing.join(', ')}`)

  // 满血扩展包：Claude Code 子代理 provider（claude CLI 由最终机器提供）
  for (const rel of EXTRA_WORKSPACE_PACKAGES) {
    const pkgDir = join(root, rel)
    const pkgJson = JSON.parse(await readFile(join(pkgDir, 'package.json'), 'utf8'))
    await copyPackage(pkgDir, pkgJson.name)
    log(`扩展（workspace）：${pkgJson.name}`)
  }
  for (const name of EXTRA_HOISTED_PACKAGES) {
    const source = join(ROOT_NODE_MODULES, name)
    if (!existsSync(source)) throw new Error(`扩展包缺失：${source}`)
    await copyPackage(source, name)
    log(`扩展（hoisted）：${name}`)
  }

  const manifest = JSON.parse(await readFile(DEPLOY_MANIFEST, 'utf8'))
  delete manifest.scripts
  await writeFile(join(STAGING, 'package.json'), JSON.stringify(manifest, null, 2))

  const entry = join(STAGING, ENTRY)
  if (!existsSync(entry)) throw new Error(`入口缺失：${entry}（请先 pnpm run build 生成 lib 产物）`)
  log(`完成，入口：${entry}`)
  log('使用方式：环境变量 DSH_RUNTIME_MODE=node')
}

await main()
