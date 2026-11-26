import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type {
  ActionResult,
  ClaimResult,
  ConfirmDeliveryResult,
  DeliveryConfirmation,
  EntryRow,
  GenerateResult,
  OverviewResult,
  PageResult,
  ReceivePreview,
  SignoffResult,
} from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

/* ── 数据导出：交付确认 ───────────────────────── */

export async function getDeliveryConfirmation(id: number): Promise<DeliveryConfirmation> {
  const response = await request(`/api/export_dataset/${id}/delivery`)
  if (!response.ok) throw new Error('交付确认读取失败')
  return await response.json()
}

export async function generateExport(
  id: number,
  payload: { rows?: number; data?: Record<string, unknown>[] },
): Promise<GenerateResult> {
  const response = await request(`/api/export_dataset/${id}/generate`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return await response.json()
}

export async function confirmDelivery(
  id: number,
  payload: { batch_no?: number; pipe_id?: number },
): Promise<ConfirmDeliveryResult> {
  const response = await request(`/api/export_dataset/${id}/delivery/confirm`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return await response.json()
}

/* ── 投递管道：接收预览与签收 ───────────────────── */

export async function getReceivePreview(id: number): Promise<ReceivePreview> {
  const response = await request(`/api/delivery_pipe/${id}/inbox`)
  if (!response.ok) throw new Error('接收预览读取失败')
  return await response.json()
}

export async function claimManifest(pipeId: number, manifestId: string): Promise<ClaimResult> {
  const response = await request(`/api/delivery_pipe/${pipeId}/inbox/${manifestId}/claim`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
  return await response.json()
}

export async function signoffManifest(
  pipeId: number,
  manifestId: string,
  payload: { processed_file?: string },
): Promise<SignoffResult> {
  const response = await request(`/api/delivery_pipe/${pipeId}/inbox/${manifestId}/signoff`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return await response.json()
}
