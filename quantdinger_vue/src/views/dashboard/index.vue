
<template>
  <div class="dashboard-pro" :class="{ 'theme-dark': isDarkTheme }">
    <!-- 主要KPI指标卡片 -->
    <div class="kpi-grid">
      <!-- 总权益 -->
      <div class="kpi-card kpi-primary">
        <div class="kpi-glow"></div>
        <div class="kpi-content">
          <div class="kpi-header">
            <span class="kpi-icon">
              <a-icon type="wallet" />
            </span>
            <span class="kpi-label">{{ $t('dashboard.totalEquity') }}</span>
          </div>
          <div class="kpi-value">
            <span class="currency">$</span>
            <span class="amount">{{ formatNumber(summary.total_equity) }}</span>
          </div>
          <div class="kpi-sub">
            <span :class="summary.total_pnl >= 0 ? 'positive' : 'negative'">
              {{ summary.total_pnl >= 0 ? '+' : '' }}{{ formatNumber(summary.total_pnl) }}
            </span>
            <span class="label">{{ $t('dashboard.label.totalPnl') }}</span>
          </div>
        </div>
      </div>

      <!-- 胜率 -->
      <div class="kpi-card kpi-win-rate">
        <div class="kpi-content">
          <div class="kpi-header">
            <span class="kpi-icon">
              <a-icon type="trophy" />
            </span>
            <span class="kpi-label">{{ $t('dashboard.winRate') || '胜率' }}</span>
          </div>
          <div class="kpi-value">
            <span class="amount">{{ formatNumber(performance.win_rate, 1) }}</span>
            <span class="unit">%</span>
          </div>
          <div class="kpi-sub">
            <span class="positive">{{ performance.winning_trades }}</span>
            <span class="label">{{ $t('dashboard.label.win') }}</span>
            <span class="divider">/</span>
            <span class="negative">{{ performance.losing_trades }}</span>
            <span class="label">{{ $t('dashboard.label.lose') }}</span>
          </div>
        </div>
        <div class="kpi-ring">
          <svg viewBox="0 0 36 36">
            <path
              class="ring-bg"
              d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
            />
            <path
              class="ring-progress"
              :stroke-dasharray="`${performance.win_rate || 0}, 100`"
              d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
            />
          </svg>
        </div>
      </div>

      <!-- 盈亏比 -->
      <div class="kpi-card kpi-profit-factor">
        <div class="kpi-content">
          <div class="kpi-header">
            <span class="kpi-icon">
              <a-icon type="rise" />
            </span>
            <span class="kpi-label">{{ $t('dashboard.profitFactor') || '盈亏比' }}</span>
          </div>
          <div class="kpi-value">
            <span class="amount">{{ formatNumber(performance.profit_factor, 2) }}</span>
            <span class="unit">:1</span>
          </div>
          <div class="kpi-sub">
            <span>{{ $t('dashboard.label.avgProfit') }} </span>
            <span class="positive">${{ formatNumber(performance.avg_win) }}</span>
          </div>
        </div>
      </div>

      <!-- 最大回撤 -->
      <div class="kpi-card kpi-drawdown">
        <div class="kpi-content">
          <div class="kpi-header">
            <span class="kpi-icon">
              <a-icon type="fall" />
            </span>
            <span class="kpi-label">{{ $t('dashboard.maxDrawdown') || '最大回撤' }}</span>
          </div>
          <div class="kpi-value">
            <span class="amount negative">{{ formatNumber(performance.max_drawdown_pct, 1) }}</span>
            <span class="unit">%</span>
          </div>
          <div class="kpi-sub">
            <span>${{ formatNumber(performance.max_drawdown) }}</span>
          </div>
        </div>
      </div>

      <!-- 总交易数 -->
      <div class="kpi-card kpi-trades">
        <div class="kpi-content">
          <div class="kpi-header">
            <span class="kpi-icon">
              <a-icon type="swap" />
            </span>
            <span class="kpi-label">{{ $t('dashboard.totalTrades') || '总交易' }}</span>
          </div>
          <div class="kpi-value">
            <span class="amount">{{ performance.total_trades }}</span>
            <span class="unit">{{ $t('dashboard.unit.trades') }}</span>
          </div>
          <div class="kpi-sub">
            <span>{{ $t('dashboard.label.avgDaily') }} </span>
            <span>{{ avgTradesPerDay }}</span>
            <span class="label"> {{ $t('dashboard.unit.trades') }}</span>
          </div>
        </div>
      </div>

      <!-- 运行策略 -->
      <div class="kpi-card kpi-strategies clickable" @click="$router.push('/trading-assistant')">
        <div class="kpi-content">
          <div class="kpi-header">
            <span class="kpi-icon">
              <a-icon type="thunderbolt" theme="filled" />
            </span>
            <span class="kpi-label">{{ $t('dashboard.runningStrategies') || '运行中策略' }}</span>
          </div>
          <div class="kpi-value">
            <span class="amount">{{ summary.indicator_strategy_count }}</span>
            <span class="unit">{{ $t('dashboard.unit.strategies') }}</span>
          </div>
          <div class="kpi-sub">
            <span class="highlight">{{ summary.indicator_strategy_count }}</span>
            <span class="label"> {{ $t('dashboard.label.indicator') }}</span>
          </div>
        </div>
        <div class="card-arrow">
          <a-icon type="right" />
        </div>
      </div>
    </div>

    <!-- 图表区域 - 第一行 -->
    <div class="chart-row">
      <!-- 收益日历 -->
      <div class="chart-panel chart-main">
        <div class="panel-header">
          <div class="panel-title">
            <a-icon type="calendar" />
            <span>{{ $t('dashboard.profitCalendar') || '收益日曆' }}</span>
          </div>
          <div class="calendar-nav">
            <a-button type="link" size="small" @click="prevMonth" :disabled="currentCalendarIndex >= calendarMonths.length - 1">
              <a-icon type="left" />
            </a-button>
            <span class="current-month">{{ currentMonthLabel }}</span>
            <a-button type="link" size="small" @click="nextMonth" :disabled="currentCalendarIndex <= 0">
              <a-icon type="right" />
            </a-button>
          </div>
        </div>
        <div class="profit-calendar">
          <div v-if="!currentCalendarMonth" class="calendar-empty">
            <a-icon type="inbox" />
            <span>{{ $t('dashboard.noData') }}</span>
          </div>
          <template v-else>
            <!-- Month summary -->
            <div class="month-summary">
              <div class="summary-item">
                <span class="summary-label">{{ $t('dashboard.ranking.totalProfit') }}</span>
                <span class="summary-value" :class="currentCalendarMonth.total >= 0 ? 'positive' : 'negative'">
                  {{ currentCalendarMonth.total >= 0 ? '+' : '' }}${{ formatNumber(currentCalendarMonth.total) }}
                </span>
              </div>
              <div class="summary-item">
                <span class="summary-label">{{ $t('dashboard.label.win') }}</span>
                <span class="summary-value positive">{{ currentCalendarMonth.win_days }}</span>
              </div>
              <div class="summary-item">
                <span class="summary-label">{{ $t('dashboard.label.lose') }}</span>
                <span class="summary-value negative">{{ currentCalendarMonth.lose_days }}</span>
              </div>
            </div>
            <!-- Weekday header -->
            <div class="calendar-weekdays">
              <div class="weekday" v-for="w in weekdays" :key="w">{{ w }}</div>
            </div>
            <!-- Calendar grid -->
            <div class="calendar-grid">
              <!-- Empty cells for offset -->
              <div
                v-for="n in calendarFirstDayOffset"
                :key="'empty-' + n"
                class="calendar-cell empty"
              ></div>
              <!-- Day cells -->
              <div
                v-for="day in currentCalendarMonth.days_in_month"
                :key="day"
                class="calendar-cell"
                :class="getDayClass(day)"
              >
                <span class="day-number">{{ day }}</span>
                <span class="day-profit" v-if="getDayProfit(day) !== null" :class="getDayProfit(day) >= 0 ? 'positive' : 'negative'">
                  {{ getDayProfit(day) >= 0 ? '+' : '' }}{{ formatCompactNumber(getDayProfit(day)) }}
                </span>
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- 策略表现饼图 -->
      <div class="chart-panel chart-side">
        <div class="panel-header">
          <div class="panel-title">
            <a-icon type="pie-chart" />
            <span>{{ $t('dashboard.strategyAllocation') || '策略分布' }}</span>
          </div>
        </div>
        <div ref="pieChart" class="chart-body"></div>
      </div>
    </div>

    <!-- 图表区域 - 第二行 -->
    <div class="chart-row">
      <!-- 回撤曲线 -->
      <div class="chart-panel chart-half">
        <div class="panel-header">
          <div class="panel-title">
            <a-icon type="area-chart" />
            <span>{{ $t('dashboard.drawdownCurve') || '回撤曲线' }}</span>
          </div>
        </div>
        <div ref="drawdownChart" class="chart-body chart-sm"></div>
      </div>

      <!-- 交易时段分布 -->
      <div class="chart-panel chart-half">
        <div class="panel-header">
          <div class="panel-title">
            <a-icon type="clock-circle" />
            <span>{{ $t('dashboard.hourlyDistribution') || '交易时段' }}</span>
          </div>
        </div>
        <div ref="hourlyChart" class="chart-body chart-sm"></div>
      </div>
    </div>

    <!-- 策略排行榜 -->
    <div class="chart-panel">
      <div class="panel-header">
        <div class="panel-title">
          <a-icon type="ordered-list" />
          <span>{{ $t('dashboard.strategyRanking') || '策略排行榜' }}</span>
        </div>
      </div>
      <div class="strategy-ranking">
        <div v-if="strategyStats.length === 0" class="empty-state">
          <a-icon type="inbox" />
          <span>{{ $t('dashboard.noStrategyData') }}</span>
        </div>
        <div v-else class="ranking-grid">
          <div
            v-for="(s, idx) in strategyStats.slice(0, 6)"
            :key="s.strategy_id"
            class="ranking-card"
            :class="{ 'rank-top': idx < 3 }"
          >
            <div class="rank-badge" :class="`rank-${idx + 1}`">{{ idx + 1 }}</div>
            <div class="rank-info">
              <div class="rank-name">{{ s.strategy_name }}</div>
              <div class="rank-stats">
                <span class="stat">
                  <label>{{ $t('dashboard.ranking.totalProfit') }}</label>
                  <span :class="s.total_pnl >= 0 ? 'positive' : 'negative'">
                    {{ s.total_pnl >= 0 ? '+' : '' }}${{ formatNumber(s.total_pnl) }}
                  </span>
                </span>
                <span class="stat">
                  <label>{{ $t('dashboard.winRate') }}</label>
                  <span>{{ formatNumber(s.win_rate, 1) }}%</span>
                </span>
                <span class="stat">
                  <label>{{ $t('dashboard.profitFactor') }}</label>
                  <span>{{ formatNumber(s.profit_factor, 2) }}</span>
                </span>
                <span class="stat">
                  <label>{{ $t('dashboard.ranking.trades') }}</label>
                  <span>{{ s.total_trades }}</span>
                </span>
              </div>
            </div>
            <div class="rank-pnl-bar">
              <div
                class="bar-fill"
                :class="s.total_pnl >= 0 ? 'positive' : 'negative'"
                :style="{ width: `${Math.min(100, Math.abs(s.total_pnl) / maxStrategyPnl * 100)}%` }"
              ></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 数据表格区域 -->
    <div class="table-row">
      <!-- 当前持仓 -->
      <div class="table-panel">
        <div class="panel-header">
          <div class="panel-title">
            <a-icon type="stock" />
            <span>{{ $t('dashboard.currentPositions') }}</span>
          </div>
          <div class="panel-badge">{{ (summary.current_positions || []).length }}</div>
        </div>
        <a-table
          :columns="positionColumns"
          :data-source="summary.current_positions"
          rowKey="id"
          :pagination="false"
          size="small"
          :scroll="{ x: 'max-content' }"
          class="pro-table"
        >
          <template slot="symbol" slot-scope="text, record">
            <div class="symbol-cell">
              <span class="symbol-name">{{ text }}</span>
              <span class="symbol-strategy">{{ record.strategy_name }}</span>
            </div>
          </template>
          <template slot="side" slot-scope="text">
            <span class="side-tag" :class="text === 'long' ? 'long' : 'short'">
              {{ text === 'long' ? 'LONG' : 'SHORT' }}
            </span>
          </template>
          <template slot="unrealized_pnl" slot-scope="text, record">
            <div class="pnl-cell">
              <span :class="text >= 0 ? 'positive' : 'negative'">
                {{ text >= 0 ? '+' : '' }}${{ formatNumber(text) }}
              </span>
              <span class="pnl-percent" :class="record.pnl_percent >= 0 ? 'positive' : 'negative'">
                {{ record.pnl_percent >= 0 ? '+' : '' }}{{ formatNumber(record.pnl_percent) }}%
              </span>
            </div>
          </template>
        </a-table>
      </div>

      <!-- 最近交易 -->
      <div class="table-panel">
        <div class="panel-header">
          <div class="panel-title">
            <a-icon type="history" />
            <span>{{ $t('dashboard.recentTrades') }}</span>
          </div>
        </div>
        <a-table
          :columns="columns"
          :data-source="summary.recent_trades"
          rowKey="id"
          :pagination="{ pageSize: 8, size: 'small' }"
          size="small"
          :scroll="{ x: 'max-content' }"
          class="pro-table"
        >
          <template slot="type" slot-scope="text">
            <span class="type-tag" :class="getTypeClass(text)">
              {{ getSignalTypeText(text) }}
            </span>
          </template>
          <template slot="profit" slot-scope="text, record">
            <span :class="formatProfitValue(text, record) !== '--' ? (text >= 0 ? 'positive' : 'negative') : ''">
              {{ formatProfitValue(text, record) }}
            </span>
          </template>
          <template slot="time" slot-scope="text">
            <span class="time-cell">{{ formatTime(text) }}</span>
          </template>
        </a-table>
      </div>
    </div>

    <!-- 订单执行记录 -->
    <div class="chart-panel orders-panel">
      <div class="panel-header">
        <div class="panel-title">
          <a-icon type="unordered-list" />
          <span>{{ $t('dashboard.pendingOrders') }}</span>
          <a-tooltip :title="soundEnabled ? $t('dashboard.clickToMute') : $t('dashboard.clickToUnmute')">
            <a-icon
              :type="soundEnabled ? 'sound' : 'audio-muted'"
              class="sound-toggle"
              :class="{ 'sound-off': !soundEnabled }"
              @click="toggleSound"
            />
          </a-tooltip>
        </div>
        <div class="panel-badge">{{ ordersPagination.total }}</div>
      </div>
      <a-table
        :columns="orderColumns"
        :data-source="pendingOrders"
        rowKey="id"
        :pagination="{
          current: ordersPagination.current,
          pageSize: ordersPagination.pageSize,
          total: ordersPagination.total,
          showSizeChanger: true,
          size: 'small',
          showTotal: (total) => $t('dashboard.totalOrders', { total })
        }"
        size="small"
        :loading="ordersLoading"
        :scroll="{ x: 1200 }"
        class="pro-table"
        @change="handleOrdersTableChange"
      >
        <template slot="strategy_name" slot-scope="text, record">
          <div class="symbol-cell">
            <span class="symbol-name">{{ text || '-' }}</span>
            <span class="symbol-strategy">ID: {{ record.strategy_id }}</span>
          </div>
        </template>
        <template slot="symbol" slot-scope="text">
          <span class="symbol-tag">{{ text }}</span>
        </template>
        <template slot="signal_type" slot-scope="text">
          <span class="type-tag" :class="getTypeClass(text)">
            {{ getSignalTypeText(text) }}
          </span>
        </template>
        <template slot="exchange" slot-scope="text, record">
          <span
            v-if="(record && (record.exchange_display || record.exchange_id || text))"
            class="exchange-tag"
            :class="(record.exchange_display || record.exchange_id || text).toLowerCase()"
          >
            {{ String(record.exchange_display || record.exchange_id || text).toUpperCase() }}
          </span>
          <span v-else class="text-muted">-</span>
          <div v-if="record && record.market_type" class="market-type">
            {{ String(record.market_type).toUpperCase() }}
          </div>
        </template>
        <template slot="notify" slot-scope="text, record">
          <div class="notify-icons">
            <a-tooltip
              v-for="ch in (record && record.notify_channels ? record.notify_channels : [])"
              :key="`${record.id}-${ch}`"
              :title="String(ch)"
            >
              <a-icon :type="getNotifyIconType(ch)" class="notify-icon" />
            </a-tooltip>
            <span v-if="!record || !record.notify_channels || record.notify_channels.length === 0" class="text-muted">-</span>
          </div>
        </template>
        <template slot="status" slot-scope="text, record">
          <span class="status-tag" :class="text">
            {{ getStatusText(text) }}
          </span>
          <div v-if="text === 'failed' && record.error_message" class="error-hint">
            <a-tooltip :title="record.error_message">
              <a-icon type="exclamation-circle" />
              <span>{{ $t('dashboard.viewError') }}</span>
            </a-tooltip>
          </div>
        </template>
        <template slot="amount" slot-scope="text, record">
          <div>{{ formatNumber(text, 8) }}</div>
          <div v-if="record.filled_amount" class="sub-text">
            {{ $t('dashboard.filled') }}: {{ formatNumber(record.filled_amount, 8) }}
          </div>
        </template>
        <template slot="price" slot-scope="text, record">
          <div v-if="record.filled_price">{{ formatNumber(record.filled_price) }}</div>
          <div v-else class="text-muted">-</div>
        </template>
        <template slot="time_info" slot-scope="text, record">
          <div class="time-cell">{{ formatTime(record.created_at) }}</div>
          <div v-if="record.executed_at" class="sub-text">
            {{ formatTime(record.executed_at) }}
          </div>
        </template>
      </a-table>
    </div>
  </div>
</template>

<script>
import * as echarts from 'echarts'
import { getDashboardSummary, getPendingOrders } from '@/api/dashboard'
import { mapState } from 'vuex'

export default {
  name: 'Dashboard',
  data () {
    return {
      summary: {
        ai_strategy_count: 0,
        indicator_strategy_count: 0,
        total_equity: 0,
        total_pnl: 0,
        total_realized_pnl: 0,
        total_unrealized_pnl: 0,
        performance: {},
        strategy_stats: [],
        daily_pnl_chart: [],
        strategy_pnl_chart: [],
        monthly_returns: [],
        hourly_distribution: [],
        calendar_months: [],
        recent_trades: [],
        current_positions: []
      },
      currentCalendarIndex: 0,
      pieChart: null,
      drawdownChart: null,
      hourlyChart: null,
      pendingOrders: [],
      ordersLoading: false,
      ordersPagination: {
        current: 1,
        pageSize: 20,
        total: 0
      },
      // 声音提醒相关
      orderPollTimer: null,
      lastOrderId: 0,
      orderPollIntervalMs: 5000,
      soundEnabled: true,
      beepCtx: null
    }
  },
  computed: {
    ...mapState({
      navTheme: state => state.app.theme
    }),
    isDarkTheme () {
      return this.navTheme === 'dark' || this.navTheme === 'realdark'
    },
    performance () {
      return this.summary.performance || {}
    },
    strategyStats () {
      return this.summary.strategy_stats || []
    },
    maxStrategyPnl () {
      const stats = this.strategyStats
      if (!stats.length) return 1
      return Math.max(...stats.map(s => Math.abs(s.total_pnl || 0)), 1)
    },
    avgTradesPerDay () {
      const chart = this.summary.daily_pnl_chart || []
      const days = chart.length || 1
      const total = this.performance.total_trades || 0
      return (total / days).toFixed(1)
    },
    calendarMonths () {
      return this.summary.calendar_months || []
    },
    currentCalendarMonth () {
      const months = this.calendarMonths
      if (!months.length) return null
      return months[this.currentCalendarIndex] || null
    },
    currentMonthLabel () {
      const m = this.currentCalendarMonth
      if (!m) return '-'
      const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
      return `${monthNames[m.month - 1]} ${m.year}`
    },
    weekdays () {
      return ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    },
    calendarFirstDayOffset () {
      const m = this.currentCalendarMonth
      if (!m) return 0
      // first_weekday: 0=Monday, 6=Sunday
      return m.first_weekday
    },
    orderStrategyFilters () {
      const list = Array.isArray(this.pendingOrders) ? this.pendingOrders : []
      const map = new Map()
      for (const item of list) {
        const id = item && item.strategy_id
        if (id === undefined || id === null || map.has(String(id))) continue
        const name = (item && item.strategy_name) ? String(item.strategy_name) : ''
        const text = name ? `${name} (ID: ${id})` : `ID: ${id}`
        map.set(String(id), { text, value: String(id) })
      }
      return Array.from(map.values()).sort((a, b) => String(a.text).localeCompare(String(b.text)))
    },
    columns () {
      return [
        {
          title: this.$t('dashboard.table.time'),
          dataIndex: 'created_at',
          scopedSlots: { customRender: 'time' },
          width: 150
        },
        {
          title: this.$t('dashboard.table.symbol'),
          dataIndex: 'symbol',
          width: 100
        },
        {
          title: this.$t('dashboard.table.type'),
          dataIndex: 'type',
          scopedSlots: { customRender: 'type' },
          width: 90
        },
        {
          title: this.$t('dashboard.table.price'),
          dataIndex: 'price',
          customRender: (text) => this.formatNumber(text),
          width: 100
        },
        {
          title: this.$t('dashboard.table.profit'),
          dataIndex: 'profit',
          scopedSlots: { customRender: 'profit' },
          align: 'right',
          width: 100
        }
      ]
    },
    positionColumns () {
      return [
        {
          title: this.$t('dashboard.table.symbol'),
          dataIndex: 'symbol',
          scopedSlots: { customRender: 'symbol' }
        },
        {
          title: this.$t('dashboard.table.side'),
          dataIndex: 'side',
          scopedSlots: { customRender: 'side' }
        },
        {
          title: this.$t('dashboard.table.size'),
          dataIndex: 'size',
          customRender: (text) => this.formatNumber(text, 4)
        },
        {
          title: this.$t('dashboard.table.entryPrice'),
          dataIndex: 'entry_price',
          customRender: (text) => this.formatNumber(text)
        },
        {
          title: this.$t('dashboard.table.pnl'),
          dataIndex: 'unrealized_pnl',
          scopedSlots: { customRender: 'unrealized_pnl' },
          align: 'right'
        }
      ]
    },
    orderColumns () {
      return [
        {
          title: this.$t('dashboard.orderTable.strategy'),
          dataIndex: 'strategy_name',
          scopedSlots: { customRender: 'strategy_name' },
          filters: this.orderStrategyFilters,
          filterMultiple: true,
          onFilter: (value, record) => String(record && record.strategy_id) === String(value),
          width: 150
        },
        {
          title: this.$t('dashboard.orderTable.exchange'),
          dataIndex: 'exchange_id',
          scopedSlots: { customRender: 'exchange' },
          width: 120
        },
        {
          title: this.$t('dashboard.orderTable.notify'),
          dataIndex: 'notify_channels',
          scopedSlots: { customRender: 'notify' },
          width: 100
        },
        {
          title: this.$t('dashboard.orderTable.symbol'),
          dataIndex: 'symbol',
          scopedSlots: { customRender: 'symbol' },
          width: 110
        },
        {
          title: this.$t('dashboard.orderTable.signalType'),
          dataIndex: 'signal_type',
          scopedSlots: { customRender: 'signal_type' },
          width: 100
        },
        {
          title: this.$t('dashboard.orderTable.amount'),
          dataIndex: 'amount',
          scopedSlots: { customRender: 'amount' },
          width: 130
        },
        {
          title: this.$t('dashboard.orderTable.price'),
          dataIndex: 'filled_price',
          scopedSlots: { customRender: 'price' },
          width: 100
        },
        {
          title: this.$t('dashboard.orderTable.status'),
          dataIndex: 'status',
          scopedSlots: { customRender: 'status' },
          width: 130
        },
        {
          title: this.$t('dashboard.orderTable.timeInfo'),
          dataIndex: 'created_at',
          scopedSlots: { customRender: 'time_info' },
          width: 160
        }
      ]
    }
  },
  mounted () {
    this.fetchData()
    this.fetchPendingOrders()
    this.startOrderPolling()
    window.addEventListener('resize', this.handleResize)
  },
  beforeDestroy () {
    this.stopOrderPolling()
    window.removeEventListener('resize', this.handleResize)
    if (this.pieChart) this.pieChart.dispose()
    if (this.drawdownChart) this.drawdownChart.dispose()
    if (this.hourlyChart) this.hourlyChart.dispose()
  },
  methods: {
    async fetchData () {
      try {
        const res = await getDashboardSummary()
        if (res.code === 1) {
          this.summary = { ...this.summary, ...res.data }
          this.$nextTick(() => {
            this.initCharts()
          })
        }
      } catch (e) {
        console.error('Failed to fetch dashboard data:', e)
      }
    },
    async fetchPendingOrders (page, pageSize) {
      this.ordersLoading = true
      try {
        const current = page || this.ordersPagination.current || 1
        const size = pageSize || this.ordersPagination.pageSize || 20
        const res = await getPendingOrders({ page: current, pageSize: size })
        if (res.code === 1) {
          const data = res.data || {}
          this.pendingOrders = data.list || []
          this.ordersPagination.current = Number(data.page || current || 1)
          this.ordersPagination.pageSize = Number(data.pageSize || size || 20)
          this.ordersPagination.total = Number(data.total || 0)
        }
      } catch (e) {
        console.error('获取订单列表失败:', e)
      } finally {
        this.ordersLoading = false
      }
    },
    // ========== 订单声音提醒 ==========
    playOrderBeep () {
      if (!this.soundEnabled) return
      try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext
        if (!AudioCtx) return
        if (!this.beepCtx) this.beepCtx = new AudioCtx()
        const ctx = this.beepCtx
        // 部分浏览器需要用户交互后才能播放声音
        if (ctx.state === 'suspended' && typeof ctx.resume === 'function') {
          ctx.resume().catch(() => {})
        }
        // 播放两声短促的提示音
        const playTone = (startTime, freq) => {
          const o = ctx.createOscillator()
          const g = ctx.createGain()
          o.type = 'sine'
          o.frequency.value = freq
          g.gain.value = 0.08
          o.connect(g)
          g.connect(ctx.destination)
          o.start(startTime)
          o.stop(startTime + 0.12)
        }
        const now = ctx.currentTime
        playTone(now, 880) // 第一声
        playTone(now + 0.18, 1100) // 第二声更高
      } catch (e) {
        console.error('播放提示音失败:', e)
      }
    },
    startOrderPolling () {
      this.stopOrderPolling()
      // 初始化 lastOrderId
      this.initLastOrderId()
      this.orderPollTimer = setInterval(() => {
        this.pollNewOrders()
      }, this.orderPollIntervalMs)
    },
    stopOrderPolling () {
      if (this.orderPollTimer) {
        clearInterval(this.orderPollTimer)
        this.orderPollTimer = null
      }
    },
    async initLastOrderId () {
      try {
        const res = await getPendingOrders({ page: 1, pageSize: 1 })
        if (res.code === 1 && res.data && res.data.list && res.data.list.length > 0) {
          // 获取最新的订单ID
          this.lastOrderId = res.data.list[0].id || 0
        }
      } catch (e) {
        console.error('初始化订单ID失败:', e)
      }
    },
    async pollNewOrders () {
      try {
        const res = await getPendingOrders({ page: 1, pageSize: 10 })
        if (res.code !== 1 || !res.data || !res.data.list) return

        const orders = res.data.list || []
        if (orders.length === 0) return

        // 检查是否有新订单
        let hasNew = false
        let maxId = this.lastOrderId
        for (const order of orders) {
          const orderId = order.id || 0
          if (orderId > this.lastOrderId) {
            hasNew = true
            if (orderId > maxId) maxId = orderId
          }
        }

        if (hasNew) {
          this.lastOrderId = maxId
          this.playOrderBeep()
          // 刷新订单列表
          this.fetchPendingOrders()
          // 显示通知
          this.$notification.info({
            message: this.$t('dashboard.newOrderNotify'),
            description: this.$t('dashboard.newOrderDesc'),
            duration: 4
          })
        }
      } catch (e) {
        console.error('轮询订单失败:', e)
      }
    },
    toggleSound () {
      this.soundEnabled = !this.soundEnabled
      if (this.soundEnabled) {
        this.$message.success(this.$t('dashboard.soundEnabled'))
      } else {
        this.$message.info(this.$t('dashboard.soundDisabled'))
      }
    },
    handleOrdersTableChange (pagination) {
      const current = (pagination && pagination.current) ? pagination.current : 1
      const pageSize = (pagination && pagination.pageSize) ? pagination.pageSize : (this.ordersPagination.pageSize || 20)
      this.ordersPagination.current = current
      this.ordersPagination.pageSize = pageSize
      this.fetchPendingOrders(current, pageSize)
    },
    getTypeClass (type) {
      if (!type) return ''
      const t = type.toLowerCase()
      if (t.includes('open_long') || t.includes('add_long')) return 'long'
      if (t.includes('open_short') || t.includes('add_short')) return 'short'
      if (t.includes('close_long')) return 'close-long'
      if (t.includes('close_short')) return 'close-short'
      return ''
    },
    getSignalTypeColor (type) {
      if (!type) return 'default'
      type = type.toLowerCase()
      if (type.includes('open_long') || type.includes('add_long')) return 'green'
      if (type.includes('open_short') || type.includes('add_short')) return 'red'
      if (type.includes('close_long')) return 'orange'
      if (type.includes('close_short')) return 'purple'
      return 'blue'
    },
    getSignalTypeText (type) {
      if (!type) return '-'
      const typeMap = {
        'open_long': this.$t('dashboard.signalType.openLong'),
        'open_short': this.$t('dashboard.signalType.openShort'),
        'close_long': this.$t('dashboard.signalType.closeLong'),
        'close_short': this.$t('dashboard.signalType.closeShort'),
        'add_long': this.$t('dashboard.signalType.addLong'),
        'add_short': this.$t('dashboard.signalType.addShort')
      }
      return typeMap[type.toLowerCase()] || type.toUpperCase()
    },
    getStatusColor (status) {
      const colorMap = {
        'pending': 'orange',
        'processing': 'blue',
        'completed': 'green',
        'failed': 'red',
        'cancelled': 'default'
      }
      return colorMap[status] || 'default'
    },
    getStatusText (status) {
      if (!status) return '-'
      const statusMap = {
        'pending': this.$t('dashboard.status.pending'),
        'processing': this.$t('dashboard.status.processing'),
        'completed': this.$t('dashboard.status.completed'),
        'failed': this.$t('dashboard.status.failed'),
        'cancelled': this.$t('dashboard.status.cancelled')
      }
      return statusMap[status.toLowerCase()] || status.toUpperCase()
    },
    getNotifyIconType (channel) {
      const c = String(channel || '').trim().toLowerCase()
      const map = {
        browser: 'bell',
        webhook: 'link',
        discord: 'comment',
        telegram: 'message',
        tg: 'message',
        tele: 'message',
        email: 'mail',
        phone: 'phone'
      }
      return map[c] || 'notification'
    },
    getExchangeTagColor (exchange) {
      const ex = String(exchange || '').trim().toLowerCase()
      const map = {
        binance: 'gold',
        okx: 'purple',
        bitget: 'cyan',
        signal: 'geekblue'
      }
      return map[ex] || 'blue'
    },
    formatNumber (num, digits = 2) {
      if (num === undefined || num === null) return '0.00'
      return Number(num).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
    },
    // 格式化盈亏值（处理信号模式下没有实盘的情况）
    formatProfitValue (value, record) {
      if (value === null || value === undefined) return '--'

      const numValue = parseFloat(value)

      // 如果值为0且是开仓信号（open_long/open_short），显示--
      const openTypes = ['open_long', 'open_short', 'add_long', 'add_short']
      if (numValue === 0 && record && openTypes.includes(record.type)) {
        return '--'
      }

      // 如果值极小（科学计数法如0E-8），视为0
      if (Math.abs(numValue) < 0.000001) {
        if (record && openTypes.includes(record.type)) {
          return '--'
        }
        return '$0.00'
      }

      // 正常显示
      const sign = numValue >= 0 ? '+' : ''
      return `${sign}$${this.formatNumber(numValue)}`
    },
    formatCompactNumber (num) {
      if (num === undefined || num === null) return '0'
      const abs = Math.abs(num)
      if (abs >= 1000000) return (num / 1000000).toFixed(1) + 'M'
      if (abs >= 1000) return (num / 1000).toFixed(1) + 'k'
      if (abs >= 100) return Math.round(num)
      return num.toFixed(0)
    },
    prevMonth () {
      if (this.currentCalendarIndex < this.calendarMonths.length - 1) {
        this.currentCalendarIndex++
      }
    },
    nextMonth () {
      if (this.currentCalendarIndex > 0) {
        this.currentCalendarIndex--
      }
    },
    getDayProfit (day) {
      const m = this.currentCalendarMonth
      if (!m || !m.days) return null
      const dayStr = String(day).padStart(2, '0')
      return m.days[dayStr] !== undefined ? m.days[dayStr] : null
    },
    getDayClass (day) {
      const profit = this.getDayProfit(day)
      if (profit === null) return 'no-data'
      if (profit > 0) return 'profit'
      if (profit < 0) return 'loss'
      return 'zero'
    },
    formatTime (timestamp) {
      if (!timestamp) return '-'
      try {
        let date
        // Handle ISO 8601 date strings (e.g., "2024-01-17T01:58:10.000Z")
        if (typeof timestamp === 'string' && timestamp.includes('-') && timestamp.includes(':')) {
          date = new Date(timestamp)
        } else if (typeof timestamp === 'number' || (typeof timestamp === 'string' && /^\d+$/.test(timestamp))) {
          // Handle numeric timestamps (seconds or milliseconds)
          const numTimestamp = typeof timestamp === 'string' ? parseInt(timestamp, 10) : timestamp
          const ms = numTimestamp < 1e12 ? numTimestamp * 1000 : numTimestamp
          date = new Date(ms)
        } else {
          return '-'
        }
        if (isNaN(date.getTime())) return '-'
        return date.toLocaleString()
      } catch (e) {
        return '-'
      }
    },
    initCharts () {
      this.initPieChart()
      this.initDrawdownChart()
      this.initHourlyChart()
    },
    initPieChart () {
      const chartDom = this.$refs.pieChart
      if (!chartDom) return
      this.pieChart = echarts.init(chartDom)

      // Use strategy_stats for pie chart data (shows all strategies, not just those with positions)
      const stats = Array.isArray(this.summary.strategy_stats) ? this.summary.strategy_stats : []
      const raw = Array.isArray(this.summary.strategy_pnl_chart) ? this.summary.strategy_pnl_chart : []

      // Prefer strategy_stats if available, fallback to strategy_pnl_chart
      let data = []
      if (stats.length > 0) {
        data = stats.map(it => {
          const name = (it && it.strategy_name) ? String(it.strategy_name) : '-'
          const val = Number(it && it.total_pnl ? it.total_pnl : 0)
          const trades = Number(it && it.total_trades ? it.total_trades : 0)
          // Use trades count as value if no PnL, so at least we show the distribution
          const displayVal = val !== 0 ? Math.abs(val) : trades
          return { name, value: displayVal, signedValue: val, trades }
        }).filter(it => it.value > 0)
      } else {
        data = raw
          .map(it => {
            const name = (it && it.name) ? String(it.name) : '-'
            const val = Number(it && it.value ? it.value : 0)
            return { name, value: Math.abs(val), signedValue: val }
          })
          .filter(it => it.value > 0)
      }

      const isDark = this.isDarkTheme
      const textColor = isDark ? '#9ca3af' : '#6b7280'

      // Modern gradient colors
      const colors = [
        new echarts.graphic.LinearGradient(0, 0, 1, 1, [
          { offset: 0, color: '#3b82f6' },
          { offset: 1, color: '#1d4ed8' }
        ]),
        new echarts.graphic.LinearGradient(0, 0, 1, 1, [
          { offset: 0, color: '#8b5cf6' },
          { offset: 1, color: '#6d28d9' }
        ]),
        new echarts.graphic.LinearGradient(0, 0, 1, 1, [
          { offset: 0, color: '#10b981' },
          { offset: 1, color: '#059669' }
        ]),
        new echarts.graphic.LinearGradient(0, 0, 1, 1, [
          { offset: 0, color: '#f59e0b' },
          { offset: 1, color: '#d97706' }
        ]),
        new echarts.graphic.LinearGradient(0, 0, 1, 1, [
          { offset: 0, color: '#ec4899' },
          { offset: 1, color: '#be185d' }
        ]),
        new echarts.graphic.LinearGradient(0, 0, 1, 1, [
          { offset: 0, color: '#06b6d4' },
          { offset: 1, color: '#0891b2' }
        ])
      ]

      const option = {
        backgroundColor: 'transparent',
        tooltip: {
          trigger: 'item',
          backgroundColor: isDark ? 'rgba(17, 24, 39, 0.95)' : 'rgba(255, 255, 255, 0.95)',
          borderColor: isDark ? '#374151' : '#e5e7eb',
          textStyle: { color: isDark ? '#f3f4f6' : '#1f2937' },
          formatter: (p) => {
            const sv = (p && p.data && typeof p.data.signedValue === 'number') ? p.data.signedValue : 0
            const svStr = (sv >= 0 ? '+' : '') + this.formatNumber(sv, 2)
            const svColor = sv >= 0 ? '#10b981' : '#ef4444'
            return `
              <div style="padding: 4px 0;">
                <div style="font-weight:600;margin-bottom:6px;">${p.name}</div>
                <div style="color:${textColor}">占比 <span style="font-weight:600;color:${isDark ? '#f3f4f6' : '#1f2937'}">${p.percent}%</span></div>
                <div style="color:${textColor}">PNL <span style="font-weight:600;color:${svColor}">$${svStr}</span></div>
              </div>
            `
          }
        },
        legend: {
          bottom: 10,
          left: 'center',
          itemWidth: 12,
          itemHeight: 12,
          itemGap: 16,
          textStyle: {
            color: textColor,
            fontSize: 11
          }
        },
        color: colors,
        series: [
          {
            name: '策略分布',
            type: 'pie',
            radius: ['50%', '75%'],
            center: ['50%', '45%'],
            avoidLabelOverlap: false,
            itemStyle: {
              borderRadius: 6,
              borderColor: isDark ? '#1f2937' : '#ffffff',
              borderWidth: 3
            },
            label: { show: false },
            emphasis: {
              label: {
                show: true,
                fontSize: 14,
                fontWeight: 'bold',
                color: isDark ? '#f3f4f6' : '#1f2937'
              },
              scaleSize: 8
            },
            labelLine: { show: false },
            data: data.length > 0 ? data : [{ value: 1, name: this.$t('dashboard.noData'), signedValue: 0 }]
          }
        ]
      }
      this.pieChart.setOption(option)
    },
    initDrawdownChart () {
      const chartDom = this.$refs.drawdownChart
      if (!chartDom) return
      this.drawdownChart = echarts.init(chartDom)

      const dates = (this.summary.daily_pnl_chart || []).map(item => item.date)
      const values = (this.summary.daily_pnl_chart || []).map(item => Number(item.profit || 0))

      // cumulative and drawdown
      const cum = []
      let acc = 0
      for (const v of values) {
        acc += Number(v || 0)
        cum.push(acc)
      }
      let peak = -Infinity
      let maxDdValue = 0
      let maxDdIndex = 0
      const dd = cum.map((v, i) => {
        peak = Math.max(peak, v)
        const drawdown = Number((v - peak).toFixed(2))
        if (drawdown < maxDdValue) {
          maxDdValue = drawdown
          maxDdIndex = i
        }
        return drawdown
      })

      const isDark = this.isDarkTheme
      const textColor = isDark ? '#a1a1aa' : '#52525b'
      const gridColor = isDark ? 'rgba(63, 63, 70, 0.5)' : 'rgba(228, 228, 231, 0.8)'

      const option = {
        backgroundColor: 'transparent',
        animation: true,
        animationDuration: 800,
        animationEasing: 'cubicOut',
        tooltip: {
          trigger: 'axis',
          backgroundColor: isDark ? 'rgba(24, 24, 27, 0.96)' : 'rgba(255, 255, 255, 0.96)',
          borderColor: isDark ? 'rgba(63, 63, 70, 0.8)' : 'rgba(228, 228, 231, 0.8)',
          borderWidth: 1,
          padding: [12, 16],
          textStyle: { color: isDark ? '#fafafa' : '#18181b', fontSize: 13 },
          extraCssText: 'box-shadow: 0 8px 32px rgba(0,0,0,0.12); border-radius: 12px;',
          axisPointer: {
            type: 'line',
            lineStyle: { color: 'rgba(239, 68, 68, 0.4)', type: 'dashed' }
          },
          formatter: (params) => {
            const p = Array.isArray(params) ? params[0] : null
            const date = p ? p.axisValue : ''
            const v = p ? Number(p.data || 0) : 0
            const vStr = this.formatNumber(Math.abs(v), 2)
            const pctOfMax = maxDdValue !== 0 ? Math.abs((v / maxDdValue) * 100).toFixed(0) : 0
            return `
              <div style="min-width: 140px;">
                <div style="font-weight:600;margin-bottom:10px;font-size:14px;color:${isDark ? '#fafafa' : '#18181b'}">${date}</div>
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                  <span style="display:flex;align-items:center;gap:8px;">
                    <span style="width:10px;height:10px;border-radius:2px;background:linear-gradient(180deg,#f87171,#dc2626);"></span>
                    <span style="color:${textColor}">${this.$t('dashboard.drawdown') || 'Drawdown'}</span>
                  </span>
                  <span style="font-weight:700;color:#ef4444;font-family:monospace;">-$${vStr}</span>
                </div>
                <div style="background:${isDark ? 'rgba(63,63,70,0.5)' : 'rgba(228,228,231,0.5)'};height:6px;border-radius:3px;overflow:hidden;">
                  <div style="width:${pctOfMax}%;height:100%;background:linear-gradient(90deg,#f87171,#ef4444);border-radius:3px;"></div>
                </div>
              </div>
            `
          }
        },
        grid: { left: 55, right: 20, bottom: 35, top: 20, containLabel: false },
        xAxis: {
          type: 'category',
          data: dates,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: textColor,
            fontSize: 10,
            formatter: (v) => v.slice(5) // Show MM-DD only
          }
        },
        yAxis: {
          type: 'value',
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: textColor,
            fontSize: 10,
            formatter: (v) => {
              if (Math.abs(v) >= 1000) return '-$' + (Math.abs(v) / 1000).toFixed(1) + 'k'
              return v === 0 ? '0' : '-$' + Math.abs(v)
            }
          },
          splitLine: { lineStyle: { color: gridColor, type: [4, 4] } },
          max: 0
        },
        series: [
          {
            name: this.$t('dashboard.drawdown') || 'Drawdown',
            type: 'line',
            data: dd,
            smooth: 0.3,
            showSymbol: false,
            lineStyle: {
              width: 2.5,
              color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
                { offset: 0, color: '#ef4444' },
                { offset: 0.5, color: '#f87171' },
                { offset: 1, color: '#fca5a5' }
              ]),
              shadowColor: 'rgba(239, 68, 68, 0.4)',
              shadowBlur: 8,
              shadowOffsetY: 4
            },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: isDark ? 'rgba(239, 68, 68, 0.4)' : 'rgba(239, 68, 68, 0.25)' },
                { offset: 0.5, color: isDark ? 'rgba(248, 113, 113, 0.15)' : 'rgba(248, 113, 113, 0.1)' },
                { offset: 1, color: 'transparent' }
              ])
            },
            markPoint: maxDdValue < 0 ? {
              symbol: 'pin',
              symbolSize: 45,
              itemStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                  { offset: 0, color: '#f87171' },
                  { offset: 1, color: '#dc2626' }
                ]),
                shadowColor: 'rgba(239, 68, 68, 0.5)',
                shadowBlur: 10
              },
              label: {
                show: true,
                color: '#fff',
                fontSize: 10,
                fontWeight: 'bold',
                formatter: () => this.$t('dashboard.label.maxDrawdownPoint') || 'MAX'
              },
              data: [{
                name: this.$t('dashboard.maxDrawdown') || 'Max Drawdown',
                coord: [maxDdIndex, maxDdValue]
              }]
            } : undefined,
            markLine: {
              silent: true,
              symbol: 'none',
              lineStyle: { color: isDark ? '#52525b' : '#a1a1aa', type: 'dashed', width: 1 },
              data: [{ yAxis: 0 }],
              label: { show: false }
            }
          }
        ]
      }
      this.drawdownChart.setOption(option)
    },
    initHourlyChart () {
      const chartDom = this.$refs.hourlyChart
      if (!chartDom) return
      this.hourlyChart = echarts.init(chartDom)

      const hourlyData = this.summary.hourly_distribution || []
      const hours = hourlyData.map(h => `${String(h.hour).padStart(2, '0')}:00`)
      const counts = hourlyData.map(h => h.count || 0)
      const profits = hourlyData.map(h => h.profit || 0)

      const isDark = this.isDarkTheme
      const textColor = isDark ? '#9ca3af' : '#6b7280'
      const gridColor = isDark ? 'rgba(75, 85, 99, 0.3)' : 'rgba(229, 231, 235, 0.8)'

      const option = {
        backgroundColor: 'transparent',
        tooltip: {
          trigger: 'axis',
          backgroundColor: isDark ? 'rgba(17, 24, 39, 0.95)' : 'rgba(255, 255, 255, 0.95)',
          borderColor: isDark ? '#374151' : '#e5e7eb',
          textStyle: { color: isDark ? '#f3f4f6' : '#1f2937' },
          formatter: (params) => {
            const arr = Array.isArray(params) ? params : []
            const hour = (arr[0] && arr[0].axisValue) ? arr[0].axisValue : ''
            let count = 0
            let profit = 0
            const tradeCountLabel = this.$t('dashboard.tradeCount') || 'Trade Count'
            const profitLabel = this.$t('dashboard.profit') || 'Profit'
            const unitLabel = this.$t('dashboard.unit.trades') || ''
            for (const p of arr) {
              if (p.seriesName === tradeCountLabel) count = p.data || 0
              if (p.seriesName === profitLabel) profit = p.data || 0
            }
            const profitColor = profit >= 0 ? '#10b981' : '#ef4444'
            const profitStr = (profit >= 0 ? '+' : '') + this.formatNumber(profit, 2)
            return `
              <div style="padding: 4px 0;">
                <div style="font-weight:600;margin-bottom:6px;">${hour}</div>
                <div style="color:${textColor}">${tradeCountLabel} <span style="font-weight:600;color:${isDark ? '#f3f4f6' : '#1f2937'}">${count} ${unitLabel}</span></div>
                <div style="color:${textColor}">${profitLabel} <span style="font-weight:600;color:${profitColor}">$${profitStr}</span></div>
              </div>
            `
          }
        },
        grid: { left: 50, right: 20, bottom: 30, top: 10, containLabel: false },
        xAxis: {
          type: 'category',
          data: hours,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: textColor,
            fontSize: 10,
            interval: 3
          }
        },
        yAxis: {
          type: 'value',
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { color: textColor, fontSize: 10 },
          splitLine: { lineStyle: { color: gridColor, type: 'dashed' } }
        },
        series: [
          {
            name: this.$t('dashboard.tradeCount') || 'Trade Count',
            type: 'bar',
            data: counts,
            barMaxWidth: 16,
            itemStyle: {
              borderRadius: [3, 3, 0, 0],
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: '#60a5fa' },
                { offset: 1, color: '#3b82f6' }
              ])
            }
          },
          {
            name: this.$t('dashboard.profit') || 'Profit',
            type: 'line',
            data: profits,
            smooth: true,
            showSymbol: false,
            lineStyle: { width: 2, color: '#a855f7' }
          }
        ]
      }
      this.hourlyChart.setOption(option)
    },
    handleResize () {
      if (this.pieChart) this.pieChart.resize()
      if (this.drawdownChart) this.drawdownChart.resize()
      if (this.hourlyChart) this.hourlyChart.resize()
    }
  }
}
</script>

<style lang="less" scoped>
// Design tokens
@bg-dark: #0f172a;
@bg-card-dark: #1e293b;
@bg-card-hover-dark: #334155;
@border-dark: #334155;
@text-primary-dark: #f1f5f9;
@text-secondary-dark: #94a3b8;

@bg-light: #f8fafc;
@bg-card-light: #ffffff;
@border-light: #e2e8f0;
@text-primary-light: #1e293b;
@text-secondary-light: #64748b;

// Colors
@green: #10b981;
@green-light: #34d399;
@red: #ef4444;
@red-light: #f87171;
@blue: #3b82f6;
@purple: #8b5cf6;
@amber: #f59e0b;
@cyan: #06b6d4;

.dashboard-pro {
  min-height: 100vh;
  padding: 20px;
  background: @bg-light;
  transition: background 0.3s;

  &.theme-dark {
    background: @bg-dark;

    .kpi-card {
      background: @bg-card-dark;
      border-color: @border-dark;

      .kpi-label { color: @text-secondary-dark; }
      .kpi-value .amount { color: @text-primary-dark; }
      .kpi-sub { color: @text-secondary-dark; }
    }

    .chart-panel, .table-panel {
      background: @bg-card-dark;
      border-color: @border-dark;

      .panel-header {
        border-color: @border-dark;
        .panel-title { color: @text-primary-dark; }
      }
    }

    .ranking-card {
      background: rgba(51, 65, 85, 0.5);
      border-color: @border-dark;

      .rank-name { color: @text-primary-dark; }
      .rank-stats label { color: @text-secondary-dark; }
    }

    .calendar-nav {
      .current-month { color: @text-primary-dark; }
      .ant-btn-link { color: @text-secondary-dark; }
    }

    .profit-calendar {
      .calendar-empty { color: @text-secondary-dark; }

      .month-summary {
        background: rgba(51, 65, 85, 0.5);

        .summary-label { color: @text-secondary-dark; }
      }

      .calendar-weekdays .weekday { color: @text-secondary-dark; }

      .calendar-grid .calendar-cell {
        background: rgba(51, 65, 85, 0.3);

        &.no-data { background: rgba(51, 65, 85, 0.2); }

        &.profit {
          background: linear-gradient(135deg, rgba(34, 197, 94, 0.15) 0%, rgba(34, 197, 94, 0.25) 100%);
        }

        &.loss {
          background: linear-gradient(135deg, rgba(239, 68, 68, 0.15) 0%, rgba(239, 68, 68, 0.25) 100%);
        }

        &.zero {
          background: rgba(100, 116, 139, 0.2);
        }

        .day-number { color: @text-primary-dark; }
      }
    }

    .pro-table {
      ::v-deep .ant-table {
        background: transparent;
        color: @text-primary-dark;
      }
      ::v-deep .ant-table-thead > tr > th {
        background: rgba(51, 65, 85, 0.5);
        color: @text-secondary-dark;
        border-color: @border-dark;
      }
      ::v-deep .ant-table-tbody > tr > td {
        border-color: @border-dark;
        color: @text-primary-dark;
      }
      ::v-deep .ant-table-tbody > tr:hover > td {
        background: rgba(51, 65, 85, 0.3);
      }
      ::v-deep .ant-table-placeholder {
        background: transparent;
        .ant-empty-description { color: @text-secondary-dark; }
      }
      ::v-deep .ant-pagination {
        .ant-pagination-item {
          background: @bg-card-dark;
          border-color: @border-dark;
          a { color: @text-primary-dark; }
          &.ant-pagination-item-active {
            background: @blue;
            border-color: @blue;
          }
        }
        .ant-pagination-prev, .ant-pagination-next {
          .ant-pagination-item-link {
            background: @bg-card-dark;
            border-color: @border-dark;
            color: @text-primary-dark;
          }
        }
      }
    }
  }

  // KPI Grid
  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px;
    margin-bottom: 20px;
  }

  .kpi-card {
    position: relative;
    background: @bg-card-light;
    border: 1px solid @border-light;
    border-radius: 16px;
    padding: 20px;
    overflow: hidden;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);

    &:hover {
      transform: translateY(-2px);
      box-shadow: 0 10px 40px rgba(0, 0, 0, 0.1);
    }

    &.clickable {
      cursor: pointer;
      .card-arrow {
        position: absolute;
        right: 16px;
        top: 50%;
        transform: translateY(-50%);
        opacity: 0.4;
        transition: all 0.3s;
      }
      &:hover .card-arrow {
        opacity: 1;
        right: 12px;
      }
    }

    .kpi-glow {
      position: absolute;
      top: -50%;
      right: -50%;
      width: 100%;
      height: 100%;
      background: radial-gradient(circle, rgba(59, 130, 246, 0.15) 0%, transparent 70%);
      pointer-events: none;
    }

    .kpi-content {
      position: relative;
      z-index: 1;
    }

    .kpi-header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 12px;
    }

    .kpi-icon {
      width: 32px;
      height: 32px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 8px;
      background: rgba(59, 130, 246, 0.1);
      color: @blue;
      font-size: 16px;
    }

    .kpi-label {
      font-size: 12px;
      font-weight: 600;
      color: @text-secondary-light;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .kpi-value {
      display: flex;
      align-items: baseline;
      gap: 2px;

      .currency {
        font-size: 18px;
        font-weight: 500;
        color: @text-secondary-light;
      }

      .amount {
        font-size: 28px;
        font-weight: 700;
        color: @text-primary-light;
        font-feature-settings: 'tnum';
      }

      .unit {
        font-size: 14px;
        font-weight: 500;
        color: @text-secondary-light;
        margin-left: 4px;
      }
    }

    .kpi-sub {
      margin-top: 8px;
      font-size: 12px;
      color: @text-secondary-light;

      .label { margin: 0 2px; }
      .divider { margin: 0 6px; opacity: 0.5; }
      .highlight { font-weight: 600; color: @blue; }
    }

    // Primary card with gradient
    &.kpi-primary {
      background: linear-gradient(135deg, #1e40af 0%, #3b82f6 50%, #60a5fa 100%);
      border: none;

      .kpi-icon {
        background: rgba(255, 255, 255, 0.2);
        color: #fff;
      }
      .kpi-label { color: rgba(255, 255, 255, 0.8); }
      .kpi-value {
        .currency, .amount, .unit { color: #fff; }
      }
      .kpi-sub { color: rgba(255, 255, 255, 0.7); }
    }

    // Win rate ring
    &.kpi-win-rate {
      .kpi-ring {
        position: absolute;
        right: 12px;
        top: 50%;
        transform: translateY(-50%);
        width: 60px;
        height: 60px;

        svg {
          transform: rotate(-90deg);

          .ring-bg {
            fill: none;
            stroke: rgba(16, 185, 129, 0.15);
            stroke-width: 3;
          }

          .ring-progress {
            fill: none;
            stroke: @green;
            stroke-width: 3;
            stroke-linecap: round;
            transition: stroke-dasharray 0.5s ease;
          }
        }
      }
      .kpi-icon { background: rgba(16, 185, 129, 0.1); color: @green; }
    }

    &.kpi-profit-factor {
      .kpi-icon { background: rgba(139, 92, 246, 0.1); color: @purple; }
    }

    &.kpi-drawdown {
      .kpi-icon { background: rgba(239, 68, 68, 0.1); color: @red; }
      .kpi-value .amount { color: @red; }
    }

    &.kpi-trades {
      .kpi-icon { background: rgba(6, 182, 212, 0.1); color: @cyan; }
    }

    &.kpi-strategies {
      .kpi-icon { background: rgba(245, 158, 11, 0.1); color: @amber; }
    }
  }

  // Chart panels
  .chart-row {
    display: flex;
    gap: 16px;
    margin-bottom: 16px;

    @media (max-width: 1024px) {
      flex-direction: column;
    }
  }

  .chart-panel {
    background: @bg-card-light;
    border: 1px solid @border-light;
    border-radius: 16px;
    overflow: hidden;

    &.chart-main { flex: 2; }
    &.chart-side { flex: 1; min-width: 300px; }
    &.chart-half { flex: 1; }

    .panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 16px 20px;
      border-bottom: 1px solid @border-light;
    }

    .panel-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 14px;
      font-weight: 600;
      color: @text-primary-light;

      .anticon { color: @blue; }
    }

    .panel-legend {
      display: flex;
      gap: 16px;
      font-size: 12px;
      color: @text-secondary-light;

      .legend-item {
        display: flex;
        align-items: center;
        gap: 6px;

        .dot {
          width: 10px;
          height: 10px;
          border-radius: 2px;

          &.bar { background: linear-gradient(180deg, @green-light, @green); }
          &.line { background: linear-gradient(90deg, @blue, @purple); }
          &.loss { background: @red; }
          &.profit { background: @green; }
        }
      }

      &.calendar-legend {
        align-items: center;
        gap: 10px;

        .legend-gradient {
          width: 80px;
          height: 10px;
          border-radius: 3px;
          background: linear-gradient(90deg, #ef4444, #fca5a5, #f4f4f5, #86efac, #22c55e);
        }
      }
    }

    .panel-badge {
      background: @blue;
      color: #fff;
      font-size: 11px;
      font-weight: 600;
      padding: 2px 8px;
      border-radius: 10px;
    }

    .chart-body {
      height: 320px;
      padding: 16px;

      &.chart-sm { height: 220px; }
      &.calendar-chart { height: 280px; }
    }

    .calendar-nav {
      display: flex;
      align-items: center;
      gap: 8px;

      .current-month {
        font-size: 14px;
        font-weight: 600;
        color: @text-primary-light;
        min-width: 80px;
        text-align: center;
      }

      .ant-btn-link {
        padding: 0;
        height: auto;
        color: @text-secondary-light;

        &:hover:not(:disabled) {
          color: @blue;
        }

        &:disabled {
          opacity: 0.3;
        }
      }
    }

    .profit-calendar {
      padding: 12px 16px;
      display: flex;
      flex-direction: column;
      overflow: hidden;

      .calendar-empty {
        height: 280px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        color: @text-secondary-light;

        .anticon {
          font-size: 40px;
          margin-bottom: 10px;
          opacity: 0.3;
        }
      }

      .month-summary {
        display: flex;
        gap: 20px;
        margin-bottom: 10px;
        padding: 8px 12px;
        background: rgba(241, 245, 249, 0.5);
        border-radius: 8px;

        .summary-item {
          display: flex;
          flex-direction: column;
          gap: 2px;

          .summary-label {
            font-size: 10px;
            color: @text-secondary-light;
            text-transform: uppercase;
            letter-spacing: 0.5px;
          }

          .summary-value {
            font-size: 15px;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;

            &.positive { color: @green; }
            &.negative { color: @red; }
          }
        }
      }

      .calendar-weekdays {
        display: grid;
        grid-template-columns: repeat(7, 1fr);
        gap: 3px;
        margin-bottom: 4px;

        .weekday {
          text-align: center;
          font-size: 10px;
          font-weight: 600;
          color: @text-secondary-light;
          padding: 4px 0;
        }
      }

      .calendar-grid {
        display: grid;
        grid-template-columns: repeat(7, 1fr);
        gap: 3px;

        .calendar-cell {
          height: 36px;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          border-radius: 6px;
          background: rgba(241, 245, 249, 0.5);
          border: 1px solid transparent;
          transition: all 0.2s ease;
          position: relative;

          &.empty {
            background: transparent;
            border: none;
          }

          &.no-data {
            background: rgba(241, 245, 249, 0.3);
          }

          &.profit {
            background: linear-gradient(135deg, rgba(34, 197, 94, 0.12) 0%, rgba(34, 197, 94, 0.2) 100%);
            border-color: rgba(34, 197, 94, 0.3);

            &:hover {
              background: linear-gradient(135deg, rgba(34, 197, 94, 0.2) 0%, rgba(34, 197, 94, 0.3) 100%);
              transform: translateY(-2px);
              box-shadow: 0 4px 12px rgba(34, 197, 94, 0.2);
            }
          }

          &.loss {
            background: linear-gradient(135deg, rgba(239, 68, 68, 0.12) 0%, rgba(239, 68, 68, 0.2) 100%);
            border-color: rgba(239, 68, 68, 0.3);

            &:hover {
              background: linear-gradient(135deg, rgba(239, 68, 68, 0.2) 0%, rgba(239, 68, 68, 0.3) 100%);
              transform: translateY(-2px);
              box-shadow: 0 4px 12px rgba(239, 68, 68, 0.2);
            }
          }

          &.zero {
            background: rgba(161, 161, 170, 0.1);
            border-color: rgba(161, 161, 170, 0.2);
          }

          .day-number {
            font-size: 11px;
            font-weight: 600;
            color: @text-primary-light;
            line-height: 1;
          }

          .day-profit {
            font-size: 9px;
            font-weight: 600;
            font-family: 'JetBrains Mono', monospace;
            margin-top: 1px;
            line-height: 1;

            &.positive { color: @green; }
            &.negative { color: @red; }
          }
        }
      }
    }
  }

  // Strategy ranking
  .strategy-ranking {
    padding: 16px;

    .empty-state {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 40px;
      color: @text-secondary-light;

      .anticon { font-size: 40px; margin-bottom: 12px; opacity: 0.3; }
    }

    .ranking-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 12px;
    }

    .ranking-card {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 14px 16px;
      background: rgba(241, 245, 249, 0.5);
      border: 1px solid @border-light;
      border-radius: 12px;
      position: relative;
      overflow: hidden;

      &.rank-top {
        border-color: transparent;
        background: linear-gradient(135deg, rgba(59, 130, 246, 0.08) 0%, rgba(139, 92, 246, 0.08) 100%);
      }

      .rank-badge {
        width: 28px;
        height: 28px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 700;
        background: @text-secondary-light;
        color: #fff;
        flex-shrink: 0;

        &.rank-1 { background: linear-gradient(135deg, #fbbf24, #f59e0b); }
        &.rank-2 { background: linear-gradient(135deg, #9ca3af, #6b7280); }
        &.rank-3 { background: linear-gradient(135deg, #cd7f32, #b87333); }
      }

      .rank-info {
        flex: 1;
        min-width: 0;

        .rank-name {
          font-size: 13px;
          font-weight: 600;
          color: @text-primary-light;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          margin-bottom: 4px;
        }

        .rank-stats {
          display: flex;
          gap: 12px;
          flex-wrap: wrap;

          .stat {
            font-size: 11px;

            label {
              color: @text-secondary-light;
              margin-right: 4px;
            }
          }
        }
      }

      .rank-pnl-bar {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 3px;
        background: rgba(0, 0, 0, 0.05);

        .bar-fill {
          height: 100%;
          border-radius: 0 3px 3px 0;
          transition: width 0.5s ease;

          &.positive { background: linear-gradient(90deg, @green, @green-light); }
          &.negative { background: linear-gradient(90deg, @red, @red-light); }
        }
      }
    }
  }

  // Table panels
  .table-row {
    display: flex;
    gap: 16px;
    margin-bottom: 16px;

    @media (max-width: 1024px) {
      flex-direction: column;
    }
  }

  .table-panel {
    flex: 1;
    background: @bg-card-light;
    border: 1px solid @border-light;
    border-radius: 16px;
    overflow: hidden;

    .panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 16px 20px;
      border-bottom: 1px solid @border-light;
    }

    .panel-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 14px;
      font-weight: 600;
      color: @text-primary-light;

      .anticon { color: @blue; }

      .sound-toggle {
        margin-left: 8px;
        font-size: 16px;
        cursor: pointer;
        color: @green;
        transition: all 0.2s;

        &:hover {
          transform: scale(1.1);
        }

        &.sound-off {
          color: @text-secondary-light;
        }
      }
    }

    .panel-badge {
      background: @blue;
      color: #fff;
      font-size: 11px;
      font-weight: 600;
      padding: 2px 8px;
      border-radius: 10px;
    }
  }

  .orders-panel {
    margin-bottom: 20px;
  }

  // Pro table styles
  .pro-table {
    ::v-deep .ant-table {
      font-size: 13px;
    }

    ::v-deep .ant-table-thead > tr > th {
      background: rgba(241, 245, 249, 0.8);
      font-weight: 600;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: @text-secondary-light;
      border-bottom: 1px solid @border-light;
      padding: 12px 16px;
    }

    ::v-deep .ant-table-tbody > tr > td {
      padding: 12px 16px;
      border-bottom: 1px solid @border-light;
    }

    ::v-deep .ant-table-tbody > tr:hover > td {
      background: rgba(59, 130, 246, 0.04);
    }

    ::v-deep .ant-pagination {
      padding: 12px 16px;
      margin: 0;
    }
  }

  // Cell styles
  .symbol-cell {
    .symbol-name {
      font-weight: 600;
      display: block;
    }
    .symbol-strategy {
      font-size: 11px;
      color: @text-secondary-light;
    }
  }

  .side-tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;

    &.long {
      background: rgba(16, 185, 129, 0.1);
      color: @green;
    }
    &.short {
      background: rgba(239, 68, 68, 0.1);
      color: @red;
    }
  }

  .type-tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;

    &.long {
      background: rgba(16, 185, 129, 0.1);
      color: @green;
    }
    &.short {
      background: rgba(239, 68, 68, 0.1);
      color: @red;
    }
    &.close-long {
      background: rgba(245, 158, 11, 0.1);
      color: @amber;
    }
    &.close-short {
      background: rgba(139, 92, 246, 0.1);
      color: @purple;
    }
  }

  .symbol-tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
    background: rgba(59, 130, 246, 0.1);
    color: @blue;
  }

  .exchange-tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;

    &.binance { background: rgba(240, 185, 11, 0.1); color: #f0b90b; }
    &.okx { background: rgba(139, 92, 246, 0.1); color: @purple; }
    &.bitget { background: rgba(6, 182, 212, 0.1); color: @cyan; }
    &.signal { background: rgba(59, 130, 246, 0.1); color: @blue; }
  }

  .market-type {
    font-size: 10px;
    color: @text-secondary-light;
    margin-top: 2px;
  }

  .status-tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;

    &.pending { background: rgba(245, 158, 11, 0.1); color: @amber; }
    &.processing { background: rgba(59, 130, 246, 0.1); color: @blue; }
    &.completed { background: rgba(16, 185, 129, 0.1); color: @green; }
    &.failed { background: rgba(239, 68, 68, 0.1); color: @red; }
    &.cancelled { background: rgba(100, 116, 139, 0.1); color: @text-secondary-light; }
  }

  .error-hint {
    font-size: 11px;
    color: @red;
    margin-top: 4px;
    cursor: pointer;

    .anticon { margin-right: 4px; }
  }

  .notify-icons {
    display: flex;
    gap: 8px;

    .notify-icon {
      color: @text-secondary-light;
      font-size: 14px;
    }
  }

  .pnl-cell {
    text-align: right;

    .pnl-percent {
      display: block;
      font-size: 11px;
    }
  }

  .time-cell {
    font-size: 12px;
    color: @text-secondary-light;
  }

  .sub-text {
    font-size: 11px;
    color: @text-secondary-light;
  }

  .text-muted {
    color: @text-secondary-light;
  }

  .positive { color: @green; }
  .negative { color: @red; }

  // Responsive
  @media (max-width: 768px) {
    padding: 12px;

    .kpi-grid {
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
    }

    .kpi-card {
      padding: 14px;

      .kpi-value .amount {
        font-size: 22px;
      }

      &.kpi-win-rate .kpi-ring {
        width: 48px;
        height: 48px;
        right: 8px;
      }
    }

    .chart-panel .chart-body {
      height: 260px;
      padding: 12px;

      &.chart-sm { height: 180px; }
    }

    .ranking-grid {
      grid-template-columns: 1fr;
    }
  }
}
</style>
