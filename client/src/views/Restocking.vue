<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.budget') }}</h3>
        </div>
        <div class="budget-body">
          <div class="budget-value">{{ formatCurrency(budget, currentCurrency) }}</div>
          <input
            v-model.number="budget"
            type="range"
            class="budget-slider"
            min="0"
            :max="maxBudget"
            :step="budgetStep"
            :aria-label="t('restocking.budget')"
          />
          <div class="budget-range">
            <span>{{ formatCurrency(0, currentCurrency) }}</span>
            <span>{{ formatCurrency(maxBudget, currentCurrency) }}</span>
          </div>
          <p class="budget-help">{{ t('restocking.budgetHelp') }}</p>
        </div>
      </div>

      <div class="stats-grid">
        <div :class="['stat-card', overBudget ? 'danger' : 'info']">
          <div class="stat-label">{{ t('restocking.selectedTotal') }}</div>
          <div class="stat-value">{{ formatMoney(selectedTotal, currentCurrency) }}</div>
        </div>
        <div :class="['stat-card', overBudget ? 'danger' : 'success']">
          <div class="stat-label">{{ overBudget ? t('restocking.overBy') : t('restocking.remaining') }}</div>
          <div class="stat-value">{{ formatMoney(Math.abs(budget - selectedTotal), currentCurrency) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.selectedItems') }}</div>
          <div class="stat-value">{{ selectedItems.length }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.leadTime') }}</div>
          <div class="stat-value">{{ t('restocking.days', { count: orderLeadTime }) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.expectedDelivery') }}</div>
          <div class="stat-value stat-date">{{ expectedDeliveryText }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.items') }} ({{ rows.length }})</h3>
        </div>
        <div class="table-container">
          <table class="restock-table">
            <thead>
              <tr>
                <th class="col-check">{{ t('restocking.table.select') }}</th>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th class="num">{{ t('restocking.table.unitCost') }}</th>
                <th class="num">{{ t('restocking.table.quantity') }}</th>
                <th class="num">{{ t('restocking.table.lineTotal') }}</th>
                <th class="num">{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.item_sku" :class="{ 'row-selected': row.selected }">
                <td class="col-check">
                  <input
                    type="checkbox"
                    :checked="row.selected"
                    :aria-label="row.item_sku"
                    @change="onToggle(row, $event.target.checked)"
                  />
                </td>
                <td><strong>{{ row.item_sku }}</strong></td>
                <td>{{ translateProductName(row.item_name) }}</td>
                <td>
                  <span :class="['badge', row.trend]">{{ t(`trends.${row.trend}`) }}</span>
                </td>
                <td class="num">{{ formatMoney(row.unit_cost, currentCurrency) }}</td>
                <td class="num">
                  <input
                    type="number"
                    class="qty-input"
                    min="0"
                    step="1"
                    :value="row.quantity"
                    :aria-label="t('restocking.table.quantity')"
                    @change="onQuantity(row, $event)"
                  />
                </td>
                <td class="num">
                  <strong>{{ formatMoney(row.lineTotal, currentCurrency) }}</strong>
                </td>
                <td class="num">{{ row.lead_time_days }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card submit-card">
        <p v-if="overBudget" class="over-warning">{{ t('restocking.overBudgetWarning') }}</p>
        <p v-if="submitError" class="over-warning">{{ submitError }}</p>
        <p v-if="successOrder" class="success-message">
          {{ t('restocking.successMessage', { orderNumber: successOrder.order_number }) }}
          <router-link to="/orders">{{ t('restocking.viewOrders') }}</router-link>
        </p>
        <button class="place-order-btn" :disabled="!canSubmit" @click="placeOrder">
          {{ submitting ? t('restocking.submitting') : t('restocking.placeOrder') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'

// Trend priority: items with rising demand are the most urgent to restock
const TREND_RANK = { increasing: 0, stable: 1, decreasing: 2 }
const BUDGET_STEP = 500

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, currentLocale, translateProductName } = useI18n()

    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])
    const budget = ref(0)
    // Manual overrides keyed by SKU, layered on top of the auto-pick
    const selection = ref({}) // sku -> boolean
    const quantities = ref({}) // sku -> number
    const submitting = ref(false)
    const submitError = ref(null)
    const successOrder = ref(null)
    // True after a successful submit until the user edits anything, so a repeat click
    // can't create a duplicate identical order
    const justSubmitted = ref(false)

    const budgetStep = BUDGET_STEP
    // Cents matter for unit costs and totals (whole dollars hid e.g. $8.75 and "over by $0")
    const formatMoney = (amount, currency) => formatCurrencyWithDecimals(amount, currency, 2)

    // Max budget = cost of fully covering every forecast, rounded up to the next 1,000
    const maxBudget = computed(() => {
      const total = forecasts.value.reduce(
        (sum, f) => sum + f.forecasted_demand * f.unit_cost, 0)
      return Math.max(1000, Math.ceil(total / 1000) * 1000)
    })

    const growth = (f) => {
      // Guard against divide-by-zero when current demand is 0
      if (!f.current_demand) return f.forecasted_demand > 0 ? Infinity : 0
      return (f.forecasted_demand - f.current_demand) / f.current_demand
    }

    // Ranking: trend first (increasing > stable > decreasing), then higher growth % wins ties.
    // Spending the budget on the fastest-growing items first reduces stock-out risk.
    const ranked = computed(() => {
      return [...forecasts.value].sort((a, b) => {
        const byTrend = (TREND_RANK[a.trend] ?? 3) - (TREND_RANK[b.trend] ?? 3)
        if (byTrend !== 0) return byTrend
        return growth(b) - growth(a)
      })
    })

    // Greedy fill in ranked order. If an item's full forecast quantity doesn't fit, buy as many
    // units as still affordable (partial) and keep going, so leftover budget isn't wasted on
    // cheaper lower-ranked items.
    const autoPick = (budgetValue) => {
      let remaining = budgetValue
      const picks = {}
      for (const f of ranked.value) {
        if (!(f.unit_cost > 0)) continue
        const fullCost = f.forecasted_demand * f.unit_cost
        let qty = 0
        if (fullCost <= remaining) {
          qty = f.forecasted_demand
        } else {
          qty = Math.floor(remaining / f.unit_cost)
        }
        if (qty > 0) {
          picks[f.item_sku] = qty
          remaining -= qty * f.unit_cost
        }
      }
      return picks
    }

    // Reset selections to the auto-pick whenever the budget (or the data) changes
    const applyAutoPick = () => {
      const picks = autoPick(budget.value)
      const sel = {}
      const qty = {}
      for (const f of forecasts.value) {
        const q = picks[f.item_sku] || 0
        sel[f.item_sku] = q > 0
        qty[f.item_sku] = q > 0 ? q : f.forecasted_demand
      }
      selection.value = sel
      quantities.value = qty
      successOrder.value = null
      justSubmitted.value = false
    }

    watch(budget, applyAutoPick)

    const rows = computed(() => {
      return ranked.value.map(f => {
        const quantity = quantities.value[f.item_sku] ?? 0
        const selected = !!selection.value[f.item_sku]
        return {
          ...f,
          selected,
          quantity,
          lineTotal: selected ? quantity * f.unit_cost : 0
        }
      })
    })

    const selectedItems = computed(() => rows.value.filter(r => r.selected && r.quantity > 0))
    const selectedTotal = computed(() => selectedItems.value.reduce((s, r) => s + r.lineTotal, 0))
    const overBudget = computed(() => selectedTotal.value > budget.value + 1e-9)

    // The order ships together, so it is only complete when the slowest supplier delivers
    const orderLeadTime = computed(() => {
      return selectedItems.value.reduce((max, r) => Math.max(max, r.lead_time_days || 0), 0)
    })

    const expectedDeliveryText = computed(() => {
      if (selectedItems.value.length === 0) return '-'
      const d = new Date()
      d.setDate(d.getDate() + orderLeadTime.value)
      if (isNaN(d.getTime())) return '-'
      return d.toLocaleDateString(currentLocale.value === 'ja' ? 'ja-JP' : 'en-US', {
        year: 'numeric', month: 'short', day: 'numeric'
      })
    })

    const canSubmit = computed(() =>
      selectedItems.value.length > 0 && !overBudget.value && !submitting.value && !justSubmitted.value)

    const onToggle = (row, checked) => {
      justSubmitted.value = false
      selection.value = { ...selection.value, [row.item_sku]: checked }
      if (checked && !(quantities.value[row.item_sku] > 0)) {
        quantities.value = { ...quantities.value, [row.item_sku]: row.forecasted_demand }
      }
    }

    // Committed on @change (blur/Enter), not on every keystroke: updating state mid-typing
    // made Vue rewrite the box (an empty box became "0", giving "07"). Writing the normalized
    // value back to the element also fixes cases like "2.5" -> 2 where state didn't change
    // and Vue would otherwise leave the stale text in place.
    const onQuantity = (row, event) => {
      justSubmitted.value = false
      const parsed = Math.floor(Number(event.target.value))
      const qty = Number.isFinite(parsed) && parsed > 0 ? parsed : 0
      event.target.value = String(qty)
      quantities.value = { ...quantities.value, [row.item_sku]: qty }
      selection.value = { ...selection.value, [row.item_sku]: qty > 0 }
    }

    const placeOrder = async () => {
      if (!canSubmit.value) return
      submitting.value = true
      submitError.value = null
      successOrder.value = null
      try {
        successOrder.value = await api.createRestockOrder({
          budget: budget.value,
          items: selectedItems.value.map(i => ({ sku: i.item_sku, quantity: i.quantity }))
        })
        justSubmitted.value = true
      } catch (err) {
        submitError.value = err.response?.data?.detail || t('restocking.submitFailed')
      } finally {
        submitting.value = false
      }
    }

    const loadData = async () => {
      try {
        loading.value = true
        error.value = null
        forecasts.value = await api.getDemandForecasts()
        const mid = Math.round((maxBudget.value * 0.5) / BUDGET_STEP) * BUDGET_STEP
        const wasSame = budget.value === mid
        budget.value = mid
        // The watcher won't fire if the value is unchanged, so apply explicitly
        if (wasSame) applyAutoPick()
      } catch (err) {
        error.value = t('restocking.loadFailed') + ': ' + err.message
      } finally {
        loading.value = false
      }
    }

    onMounted(loadData)

    return {
      t,
      currentCurrency,
      translateProductName,
      formatCurrency,
      formatMoney,
      loading,
      error,
      budget,
      budgetStep,
      maxBudget,
      rows,
      selectedItems,
      selectedTotal,
      overBudget,
      orderLeadTime,
      expectedDeliveryText,
      canSubmit,
      submitting,
      submitError,
      successOrder,
      onToggle,
      onQuantity,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-card {
  margin-bottom: 1.5rem;
}

.budget-body {
  padding: 0 1.5rem 1.5rem;
}

.budget-value {
  font-size: 2rem;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 0.75rem;
}

.budget-slider {
  width: 100%;
  accent-color: #3b82f6;
}

.budget-range {
  display: flex;
  justify-content: space-between;
  font-size: 0.813rem;
  color: #64748b;
}

.budget-help {
  margin-top: 0.75rem;
  font-size: 0.875rem;
  color: #64748b;
}

.stat-date {
  font-size: 1.25rem;
}

.restock-table .num {
  text-align: right;
  white-space: nowrap;
}

.col-check {
  width: 64px;
  text-align: center;
}

.row-selected {
  background: #f8fafc;
}

.qty-input {
  width: 90px;
  padding: 0.375rem 0.5rem;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  text-align: right;
  color: #0f172a;
}

.submit-card {
  margin-top: 1.5rem;
  padding: 1.25rem 1.5rem;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.75rem;
}

.over-warning {
  color: #dc2626;
  font-size: 0.875rem;
  font-weight: 500;
}

.success-message {
  color: #059669;
  font-size: 0.875rem;
  font-weight: 500;
}

.success-message a {
  margin-left: 0.5rem;
  color: #2563eb;
}

.place-order-btn {
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 8px;
  padding: 0.75rem 1.5rem;
  font-weight: 600;
  cursor: pointer;
}

.place-order-btn:hover:not(:disabled) {
  background: #1e293b;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

@media (max-width: 640px) {
  .budget-value {
    font-size: 1.5rem;
  }

  .place-order-btn {
    width: 100%;
  }
}
</style>
