<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="isOpen && backlogItem" class="modal-overlay" @click="close">
        <div class="modal-container" role="dialog" aria-modal="true" @click.stop>
          <div class="modal-header">
            <h3 class="modal-title">
              {{ mode === 'view' ? 'Purchase Order' : 'Create Purchase Order' }}
            </h3>
            <button class="close-button" aria-label="Close" @click="close">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M15 5L5 15M5 5L15 15" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>
          </div>

          <form class="modal-body" novalidate @submit.prevent="submit" id="po-form">
            <div class="item-context">
              <div class="item-name">{{ translateProductName(backlogItem.item_name) }}</div>
              <div class="item-meta">
                <span class="sku">SKU: {{ backlogItem.item_sku }}</span>
                <span>Order: {{ backlogItem.order_id }}</span>
                <span class="shortage">Shortage: {{ shortage }} units</span>
              </div>
            </div>

            <!-- View mode -->
            <template v-if="mode === 'view'">
              <div v-if="viewLoading" class="state-message">Loading purchase order...</div>
              <div v-else-if="viewError" class="error-message">{{ viewError }}</div>
              <div v-else-if="viewPO" class="info-grid">
                <div class="info-item">
                  <div class="info-label">PO Number</div>
                  <div class="info-value mono">{{ viewPO.id }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Status</div>
                  <div class="info-value"><span class="badge">{{ viewPO.status }}</span></div>
                </div>
                <div class="info-item">
                  <div class="info-label">Supplier</div>
                  <div class="info-value">{{ viewPO.supplier_name }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Quantity</div>
                  <div class="info-value">{{ viewPO.quantity }} units</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Unit Cost</div>
                  <div class="info-value">{{ formatMoney(viewPO.unit_cost) }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Total</div>
                  <div class="info-value">{{ formatMoney(viewPO.quantity * viewPO.unit_cost) }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Expected Delivery</div>
                  <div class="info-value">{{ formatDate(viewPO.expected_delivery_date) }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Created</div>
                  <div class="info-value">{{ formatDate(viewPO.created_date) }}</div>
                </div>
                <div v-if="viewPO.notes" class="info-item full">
                  <div class="info-label">Notes</div>
                  <div class="info-value">{{ viewPO.notes }}</div>
                </div>
              </div>
            </template>

            <!-- Create mode -->
            <template v-else>
              <div class="form-grid">
                <div class="form-field full">
                  <label for="po-supplier">Supplier name</label>
                  <input id="po-supplier" v-model="form.supplier_name" type="text" :class="{ invalid: errors.supplier_name }" :disabled="submitting" />
                  <span v-if="errors.supplier_name" class="field-error">{{ errors.supplier_name }}</span>
                </div>

                <div class="form-field">
                  <label for="po-quantity">Quantity</label>
                  <input id="po-quantity" v-model.number="form.quantity" type="number" min="1" step="1" :class="{ invalid: errors.quantity }" :disabled="submitting" />
                  <span v-if="errors.quantity" class="field-error">{{ errors.quantity }}</span>
                </div>

                <div class="form-field">
                  <label for="po-cost">Unit cost</label>
                  <input id="po-cost" v-model.number="form.unit_cost" type="number" min="0" step="0.01" :class="{ invalid: errors.unit_cost }" :disabled="submitting" />
                  <span v-if="errors.unit_cost" class="field-error">{{ errors.unit_cost }}</span>
                </div>

                <div class="form-field full">
                  <label for="po-date">Expected delivery date</label>
                  <input id="po-date" v-model="form.expected_delivery_date" type="date" :class="{ invalid: errors.expected_delivery_date }" :disabled="submitting" />
                  <span v-if="errors.expected_delivery_date" class="field-error">{{ errors.expected_delivery_date }}</span>
                </div>

                <div class="form-field full">
                  <label for="po-notes">Notes (optional)</label>
                  <textarea id="po-notes" v-model="form.notes" rows="3" :disabled="submitting"></textarea>
                </div>
              </div>

              <div class="total-row">
                <span>Total</span>
                <strong>{{ formatMoney(total) }}</strong>
              </div>

              <div v-if="submitError" class="error-message">{{ submitError }}</div>
            </template>
          </form>

          <div class="modal-footer">
            <button type="button" class="btn-secondary" @click="close">
              {{ mode === 'view' ? 'Close' : 'Cancel' }}
            </button>
            <button v-if="mode !== 'view'" type="submit" form="po-form" class="btn-primary" :disabled="submitting">
              {{ submitting ? 'Creating...' : 'Create Purchase Order' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

const { translateProductName } = useI18n()

const props = defineProps({
  isOpen: { type: Boolean, default: false },
  backlogItem: { type: Object, default: null },
  mode: { type: String, default: 'create' }
})

const emit = defineEmits(['close', 'po-created'])

const form = reactive({
  supplier_name: '',
  quantity: 1,
  unit_cost: null,
  expected_delivery_date: '',
  notes: ''
})
const errors = reactive({})
const submitting = ref(false)
const submitError = ref(null)

const viewPO = ref(null)
const viewLoading = ref(false)
const viewError = ref(null)

const shortage = computed(() => {
  if (!props.backlogItem) return 0
  return Math.max(props.backlogItem.quantity_needed - props.backlogItem.quantity_available, 0)
})

const total = computed(() => {
  const q = Number(form.quantity)
  const c = Number(form.unit_cost)
  return q > 0 && c > 0 ? q * c : 0
})

// Local-time YYYY-MM-DD (toISOString would shift the date across timezones)
const toDateInput = (date) => {
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

const defaultDeliveryDate = () => {
  const d = new Date()
  d.setDate(d.getDate() + 14)
  return toDateInput(d)
}

const resetForm = () => {
  form.supplier_name = ''
  form.quantity = Math.max(shortage.value, 1)
  form.unit_cost = null
  form.expected_delivery_date = defaultDeliveryDate()
  form.notes = ''
  Object.keys(errors).forEach((k) => delete errors[k])
  submitError.value = null
  submitting.value = false
}

const loadPO = async () => {
  viewPO.value = null
  viewError.value = null
  // Prefer the PO already attached to the backlog item (set locally after creation)
  if (props.backlogItem.purchase_order) {
    viewPO.value = props.backlogItem.purchase_order
    return
  }
  viewLoading.value = true
  try {
    viewPO.value = await api.getPurchaseOrderByBacklogItem(props.backlogItem.id)
  } catch (err) {
    viewError.value = err.response?.status === 404
      ? 'No purchase order found for this item.'
      : 'Failed to load purchase order.'
    console.error('Failed to load purchase order:', err)
  } finally {
    viewLoading.value = false
  }
}

// Re-initialise every time the modal is (re)opened or switches mode/item
watch(
  () => [props.isOpen, props.mode, props.backlogItem?.id],
  () => {
    if (!props.isOpen || !props.backlogItem) return
    if (props.mode === 'view') loadPO()
    else resetForm()
  },
  { immediate: true }
)

const validate = () => {
  Object.keys(errors).forEach((k) => delete errors[k])
  if (!form.supplier_name.trim()) errors.supplier_name = 'Supplier name is required'
  if (!Number.isInteger(form.quantity) || form.quantity < 1) errors.quantity = 'Quantity must be a whole number of at least 1'
  if (typeof form.unit_cost !== 'number' || !(form.unit_cost > 0)) errors.unit_cost = 'Unit cost must be greater than 0'
  if (!form.expected_delivery_date || isNaN(new Date(form.expected_delivery_date).getTime())) {
    errors.expected_delivery_date = 'Expected delivery date is required'
  }
  return Object.keys(errors).length === 0
}

// FastAPI returns `detail` as a string (404/409) or a list of validation errors (422)
const extractError = (err) => {
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join('; ')
  return 'Failed to create purchase order. Please try again.'
}

const submit = async () => {
  if (submitting.value || !validate()) return
  submitting.value = true
  submitError.value = null
  try {
    const po = await api.createPurchaseOrder({
      backlog_item_id: props.backlogItem.id,
      supplier_name: form.supplier_name.trim(),
      quantity: form.quantity,
      unit_cost: form.unit_cost,
      expected_delivery_date: form.expected_delivery_date,
      notes: form.notes.trim() || null
    })
    emit('po-created', po)
  } catch (err) {
    submitError.value = extractError(err)
    console.error('Failed to create purchase order:', err)
  } finally {
    submitting.value = false
  }
}

const close = () => emit('close')

const onKeydown = (e) => {
  if (e.key === 'Escape' && props.isOpen) close()
}
onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))

const formatMoney = (value) => {
  const n = Number(value)
  if (isNaN(n)) return 'N/A'
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

const formatDate = (dateString) => {
  if (!dateString) return 'N/A'
  const date = new Date(dateString)
  if (isNaN(date.getTime())) return 'N/A'
  return date.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  padding: 1rem;
}

.modal-container {
  background: white;
  border-radius: 12px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.15);
  max-width: 600px;
  width: 100%;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.5rem;
  border-bottom: 1px solid #e2e8f0;
}

.modal-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.025em;
}

.close-button {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  padding: 0.5rem;
  display: flex;
  border-radius: 6px;
  transition: all 0.15s ease;
}

.close-button:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem 2rem;
}

.item-context {
  padding: 1rem 1.25rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  margin-bottom: 1.5rem;
}

.item-name {
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 0.375rem;
}

.item-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 1rem;
  font-size: 0.813rem;
  color: #64748b;
}

.item-meta .sku {
  font-family: 'Monaco', 'Courier New', monospace;
}

.item-meta .shortage {
  color: #dc2626;
  font-weight: 600;
}

.form-grid,
.info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem 1.25rem;
}

.full {
  grid-column: 1 / -1;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.form-field label,
.info-label {
  font-size: 0.813rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
}

.form-field input,
.form-field textarea {
  padding: 0.625rem 0.75rem;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 0.875rem;
  font-family: inherit;
  color: #0f172a;
  background: white;
}

.form-field input:focus,
.form-field textarea:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
}

.form-field input.invalid {
  border-color: #dc2626;
}

.form-field textarea {
  resize: vertical;
}

.field-error {
  font-size: 0.75rem;
  color: #dc2626;
}

.total-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 1.25rem;
  padding-top: 1rem;
  border-top: 1px solid #e2e8f0;
  color: #475569;
  font-size: 0.938rem;
}

.total-row strong {
  font-size: 1.25rem;
  color: #0f172a;
}

.error-message {
  margin-top: 1rem;
  padding: 0.75rem 1rem;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: #991b1b;
  font-size: 0.875rem;
}

.state-message {
  color: #64748b;
  font-size: 0.875rem;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.info-value {
  font-size: 0.938rem;
  font-weight: 500;
  color: #0f172a;
}

.info-value.mono {
  font-family: 'Monaco', 'Courier New', monospace;
  color: #2563eb;
}

.badge {
  display: inline-block;
  padding: 0.25rem 0.625rem;
  border-radius: 6px;
  background: #fef3c7;
  color: #92400e;
  font-size: 0.813rem;
  font-weight: 600;
}

.modal-footer {
  padding: 1.25rem 1.5rem;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}

.btn-secondary,
.btn-primary {
  padding: 0.625rem 1.25rem;
  border-radius: 8px;
  font-weight: 500;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.15s ease;
  font-family: inherit;
}

.btn-secondary {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  color: #334155;
}

.btn-secondary:hover {
  background: #e2e8f0;
  border-color: #cbd5e1;
}

.btn-primary {
  background: #0f172a;
  border: 1px solid #0f172a;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #1e293b;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .modal-container,
.modal-leave-active .modal-container {
  transition: transform 0.2s ease;
}

.modal-enter-from .modal-container,
.modal-leave-to .modal-container {
  transform: scale(0.95);
}
</style>
