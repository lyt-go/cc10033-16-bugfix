<template>
  <section class="inbox-section" data-testid="delivery-inbox-section">
    <h3 class="section-title">接收预览</h3>
    <p class="section-desc">
      接收清单与导出方交付清单一一对应；已领取未答复的列入签收待办，回执始终指向原批次。
    </p>

    <article
      v-for="item in previews"
      :key="item.entry_id"
      class="inbox-card"
      :data-testid="`inbox-card-${item.entry_id}`"
    >
      <header class="card-head">
        <strong>{{ item.配置编号 }}</strong>
        <span class="badge">待领取 {{ item.pending_claim.length }}</span>
        <span class="badge warn" :data-testid="`pending-signoff-${item.entry_id}`">
          签收待办 {{ item.pending_signoff.length }} 笔 / {{ signoffRows(item) }} 行
        </span>
      </header>

      <table v-if="item.inbox.length" class="data-table compact">
        <thead>
          <tr>
            <th>清单号</th>
            <th>批次</th>
            <th>条数</th>
            <th>文件路径</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="rec in item.inbox"
            :key="rec.manifest_id"
            :data-testid="`inbox-${item.entry_id}-${rec.manifest_id}`"
          >
            <td>{{ rec.manifest_id }}</td>
            <td>#{{ rec.batch_no }}</td>
            <td>{{ rec.rows }}</td>
            <td>{{ rec.file_path }}</td>
            <td>{{ rec.status }}</td>
            <td class="row-actions">
              <button
                v-if="rec.status === '待领取'"
                class="link"
                type="button"
                :data-testid="`claim-${item.entry_id}-${rec.manifest_id}`"
                @click="claim(item.entry_id, rec.manifest_id)"
              >
                领取
              </button>
              <template v-if="rec.status !== '已签收'">
                <input
                  v-model="processedFiles[rec.manifest_id]"
                  class="inline-input"
                  :data-testid="`processed-file-${item.entry_id}-${rec.manifest_id}`"
                  placeholder="实际处理文件（可空）"
                />
                <button
                  class="link"
                  type="button"
                  :data-testid="`signoff-${item.entry_id}-${rec.manifest_id}`"
                  @click="signoff(item.entry_id, rec.manifest_id)"
                >
                  签收
                </button>
              </template>
              <span v-else>回执 {{ rec.receipt_id }}</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-state">接收列表为空：等待数据导出确认交付。</p>

      <ul v-if="item.receipts.length" class="receipt-list">
        <li
          v-for="rc in item.receipts"
          :key="rc.receipt_id"
          :data-testid="`receipt-${item.entry_id}-${rc.receipt_id}`"
        >
          回执 {{ rc.receipt_id }} · 清单 {{ rc.manifest_id }} · 批次 #{{ rc.batch_no }} ·
          {{ rc.rows }} 行 · {{ rc.file_path }}
          <span v-if="rc.file_mismatch" class="badge warn">
            实际处理文件不符：{{ rc.processed_file }}
          </span>
        </li>
      </ul>
    </article>

    <p v-if="message" class="status-text" data-testid="inbox-message">{{ message }}</p>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

import {
  claimManifest,
  getReceivePreview,
  signoffManifest,
} from '@/api/backend-service'
import type { EntryRow, ReceivePreview } from '@/data/types'

const props = defineProps<{ rows: EntryRow[] }>()
const emit = defineEmits<{ changed: [] }>()

const previews = ref<ReceivePreview[]>([])
const processedFiles = ref<Record<string, string>>({})
const message = ref('')

async function load() {
  previews.value = await Promise.all(
    props.rows.map((row) => getReceivePreview(Number(row.id))),
  )
}

function signoffRows(item: ReceivePreview): number {
  return item.pending_signoff.reduce((sum, rec) => sum + rec.rows, 0)
}

async function claim(pipeId: number, manifestId: string) {
  message.value = ''
  try {
    const result = await claimManifest(pipeId, manifestId)
    if (!result.ok) throw new Error(result.reason)
    message.value = `已领取：${manifestId}`
    await load()
    emit('changed')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '领取失败'
  }
}

async function signoff(pipeId: number, manifestId: string) {
  message.value = ''
  try {
    const processed = (processedFiles.value[manifestId] ?? '').trim()
    const result = await signoffManifest(pipeId, manifestId, {
      processed_file: processed || undefined,
    })
    if (!result.ok) throw new Error(result.reason)
    message.value = result.reused
      ? `${result.reason}：${result.receipt?.receipt_id ?? ''}`
      : `已签收：${result.receipt?.receipt_id ?? ''}（${result.receipt?.rows ?? 0} 行）`
    await load()
    emit('changed')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '签收失败'
  }
}

watch(() => props.rows, () => void load(), { immediate: true, deep: true })
</script>

<style scoped>
.inbox-section {
  margin-top: 1.5rem;
  border-top: 1px solid var(--line, #d8dee9);
  padding-top: 1rem;
}
.section-title {
  margin: 0 0 0.25rem;
  font-size: 1.05rem;
}
.section-desc {
  margin: 0 0 0.75rem;
  color: #5b6472;
  font-size: 0.85rem;
}
.inbox-card {
  border: 1px solid #d8dee9;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  margin-bottom: 0.75rem;
  background: #fbfcfe;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}
.badge {
  border: 1px solid #c3ccd9;
  border-radius: 999px;
  padding: 0.05rem 0.6rem;
  font-size: 0.78rem;
  color: #414b5c;
}
.badge.warn {
  border-color: #c98a1b;
  color: #c98a1b;
}
.data-table.compact {
  font-size: 0.85rem;
}
.row-actions {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.inline-input {
  width: 10rem;
  padding: 0.2rem 0.45rem;
  border: 1px solid #c3ccd9;
  border-radius: 6px;
}
.receipt-list {
  margin: 0.5rem 0 0;
  padding-left: 1.2rem;
  font-size: 0.85rem;
  color: #414b5c;
}
.status-text {
  color: #2f5d9e;
  font-size: 0.85rem;
}
</style>
