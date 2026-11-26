<template>
  <section class="delivery-section" data-testid="export-delivery-section">
    <h3 class="section-title">交付确认</h3>
    <p class="section-desc">
      按批次核对实际行数与交付清单；空产物与内容未生成分别标注，重复确认同一批次不会换成最新一版。
    </p>

    <article
      v-for="item in confirmations"
      :key="item.entry_id"
      class="delivery-card"
      :data-testid="`delivery-card-${item.entry_id}`"
    >
      <header class="card-head">
        <strong>{{ item.任务编号 }}</strong>
        <span class="badge">{{ item.status }}</span>
        <span v-if="!item.generated" class="badge muted" :data-testid="`not-generated-${item.entry_id}`">
          内容未生成
        </span>
        <span v-else-if="item.actual_rows === 0" class="badge warn" :data-testid="`empty-artifact-${item.entry_id}`">
          空产物 · 0 行
        </span>
        <span v-else class="badge ok" :data-testid="`actual-rows-${item.entry_id}`">
          实际行数 {{ item.actual_rows }}
        </span>
      </header>

      <div class="card-actions">
        <input
          v-model="generateRows[item.entry_id]"
          class="inline-input"
          :data-testid="`generate-rows-${item.entry_id}`"
          placeholder="模拟条数（可空）"
        />
        <button
          class="btn"
          type="button"
          :data-testid="`generate-${item.entry_id}`"
          @click="generate(item.entry_id)"
        >
          {{ item.generated ? '重新生成新版' : '生成产物' }}
        </button>
        <input
          v-model="pipeIds[item.entry_id]"
          class="inline-input"
          :data-testid="`pipe-id-${item.entry_id}`"
          placeholder="投递管道ID（可空）"
        />
        <RouterLink class="link" to="/delivery_pipe" :data-testid="`goto-pipe-${item.entry_id}`">
          前往投递管道核对接收预览
        </RouterLink>
      </div>

      <table v-if="item.generated" class="data-table compact">
        <thead>
          <tr>
            <th>批次</th>
            <th>行数</th>
            <th>计数来源</th>
            <th>文件路径</th>
            <th>生成时间</th>
            <th>交付状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="batch in item.batches"
            :key="batch.batch_no"
            :data-testid="`batch-${item.entry_id}-${batch.batch_no}`"
          >
            <td>#{{ batch.batch_no }}</td>
            <td>{{ batch.empty ? '0（空产物）' : batch.rows }}</td>
            <td>{{ batch.row_source === 'actual' ? '实际输入' : '模拟计数' }}</td>
            <td>{{ batch.file_path }}</td>
            <td>{{ batch.generated_at }}</td>
            <td>
              <span v-if="batch.delivered">已确认 · {{ batch.manifest_id }}</span>
              <span v-else>待确认</span>
            </td>
            <td>
              <button
                class="link"
                type="button"
                :data-testid="`confirm-${item.entry_id}-${batch.batch_no}`"
                @click="confirm(item.entry_id, batch.batch_no)"
              >
                {{ batch.delivered ? '重试确认' : '确认交付' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-state">
        内容未生成：请先生成导出产物；空产物确认后条数为 0。
      </p>

      <ul v-if="item.deliveries.length" class="manifest-list">
        <li
          v-for="m in item.deliveries"
          :key="m.manifest_id"
          :data-testid="`manifest-${item.entry_id}-${m.manifest_id}`"
        >
          清单 {{ m.manifest_id }} · 批次 #{{ m.batch_no }} · {{ m.rows }} 行 ·
          {{ m.file_path }} · 管道状态 {{ m.pipe_status }}
          <span v-if="m.receipt_id"> · 回执 {{ m.receipt_id }}</span>
        </li>
      </ul>
    </article>

    <p v-if="message" class="status-text" data-testid="delivery-message">{{ message }}</p>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

import {
  confirmDelivery,
  generateExport,
  getDeliveryConfirmation,
} from '@/api/backend-service'
import type { DeliveryConfirmation, EntryRow } from '@/data/types'

const props = defineProps<{ rows: EntryRow[] }>()
const emit = defineEmits<{ changed: [] }>()

const confirmations = ref<DeliveryConfirmation[]>([])
const generateRows = ref<Record<number, string>>({})
const pipeIds = ref<Record<number, string>>({})
const message = ref('')

async function load() {
  confirmations.value = await Promise.all(
    props.rows.map((row) => getDeliveryConfirmation(Number(row.id))),
  )
}

function parsePipeId(entryId: number): number | undefined {
  const raw = (pipeIds.value[entryId] ?? '').trim()
  if (!raw) return undefined
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : undefined
}

async function generate(entryId: number) {
  message.value = ''
  try {
    const raw = (generateRows.value[entryId] ?? '').trim()
    const payload = raw ? { rows: Number(raw) } : {}
    const result = await generateExport(entryId, payload)
    if (!result.ok) throw new Error(result.message)
    message.value = result.message
    await load()
    emit('changed')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '生成失败'
  }
}

async function confirm(entryId: number, batchNo: number) {
  message.value = ''
  try {
    const result = await confirmDelivery(entryId, {
      batch_no: batchNo,
      pipe_id: parsePipeId(entryId),
    })
    if (!result.ok) throw new Error(result.reason)
    message.value = result.reused
      ? `${result.reason}：${result.manifest?.manifest_id ?? ''}`
      : `已确认交付：${result.manifest?.manifest_id ?? ''}（${result.manifest?.rows ?? 0} 行）`
    await load()
    emit('changed')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '确认交付失败'
  }
}

watch(() => props.rows, () => void load(), { immediate: true, deep: true })
</script>

<style scoped>
.delivery-section {
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
.delivery-card {
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
.badge.ok {
  border-color: #2f9e6e;
  color: #2f9e6e;
}
.badge.warn {
  border-color: #c98a1b;
  color: #c98a1b;
}
.badge.muted {
  color: #8a93a3;
}
.card-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-bottom: 0.5rem;
}
.inline-input {
  width: 9.5rem;
  padding: 0.25rem 0.5rem;
  border: 1px solid #c3ccd9;
  border-radius: 6px;
}
.data-table.compact {
  font-size: 0.85rem;
}
.manifest-list {
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
