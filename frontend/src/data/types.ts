/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

/** 数据导出：交付确认视图 */
export type ExportBatch = {
  batch_no: number
  rows: number
  row_source: 'actual' | 'simulated'
  file_path: string
  generated_at: string
  empty: boolean
  delivered: boolean
  manifest_id: string | null
}

export type DeliveryManifest = {
  manifest_id: string
  export_id: number
  batch_no: number
  rows: number
  file_path: string
  confirmed_at: string
  pipe_id: number | null
  pipe_status: string
  receipt_id: string | null
}

export type DeliveryConfirmation = {
  ok: boolean
  entry_id: number
  任务编号: string
  status: string
  generated: boolean
  actual_rows: number | null
  current_batch_no: number | null
  batches: ExportBatch[]
  deliveries: DeliveryManifest[]
}

export type ConfirmDeliveryResult = {
  ok: boolean
  reason: string
  reused?: boolean
  manifest: DeliveryManifest | null
}

export type GenerateResult = {
  ok: boolean
  message: string
  batch: ExportBatch | null
}

/** 投递管道：接收预览 */
export type InboxRecord = {
  manifest_id: string
  export_id: number
  batch_no: number
  rows: number
  file_path: string
  received_at: string
  status: string
  claimed_at: string | null
  receipt_id: string | null
}

export type Receipt = {
  receipt_id: string
  manifest_id: string
  export_id: number | null
  batch_no: number
  rows: number
  file_path: string
  signed_at: string
  processed_file: string
  file_mismatch: boolean
}

export type ReceivePreview = {
  ok: boolean
  entry_id: number
  配置编号: string
  inbox: InboxRecord[]
  pending_claim: InboxRecord[]
  pending_signoff: InboxRecord[]
  receipts: Receipt[]
}

export type ClaimResult = {
  ok: boolean
  reason: string
  record: InboxRecord | null
}

export type SignoffResult = {
  ok: boolean
  reason: string
  reused?: boolean
  receipt: Receipt | null
}
