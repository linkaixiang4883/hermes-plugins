/**
 * opencode-go-usage — 编码套餐用量（OpenCode Go / Command Code GOAT）桌面状态栏插件（桌面半）。
 *
 * 芯片：  Go | GOAT [███████░░░] 53%  —— 三个窗口里最紧张的那个；颜色按三段阈值
 * 点击：  应用内详情面板（不跳转外部页面）
 * 数据：  本插件自有后端 /api/plugins/opencode-go-usage/{gate,usage}
 *        （见 plugins/opencode-go-usage/dashboard/plugin_api.py；只读、免登录；
 *          后端注册表按套餐选家：opencode-go / commandcode-goat）
 *
 * 模型门控（v1.1）：**只在使用本站套餐的模型时才显示芯片** ——
 *   · 当前模型跑在 OpenCode Go → 显示 Go 用量；跑在 Command Code（GOAT）→ 显示 GOAT 用量；
 *   · opencode Zen / 其他任何 provider → 芯片完全消失（避免误导）。
 *   判定链路：监听 host.state.model（+焦点会话）→ 调后端 /gate →
 *   后端按 ① model 前缀（仅限受支持套餐的 provider）② 会话行（state.db 的 provider）
 *   ③ 配置默认 provider 解析 → 命中注册表的 model_providers 才注册芯片。
 *   将来再加一家 = 后端加一条 ProviderSpec（前端零改动；芯片前缀/面板标题都跟后端走）。
 *
 * 纯 ESM、无构建；只允许导入 @hermes/plugin-sdk / react / react/jsx-runtime，
 * UI 一律用 jsx() 调用（本文件不会被编译，JSX 语法解析不了）。
 *
 * 开发提示：本文件是"统一包"的桌面半，源在 plugins/<id>/desktop/；
 * Electron 主进程会把它复制到 desktop-plugins/<id>/ 并打上 .hermes-package.json
 * 标记（源文件更新后需要一次 Rescan / 重开 App 触发同步，之后热重载生效）。
 */
import { haptic, host, queryClient, STATUSBAR_AREAS, usePluginI18n, useQuery } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'opencode-go-usage'
const REFRESH_MS = 300_000
const GATE_RETRY_MS = [1500, 4000] // 模型切换后会话行可能晚一拍落库 → 延迟复核

let rest = null // ctx.rest，register() 时注入
let tRef = null // ctx.i18n.t
let ctxRef = null // 插件上下文（重注册芯片用）
let forceNext = false // 手动刷新：绕过后端 60s 缓存

let chipDispose = null // 当前芯片贡献的 disposer（未命中时为 null → 芯片不存在）
let activeProviderId = null // 门控命中的用量 provider（如 opencode-go）
let gateToken = 0 // 门控异步竞态令牌
let retryTimers = []

// 与 opencode 官网 Go 面板一致的三段阈值：<50 绿 / 50–74 黄 / ≥75 红
const TONE_COLORS = ['var(--ui-green)', 'var(--ui-yellow)', 'var(--ui-red)']
const toneOf = percent => (percent >= 75 ? 2 : percent >= 50 ? 1 : 0)

function barText(percent, width = 10) {
  const pct = Math.max(0, Math.min(100, Math.round(percent || 0)))
  const filled = Math.round((pct / 100) * width)
  return '█'.repeat(filled) + '░'.repeat(width - filled)
}

/** 与 console 同款格式：`3d 5h` / `4h 20m` / `12m` */
function resetText(resetsAt) {
  const ms = new Date(resetsAt).getTime() - Date.now()
  if (!Number.isFinite(ms) || ms <= 0) return ''
  const mins = Math.ceil(ms / 60000)
  const days = Math.floor(mins / 1440)
  const hours = Math.floor((mins % 1440) / 60)
  if (days >= 1) return `${days}d ${hours}h`
  if (hours >= 1) return `${hours}h ${mins % 60}m`
  return `${mins}m`
}

/** 行数据来自后端归一化的 windows[]（{id,label,percent,status,resetsAt}）。 */
function windowsOf(list) {
  return (list || []).map(w => ({
    key: w.id,
    fallbackLabel: w.label || w.id,
    percent: Number(w.percent) || 0,
    status: w.status,
    resetsAt: w.resetsAt
  }))
}

/** 已知窗口 id 用本插件 i18n 文案；未知 id 回退后端 label（新 provider 的接入口）。 */
function windowLabel(t, win) {
  const key = `win_${win.key}`
  const translated = t(key)
  return translated === key ? win.fallbackLabel : translated
}

function fmtBalance(balance) {
  const value = balance && balance.value
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  const symbol = balance.unit === 'CNY' ? '¥' : balance.unit === 'USD' ? '$' : ''
  return `${symbol}${value.toFixed(2)}`
}

function topWindow(windows) {
  return windows.reduce((a, b) => (b.percent >= a.percent ? b : a))
}

/** 载荷是否已有可渲染数据（windows 或 balance 任一）。 */
function usableData(data) {
  if (!data || data.ok === false || !data.provider) return false
  return Boolean((data.windows && data.windows.length) || data.balance)
}

function useUsage() {
  const providerId = activeProviderId
  return useQuery({
    queryKey: [ID, 'usage', providerId || 'none'],
    enabled: Boolean(providerId),
    queryFn: () => {
      const query = `provider=${encodeURIComponent(providerId)}`
      return rest(forceNextPath(query))
    },
    refetchInterval: REFRESH_MS,
    // 桌面 App 的全局 queryClient 设了 refetchOnWindowFocus:false（lib/query-client.ts），
    // 且 React Query 的 refetchInterval 在窗口失焦时会暂停（refetchIntervalInBackground 默认 false）。
    // 不显式覆盖这两项的话：切走→轮询停；切回→不补拉；唯一触发只剩"点击面板"（挂载强制 refetch）。
    // refetchIntervalInBackground 保后台轮询，refetchOnWindowFocus 保回窗即拉（staleTime 兜底防抖）。
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    staleTime: 60_000,
    retry: 1
  })
}

function forceNextPath(query) {
  // forceNext 在下一次调用时生效一次（刷新按钮置位）
  if (forceNext) {
    forceNext = false
    return `/usage?${query}&force=1`
  }
  return `/usage?${query}`
}

function fmtTime(iso) {
  const date = new Date(iso)
  return Number.isFinite(date.getTime())
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : ''
}

function reasonText(t, error) {
  const kind = (error && error.kind) || 'unknown'
  const map = {
    no_key: 'errNoKey',
    pool_unreadable: 'errPool',
    internal: 'errInternal',
    network: 'errNetwork',
    timeout: 'errTimeout',
    unauthorized: 'errUnauthorized',
    entitlement: 'errEntitlement',
    malformed: 'errMalformed',
    unknown_provider: 'errProvider'
  }
  return t(map[kind] || 'errUnknown')
}

function reasonFromQuery(t, query) {
  if (query.isError) return t('errBackend')
  return reasonText(t, query.data && query.data.error)
}

// ---------------------------------------------------------------------------
// 模型门控：/gate 判定 + 芯片的动态注册/注销
// ---------------------------------------------------------------------------

function clearGateRetries() {
  retryTimers.forEach(timer => clearTimeout(timer))
  retryTimers = []
}

async function resolveGate() {
  if (!rest) return null
  const model = String(host.state.model.get() || '')
  const session = String(host.state.focusedStoredSessionId.get() || '')
  const params = new URLSearchParams()
  if (model) params.set('model', model)
  if (session) params.set('session', session)
  try {
    return await rest(`/gate?${params.toString()}`)
  } catch (error) {
    return null // 后端不可达 → 视为未命中（隐藏比误导好）；模型再变时会重试
  }
}

function applyGate(decision, token) {
  if (token !== gateToken) return
  const providerId = decision && decision.ok && decision.matched ? decision.provider : null
  if (providerId === activeProviderId && chipDispose) return // 无变化
  if (chipDispose) {
    chipDispose()
    chipDispose = null
  }
  activeProviderId = providerId
  if (providerId && ctxRef) chipDispose = registerChip()
}

async function syncGate() {
  const token = ++gateToken
  clearGateRetries()
  applyGate(await resolveGate(), token)
  for (const delay of GATE_RETRY_MS) {
    retryTimers.push(
      setTimeout(async () => {
        if (token !== gateToken) return
        applyGate(await resolveGate(), token)
      }, delay)
    )
  }
}

/** 注册芯片贡献；返回 disposer。仅在门控命中时调用。 */
function registerChip() {
  // 芯片提示语按当前套餐选词（opencode-go / commandcode-goat…）；未知 id 用通用兜底
  const titleKey = `chipTitle_${activeProviderId}`
  const toggleKey = `chipToggle_${activeProviderId}`
  const pick = (specific, generic) => {
    const translated = tRef(specific)
    return translated === specific ? tRef(generic) : translated
  }
  return ctxRef.register({
    id: 'chip',
    area: STATUSBAR_AREAS.right,
    order: 130,
    data: {
      id: ID, // 唯一 id：右键"显示/隐藏"菜单与持久化都用它
      label: jsx(ChipLabel, {}), // 动态前缀（provider.short，缺省 'Go'）
      detail: jsx(ChipDetail, {}),
      title: pick(titleKey, 'chipTitle'),
      menuContent: () => jsx(UsagePanel, {}),
      menuAlign: 'end',
      menuClassName: 'w-auto border-(--ui-stroke-secondary) p-0',
      toggleLabel: pick(toggleKey, 'chipToggle'),
      variant: 'menu'
    }
  })
}

/** 芯片前缀：动态取 provider.short（后端注册表换家时自动跟随）；数据未到时先留空。 */
function ChipLabel() {
  const query = useUsage()
  const short = (query.data && query.data.provider && query.data.provider.short) || ''
  return jsx('span', { children: short })
}

/** 芯片的数值部分：windows → `[███░░░░░░░] 53%`；balance → `$12.34`。 */
function ChipDetail() {
  const query = useUsage()
  if (query.isPending) return jsx('span', { children: '…' })
  const data = query.data
  if (!usableData(data)) return jsx('span', { className: 'opacity-70', children: '—' })
  if (data.provider.kind === 'balance') {
    return jsx('span', { className: 'tabular-nums', children: fmtBalance(data.balance) })
  }
  const windows = windowsOf(data.windows)
  const top = topWindow(windows)
  const limited = windows.some(w => w.status === 'rate-limited')
  return jsxs('span', {
    className: 'tabular-nums',
    style: { color: TONE_COLORS[toneOf(top.percent)] },
    children: ['[', barText(top.percent), `] ${top.percent}%`, limited ? ' ⚠' : '']
  })
}

function WindowRow({ t, win }) {
  const color = TONE_COLORS[toneOf(win.percent)]
  const rightChildren = [jsx('span', { style: { color }, children: `${win.percent}%` }, 'pct')]
  if (win.resetsAt) {
    const reset = resetText(win.resetsAt)
    if (reset) {
      rightChildren.push(
        jsx(
          'span',
          {
            className: 'text-(--ui-text-quaternary)',
            children: ` · ${t('resetIn', reset)}`
          },
          'reset'
        )
      )
    }
  }
  return jsxs(
    'div',
    {
      className: 'flex flex-col gap-1',
      children: [
        jsxs(
          'div',
          {
            className: 'flex items-center justify-between gap-2',
            children: [
              jsxs(
                'span',
                {
                  className: 'flex min-w-0 items-center gap-2',
                  children: [
                    jsx('span', { className: 'size-2 shrink-0 rounded-[2px]', style: { background: color } }, 'dot'),
                    jsx(
                      'span',
                      { className: 'truncate text-(--ui-text-tertiary)', children: windowLabel(t, win) },
                      'label'
                    )
                  ]
                },
                'left'
              ),
              jsxs('span', { className: 'shrink-0 tabular-nums', children: rightChildren }, 'right')
            ]
          },
          'head'
        ),
        jsx(
          'span',
          {
            className: 'block h-1.5 w-full overflow-hidden rounded-full bg-(--ui-stroke-tertiary)',
            children: jsx('span', {
              className: 'block h-full rounded-full',
              style: { width: `${Math.min(100, win.percent)}%`, background: color }
            })
          },
          'bar'
        )
      ]
    },
    win.key
  )
}

function UsagePanel() {
  const t = usePluginI18n(ID)
  const query = useUsage()
  const data = query.data
  const ready = usableData(data)
  const isBalance = ready && data.provider.kind === 'balance'
  const windows = ready && !isBalance ? windowsOf(data.windows) : null
  const top = windows ? topWindow(windows) : null

  const refresh = () => {
    haptic('tap')
    forceNext = true
    queryClient.invalidateQueries({ queryKey: [ID, 'usage', activeProviderId || 'none'] })
  }

  const title = ready && data.provider.display ? data.provider.display : t('panelTitle')

  const body = []
  if (!data && query.isPending) {
    body.push(jsx('p', { className: 'text-(--ui-text-tertiary)', children: t('loading') }, 'loading'))
  } else if (data && data.ok === false) {
    body.push(
      jsx('p', { className: 'text-(--ui-text-tertiary)', children: reasonText(t, data.error) }, 'err')
    )
  } else if (query.isError && !data) {
    body.push(jsx('p', { className: 'text-(--ui-text-tertiary)', children: t('errBackend') }, 'errq'))
  } else if (!ready) {
    body.push(
      jsx(
        'p',
        { className: 'text-(--ui-text-tertiary)', children: reasonFromQuery(t, query) },
        'errk'
      )
    )
  } else {
    const key = data.key
    if (key && key.error) {
      body.push(
        jsx(
          'p',
          { className: 'text-(--ui-text-tertiary)', children: reasonText(t, key.error) },
          'keyerr'
        )
      )
    } else if (isBalance) {
      body.push(
        jsx(
          'p',
          {
            className: 'text-[1.05rem] tabular-nums text-foreground',
            children: fmtBalance(data.balance)
          },
          'balance'
        )
      )
    } else {
      windows.forEach(win => body.push(jsx(WindowRow, { t, win }, `row-${win.key}`)))
    }
    const notes = []
    if (key && key.fallback) notes.push(t('noteFallback'))
    if (key && key.poolStatus === 'exhausted') {
      const thaw = key.cooldownUntil ? fmtTime(new Date(key.cooldownUntil * 1000).toISOString()) : ''
      notes.push(t('noteCooling', thaw || '—'))
    }
    if (notes.length) {
      body.push(
        jsx('p', { className: 'text-(--ui-text-quaternary)', children: notes.join(' · ') }, 'notes')
      )
    }
  }

  const footerLeft = data && data.fetchedAt ? t('updatedAt', fmtTime(data.fetchedAt)) : ''
  const footerRight = []
  if (data && data.poolSize) {
    footerRight.push(
      jsx('span', { className: 'text-(--ui-text-quaternary)', children: t('poolSize', String(data.poolSize)) }, 'pool')
    )
  }
  footerRight.push(
    jsx(
      'button',
      {
        type: 'button',
        className:
          'rounded px-1.5 py-0.5 text-(--ui-text-tertiary) transition-colors hover:bg-(--chrome-action-hover) hover:text-foreground',
        onClick: refresh,
        children: query.isFetching ? t('refreshing') : t('refresh')
      },
      'refresh'
    )
  )

  const headerRight = isBalance
    ? null
    : top
      ? jsx(
          'span',
          {
            className: 'text-[0.6875rem] tabular-nums',
            style: { color: TONE_COLORS[toneOf(top.percent)] },
            children: `${top.percent}%`
          },
          'top'
        )
      : null

  return jsxs('div', {
    className: 'flex w-72 flex-col gap-3 p-3 text-[0.75rem]',
    'data-slot': 'opencode-go-usage-panel',
    children: [
      jsxs(
        'div',
        {
          className: 'flex items-baseline justify-between gap-2',
          children: [
            jsx('p', { className: 'font-medium text-foreground', children: title }, 'title'),
            headerRight
          ]
        },
        'header'
      ),
      ...body,
      jsxs(
        'div',
        {
          className:
            'flex items-center justify-between gap-2 border-t border-(--ui-stroke-tertiary) pt-2 text-[0.6875rem]',
          children: [
            jsx('span', { className: 'text-(--ui-text-quaternary)', children: footerLeft }, 'updated'),
            jsxs('span', { className: 'flex items-center gap-2', children: footerRight }, 'actions')
          ]
        },
        'footer'
      )
    ]
  })
}

const BUNDLES = {
  en: {
    chipTitle: 'Coding plan usage — click for details',
    'chipTitle_opencode-go': 'OpenCode Go usage — click for details',
    'chipTitle_commandcode-goat': 'Command Code GOAT usage — click for details',
    chipToggle: 'Coding plan usage',
    'chipToggle_opencode-go': 'OpenCode Go usage',
    'chipToggle_commandcode-goat': 'Command Code GOAT usage',
    panelTitle: 'Usage',
    win_rolling: 'Rolling 5h',
    win_weekly: 'Weekly',
    win_monthly: 'Monthly',
    loading: 'Loading…',
    refresh: 'Refresh',
    refreshing: 'Refreshing…',
    updatedAt: value => `Updated ${value}`,
    poolSize: value => `${value} key(s) in pool`,
    resetIn: value => `resets in ${value}`,
    noteFallback: 'Main key failed — showing the next available key',
    noteCooling: value => `All keys cooling down; earliest thaw ${value}`,
    errNoKey: 'No API key found (credential pool and .env are empty)',
    errPool: 'Could not read the credential pool (auth.json)',
    errInternal: 'Backend internal error',
    errNetwork: 'Network error while querying the provider',
    errTimeout: 'Query to the provider timed out',
    errUnauthorized: 'Key rejected (401) — invalid or deleted',
    errEntitlement: 'No subscription for this key (403)',
    errMalformed: 'Unexpected response from the provider',
    errProvider: 'Unknown provider id',
    errBackend: 'Backend not reachable — add the plugin to plugins.enabled and restart the backend',
    errUnknown: 'Unknown error'
  },
  zh: {
    chipTitle: '编码套餐用量 — 点击查看详情',
    'chipTitle_opencode-go': 'OpenCode Go 用量 — 点击查看详情',
    'chipTitle_commandcode-goat': 'Command Code GOAT 用量 — 点击查看详情',
    chipToggle: '编码套餐用量',
    'chipToggle_opencode-go': 'OpenCode Go 用量',
    'chipToggle_commandcode-goat': 'Command Code GOAT 用量',
    panelTitle: '用量',
    win_rolling: '滚动 5h',
    win_weekly: '周',
    win_monthly: '月',
    loading: '加载中…',
    refresh: '刷新',
    refreshing: '刷新中…',
    updatedAt: value => `更新于 ${value}`,
    poolSize: value => `池内 ${value} 把 key`,
    resetIn: value => `${value} 后重置`,
    noteFallback: '主力 key 查询失败 — 已顺延到下一把可用 key',
    noteCooling: value => `所有 key 冷却中；最早 ${value} 解冻`,
    errNoKey: '找不到 API key（凭证池与 .env 均为空）',
    errPool: '读取凭证池（auth.json）失败',
    errInternal: '后端内部错误',
    errNetwork: '访问提供商网络错误',
    errTimeout: '访问提供商超时',
    errUnauthorized: 'key 被拒（401）— 无效或已删除',
    errEntitlement: '该 key 没有对应订阅（403）',
    errMalformed: '提供商返回了预期外的内容',
    errProvider: '未知的提供商 id',
    errBackend: '后端不可达 — 确认已加入 plugins.enabled 并重启后端后生效',
    errUnknown: '未知错误'
  }
}

export default {
  id: ID, // 必须与目录名一致
  name: '编码套餐用量（Go / GOAT）',
  register(ctx) {
    ctxRef = ctx
    rest = path => ctx.rest(path)
    ctx.i18n.register(BUNDLES)
    tRef = ctx.i18n.t

    // 模型门控：模型 / 焦点会话变化 → 重新判定芯片是否该出现
    const unsubscribeModel = host.state.model.subscribe(() => {
      void syncGate()
    })
    const unsubscribeSession = host.state.focusedStoredSessionId.subscribe(() => {
      void syncGate()
    })

    ctx.onDispose(() => {
      unsubscribeModel()
      unsubscribeSession()
      clearGateRetries()
      if (chipDispose) {
        chipDispose()
        chipDispose = null
      }
      activeProviderId = null
    })

    void syncGate() // subscribe 通常会立即回调一次，这里再兜底一次（令牌去重）
  }
}
