<template>
  <div class="trading-assistant" :class="{ 'theme-dark': isDarkTheme }">
    <a-row :gutter="24" class="strategy-layout">
      <!-- 左侧：策略列表 -->
      <a-col
        :xs="24"
        :sm="24"
        :md="10"
        :lg="8"
        :xl="8"
        class="strategy-list-col">
        <a-card :bordered="false" class="strategy-list-card">
          <div slot="title" class="card-title">
            <span>{{ $t('trading-assistant.strategyList') }}</span>
            <a-button type="primary" size="small" @click="handleCreateStrategy">
              <a-icon type="plus" />
              {{ $t('trading-assistant.createStrategy') }}
            </a-button>
          </div>

          <!-- 分组方式切换 -->
          <div class="group-mode-switch">
            <span class="group-mode-label">{{ $t('trading-assistant.groupBy') }}:</span>
            <a-radio-group v-model="groupByMode" size="small" button-style="solid">
              <a-radio-button value="strategy">
                <a-icon type="folder" />
                {{ $t('trading-assistant.groupByStrategy') }}
              </a-radio-button>
              <a-radio-button value="symbol">
                <a-icon type="stock" />
                {{ $t('trading-assistant.groupBySymbol') }}
              </a-radio-button>
            </a-radio-group>
          </div>

          <a-spin :spinning="loading">
            <a-empty v-if="!loading && strategies.length === 0" :description="$t('trading-assistant.noStrategy')" />
            <div v-else class="strategy-grouped-list">
              <!-- 策略组列表 -->
              <div v-for="group in groupedStrategies.groups" :key="group.id" class="strategy-group">
                <!-- 策略组头部 -->
                <div class="strategy-group-header" @click="toggleGroup(group.id)">
                  <div class="group-header-left">
                    <a-icon :type="collapsedGroups[group.id] ? 'right' : 'down'" class="collapse-icon" />
                    <a-icon :type="groupByMode === 'symbol' ? 'stock' : 'folder'" class="group-icon" />
                    <span class="group-name">{{ group.baseName }}</span>
                    <a-tag size="small" color="blue">{{ group.strategies.length }} {{
                      groupByMode === 'symbol' ? $t('trading-assistant.strategyCount') : $t('trading-assistant.symbolCount') }}</a-tag>
                  </div>
                  <div class="group-header-right" @click.stop>
                    <span v-if="group.runningCount > 0" class="group-status running">
                      {{ group.runningCount }} {{ $t('trading-assistant.status.running') }}
                    </span>
                    <span v-if="group.stoppedCount > 0" class="group-status stopped">
                      {{ group.stoppedCount }} {{ $t('trading-assistant.status.stopped') }}
                    </span>
                    <a-dropdown :getPopupContainer="getDropdownContainer" :trigger="['click']">
                      <a-menu slot="overlay" @click="({ key }) => handleGroupMenuClick(key, group)">
                        <a-menu-item key="startAll">
                          <a-icon type="play-circle" />
                          {{ $t('trading-assistant.startAll') }}
                        </a-menu-item>
                        <a-menu-item key="stopAll">
                          <a-icon type="pause-circle" />
                          {{ $t('trading-assistant.stopAll') }}
                        </a-menu-item>
                        <a-menu-divider />
                        <a-menu-item key="deleteAll" class="danger-item">
                          <a-icon type="delete" />
                          {{ $t('trading-assistant.deleteAll') }}
                        </a-menu-item>
                      </a-menu>
                      <a-button type="link" icon="more" size="small" />
                    </a-dropdown>
                  </div>
                </div>
                <!-- 策略组内的策略列表（可折叠） -->
                <div v-show="!collapsedGroups[group.id]" class="strategy-group-content">
                  <div
                    v-for="item in group.strategies"
                    :key="item.id"
                    :class="['strategy-list-item', { active: selectedStrategy && selectedStrategy.id === item.id }]"
                    @click="handleSelectStrategy(item)">
                    <div class="strategy-item-content">
                      <div class="strategy-item-header">
                        <div class="strategy-name-wrapper">
                          <!-- 按策略分组：显示 Symbol -->
                          <template v-if="groupByMode === 'strategy'">
                            <span class="info-item" v-if="item.trading_config && item.trading_config.symbol">
                              <a-icon type="dollar" />
                              {{ item.trading_config.symbol }}
                            </span>
                          </template>
                          <!-- 按 Symbol 分组：显示策略名称、周期、指标 -->
                          <template v-else>
                            <span class="info-item strategy-name-text">
                              <a-icon type="thunderbolt" />
                              {{ item.displayInfo ? item.displayInfo.strategyName : item.strategy_name }}
                            </span>
                            <a-tag size="small" color="cyan" v-if="item.displayInfo && item.displayInfo.timeframe">
                              <a-icon type="clock-circle" style="margin-right: 2px;" />
                              {{ item.displayInfo.timeframe }}
                            </a-tag>
                            <a-tag size="small" color="purple" v-if="item.displayInfo && item.displayInfo.indicatorName && item.displayInfo.indicatorName !== '-'">
                              <a-icon type="line-chart" style="margin-right: 2px;" />
                              {{ item.displayInfo.indicatorName }}
                            </a-tag>
                          </template>
                          <span
                            class="status-label"
                            :class="[
                              item.status ? `status-${item.status}` : '',
                              { 'status-stopped': item.status === 'stopped' }
                            ]">
                            {{ getStatusText(item.status) }}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div class="strategy-item-actions" @click.stop>
                      <a-dropdown :getPopupContainer="getDropdownContainer" :trigger="['click']">
                        <a-menu slot="overlay" @click="({ key }) => handleMenuClick(key, item)">
                          <a-menu-item v-if="item.status === 'stopped'" key="start">
                            <a-icon type="play-circle" />
                            {{ $t('trading-assistant.startStrategy') }}
                          </a-menu-item>
                          <a-menu-item v-if="item.status === 'running'" key="stop">
                            <a-icon type="pause-circle" />
                            {{ $t('trading-assistant.stopStrategy') }}
                          </a-menu-item>
                          <a-menu-divider />
                          <a-menu-item key="edit">
                            <a-icon type="edit" />
                            {{ $t('trading-assistant.editStrategy') }}
                          </a-menu-item>
                          <a-menu-divider />
                          <a-menu-item key="delete" class="danger-item">
                            <a-icon type="delete" />
                            {{ $t('trading-assistant.deleteStrategy') }}
                          </a-menu-item>
                        </a-menu>
                        <a-button type="link" icon="more" size="small" />
                      </a-dropdown>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 未分组的策略列表 -->
              <div
                v-for="item in groupedStrategies.ungrouped"
                :key="item.id"
                :class="['strategy-list-item', { active: selectedStrategy && selectedStrategy.id === item.id }]"
                @click="handleSelectStrategy(item)">
                <div class="strategy-item-content">
                  <div class="strategy-item-header">
                    <div class="strategy-name-wrapper">
                      <a-tag
                        v-if="item.exchange_config && item.exchange_config.exchange_id"
                        :color="getExchangeTagColor(item.exchange_config.exchange_id)"
                        size="small"
                        class="exchange-tag">
                        <a-icon type="bank" style="margin-right: 4px;" />
                        {{ getExchangeDisplayName(item.exchange_config.exchange_id) }}
                      </a-tag>
                      <span class="strategy-name">{{ item.strategy_name }}</span>
                      <a-tag
                        v-if="item.strategy_type === 'PromptBasedStrategy'"
                        color="purple"
                        size="small"
                        class="strategy-type-tag">
                        <a-icon type="robot" style="margin-right: 2px;" />
                        AI
                      </a-tag>
                    </div>
                  </div>
                  <div class="strategy-item-info">
                    <span class="info-item" v-if="item.trading_config && item.trading_config.symbol">
                      <a-icon type="dollar" />
                      {{ item.trading_config.symbol }}
                    </span>
                    <span
                      class="status-label"
                      :class="[
                        item.status ? `status-${item.status}` : '',
                        { 'status-stopped': item.status === 'stopped' }
                      ]">
                      {{ getStatusText(item.status) }}
                    </span>
                  </div>
                </div>
                <div class="strategy-item-actions" @click.stop>
                  <a-dropdown :getPopupContainer="getDropdownContainer" :trigger="['click']">
                    <a-menu slot="overlay" @click="({ key }) => handleMenuClick(key, item)">
                      <a-menu-item v-if="item.status === 'stopped'" key="start">
                        <a-icon type="play-circle" />
                        {{ $t('trading-assistant.startStrategy') }}
                      </a-menu-item>
                      <a-menu-item v-if="item.status === 'running'" key="stop">
                        <a-icon type="pause-circle" />
                        {{ $t('trading-assistant.stopStrategy') }}
                      </a-menu-item>
                      <a-menu-divider />
                      <a-menu-item key="edit">
                        <a-icon type="edit" />
                        {{ $t('trading-assistant.editStrategy') }}
                      </a-menu-item>
                      <a-menu-divider />
                      <a-menu-item key="delete" class="danger-item">
                        <a-icon type="delete" />
                        {{ $t('trading-assistant.deleteStrategy') }}
                      </a-menu-item>
                    </a-menu>
                    <a-button type="link" icon="more" size="small" />
                  </a-dropdown>
                </div>
              </div>
            </div>
          </a-spin>
        </a-card>
      </a-col>

      <!-- 右侧：策略详情和交易记录 -->
      <a-col
        :xs="24"
        :sm="24"
        :md="14"
        :lg="16"
        :xl="16"
        class="strategy-detail-col">
        <div v-if="!selectedStrategy" class="empty-detail">
          <a-empty :description="$t('trading-assistant.selectStrategy')" />
        </div>

        <div v-else class="strategy-detail-panel">
          <!-- 策略头部信息 -->
          <a-card :bordered="false" class="strategy-header-card">
            <div class="strategy-header">
              <div class="header-left">
                <div class="strategy-title-row">
                  <h3 class="strategy-title">{{ selectedStrategy.strategy_name }}</h3>
                  <div class="status-badge" :class="[`status-${selectedStrategy.status}`]">
                    <span class="status-dot"></span>
                    {{ getStatusText(selectedStrategy.status) }}
                  </div>
                </div>

                <!-- 关键数据卡片 -->
                <div class="key-stats-grid">
                  <div
                    class="stat-card"
                    v-if="selectedStrategy.initial_capital || (selectedStrategy.trading_config && selectedStrategy.trading_config.initial_capital)">
                    <div class="stat-icon investment">
                      <a-icon type="wallet" />
                    </div>
                    <div class="stat-content">
                      <div class="stat-label">{{ $t('trading-assistant.detail.totalInvestment') }}</div>
                      <div class="stat-value">${{ ((selectedStrategy.initial_capital ||
                      selectedStrategy.trading_config?.initial_capital) || 0).toLocaleString() }}</div>
                    </div>
                  </div>
                  <div class="stat-card" v-if="currentEquity !== null">
                    <div class="stat-icon equity">
                      <a-icon type="fund" />
                    </div>
                    <div class="stat-content">
                      <div class="stat-label">{{ $t('trading-assistant.detail.currentEquity') }}</div>
                      <div class="stat-value" :class="getEquityColorClass">{{ formatCurrency(currentEquity) }}</div>
                    </div>
                  </div>
                  <div
                    class="stat-card pnl-card"
                    v-if="totalPnl !== null"
                    :class="{ 'profit': totalPnl > 0, 'loss': totalPnl < 0 }">
                    <div class="stat-icon pnl">
                      <a-icon :type="totalPnl >= 0 ? 'rise' : 'fall'" />
                    </div>
                    <div class="stat-content">
                      <div class="stat-label">{{ $t('trading-assistant.detail.totalPnl') }}</div>
                      <div class="stat-value" :class="getPnlColorClass">
                        {{ formatPnl(totalPnl) }}
                        <span class="pnl-percent">({{ formatPnlPercent(totalPnlPercent) }})</span>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- 策略详情标签 -->
                <div class="strategy-tags">
                  <div class="tag-item" v-if="selectedStrategy.trading_config">
                    <a-icon type="stock" />
                    <span>{{ selectedStrategy.trading_config.symbol }}</span>
                  </div>
                  <div
                    class="tag-item"
                    v-if="selectedStrategy.indicator_config && selectedStrategy.indicator_config.indicator_name">
                    <a-icon type="line-chart" />
                    <span>{{ selectedStrategy.indicator_config.indicator_name }}</span>
                  </div>
                  <div class="tag-item" v-if="selectedStrategy.trading_config">
                    <a-icon type="thunderbolt" />
                    <span>{{ selectedStrategy.trading_config.leverage || 1 }}x</span>
                  </div>
                  <div
                    class="tag-item"
                    v-if="selectedStrategy.trading_config && selectedStrategy.trading_config.trade_direction">
                    <a-icon type="swap" />
                    <span>{{ getTradeDirectionText(selectedStrategy.trading_config.trade_direction) }}</span>
                  </div>
                  <div
                    class="tag-item"
                    v-if="selectedStrategy.trading_config && selectedStrategy.trading_config.timeframe">
                    <a-icon type="clock-circle" />
                    <span>{{ selectedStrategy.trading_config.timeframe }}</span>
                  </div>
                </div>
              </div>
              <div class="header-right">
                <a-button
                  v-if="selectedStrategy.status === 'stopped'"
                  type="primary"
                  size="large"
                  class="action-btn start-btn"
                  @click="handleStartStrategy(selectedStrategy.id)">
                  <a-icon type="play-circle" />
                  {{ $t('trading-assistant.startStrategy') }}
                </a-button>
                <a-button
                  v-if="selectedStrategy.status === 'running'"
                  type="danger"
                  size="large"
                  class="action-btn stop-btn"
                  @click="handleStopStrategy(selectedStrategy.id)">
                  <a-icon type="pause-circle" />
                  {{ $t('trading-assistant.stopStrategy') }}
                </a-button>
              </div>
            </div>
          </a-card>

          <!-- 策略详情标签页 -->
          <a-card :bordered="false" class="strategy-content-card">
            <a-tabs defaultActiveKey="positions">
              <a-tab-pane key="positions" :tab="$t('trading-assistant.tabs.positions')">
                <position-records
                  :strategy-id="selectedStrategy.id"
                  :market-type="(selectedStrategy.trading_config && selectedStrategy.trading_config.market_type) || 'swap'"
                  :leverage="(selectedStrategy.trading_config && selectedStrategy.trading_config.leverage) || 1"
                  :loading="loadingRecords" />
              </a-tab-pane>
              <a-tab-pane key="trades" :tab="$t('trading-assistant.tabs.tradingRecords')">
                <trading-records :strategy-id="selectedStrategy.id" :loading="loadingRecords" />
              </a-tab-pane>
            </a-tabs>
          </a-card>
        </div>
      </a-col>
    </a-row>

    <!-- 创建/编辑策略弹窗 - 合并版本 -->
    <a-modal
      :visible="showFormModal"
      :title="editingStrategy ? $t('trading-assistant.editStrategy') : $t('trading-assistant.createStrategy')"
      :width="isMobile ? '95%' : 1100"
      :confirmLoading="saving"
      @ok="handleSubmit"
      @cancel="handleCloseModal"
      :maskClosable="false"
      :wrapClassName="isMobile ? 'mobile-modal' : ''"
      :bodyStyle="{ maxHeight: '70vh', overflowY: 'auto' }">
      <a-spin :spinning="loadingIndicators">
        <a-steps :current="currentStep" class="steps-container">
          <a-step :title="$t('trading-assistant.form.step1')" />
          <a-step :title="$t('trading-assistant.form.step2Params')" />
          <a-step :title="$t('trading-assistant.form.step3Signal')" />
        </a-steps>

        <div class="form-container">
          <!-- 步骤1: 指标策略-选择技术指标 / AI策略-基础配置 -->
          <div v-show="currentStep === 0" class="step-content">
            <!-- 指标策略：选择技术指标 -->
            <div v-if="strategyType === 'indicator'">
              <a-form :form="form" layout="vertical">
                <a-form-item :label="$t('trading-assistant.form.indicator')">
                  <a-select
                    v-decorator="['indicator_id', { rules: [{ required: true, message: $t('trading-assistant.validation.indicatorRequired') }] }]"
                    :placeholder="$t('trading-assistant.placeholders.selectIndicator')"
                    show-search
                    :filter-option="filterIndicatorOption"
                    @focus="handleIndicatorSelectFocus"
                    @change="handleIndicatorChange"
                    :loading="loadingIndicators"
                    :getPopupContainer="(triggerNode) => triggerNode.parentNode">
                    <a-select-option
                      v-for="indicator in availableIndicators"
                      :key="String(indicator.id)"
                      :value="String(indicator.id)">
                      <div class="indicator-option">
                        <span class="indicator-name">{{ indicator.name }}</span>
                        <a-tag v-if="indicator.type" size="small" :color="getIndicatorTypeColor(indicator.type)">
                          {{ getIndicatorTypeName(indicator.type) }}
                        </a-tag>
                      </div>
                    </a-select-option>
                  </a-select>
                  <div class="form-item-hint">
                    {{ $t('trading-assistant.form.indicatorHint') }}
                  </div>
                </a-form-item>

                <a-form-item v-if="selectedIndicator" :label="$t('trading-assistant.form.indicatorDescription')">
                  <div class="indicator-description">
                    {{ selectedIndicator.description || $t('trading-assistant.form.noDescription') }}
                  </div>
                </a-form-item>

                <!-- 指标参数配置 -->
                <a-form-item v-if="indicatorParams.length > 0" :label="$t('trading-assistant.form.indicatorParams')">
                  <div class="indicator-params-form">
                    <a-row :gutter="16">
                      <a-col v-for="param in indicatorParams" :key="param.name" :xs="24" :sm="12" :md="8">
                        <div class="param-item">
                          <label class="param-label">
                            {{ param.name }}
                            <a-tooltip v-if="param.description" :title="param.description">
                              <a-icon type="question-circle" style="margin-left: 4px; color: #999;" />
                            </a-tooltip>
                          </label>
                          <!-- 整数类型 -->
                          <a-input-number
                            v-if="param.type === 'int'"
                            v-model="indicatorParamValues[param.name]"
                            :precision="0"
                            style="width: 100%;"
                            size="small" />
                          <!-- 浮点数类型 -->
                          <a-input-number
                            v-else-if="param.type === 'float'"
                            v-model="indicatorParamValues[param.name]"
                            :precision="4"
                            style="width: 100%;"
                            size="small" />
                          <!-- 布尔类型 -->
                          <a-switch
                            v-else-if="param.type === 'bool'"
                            v-model="indicatorParamValues[param.name]"
                            size="small" />
                          <!-- 字符串类型 -->
                          <a-input
                            v-else
                            v-model="indicatorParamValues[param.name]"
                            size="small" />
                        </div>
                      </a-col>
                    </a-row>
                    <div class="form-item-hint" style="margin-top: 8px;">
                      {{ $t('trading-assistant.form.indicatorParamsHint') }}
                    </div>
                  </div>
                </a-form-item>

                <a-divider />

                <a-form-item :label="$t('trading-assistant.form.strategyName')">
                  <a-input
                    v-decorator="['strategy_name', { rules: [{ required: true, message: $t('trading-assistant.validation.strategyNameRequired') }] }]"
                    :placeholder="$t('trading-assistant.placeholders.inputStrategyName')" />
                </a-form-item>

                <a-form-item
                  :label="isEditMode ? $t('trading-assistant.form.symbol') : $t('trading-assistant.form.symbols')">
                  <!-- 编辑模式：单选 -->
                  <a-select
                    v-if="isEditMode"
                    v-decorator="['symbol', { rules: [{ required: true, message: $t('trading-assistant.validation.symbolRequired') }] }]"
                    :placeholder="$t('trading-assistant.placeholders.selectSymbol')"
                    show-search
                    :filter-option="filterWatchlistOption"
                    :loading="loadingWatchlist"
                    @change="handleWatchlistSymbolChange"
                    :getPopupContainer="(triggerNode) => triggerNode.parentNode">
                    <a-select-option
                      v-for="item in watchlist"
                      :key="`${item.market}:${item.symbol}`"
                      :value="`${item.market}:${item.symbol}`">
                      <div class="symbol-option">
                        <a-tag :color="getMarketColor(item.market)" style="margin-right: 8px; margin-bottom: 0;">
                          {{ item.market }}
                        </a-tag>
                        <span class="symbol-name">{{ item.symbol }}</span>
                        <span v-if="item.name" class="symbol-name-extra">{{ item.name }}</span>
                      </div>
                    </a-select-option>
                    <!-- 添加交易对选项 -->
                    <a-select-option key="__add_symbol_option__" value="__add_symbol_option__" class="add-symbol-option">
                      <div style="width: 100%; text-align: center; padding: 4px 0; color: #1890ff; cursor: pointer;">
                        <a-icon type="plus" style="margin-right: 4px;" />
                        <span>{{ $t('trading-assistant.form.addSymbol') }}</span>
                      </div>
                    </a-select-option>
                  </a-select>
                  <!-- 创建模式：多选 -->
                  <a-select
                    v-else
                    v-model="selectedSymbols"
                    mode="multiple"
                    :placeholder="$t('trading-assistant.placeholders.selectSymbols')"
                    show-search
                    :filter-option="filterWatchlistOptionWithAdd"
                    :loading="loadingWatchlist"
                    @change="handleMultiSymbolChangeWithAdd"
                    :getPopupContainer="(triggerNode) => triggerNode.parentNode"
                    :maxTagCount="3">
                    <a-select-option
                      v-for="item in watchlist"
                      :key="`${item.market}:${item.symbol}`"
                      :value="`${item.market}:${item.symbol}`">
                      <div class="symbol-option">
                        <a-tag :color="getMarketColor(item.market)" style="margin-right: 8px; margin-bottom: 0;">
                          {{ item.market }}
                        </a-tag>
                        <span class="symbol-name">{{ item.symbol }}</span>
                        <span v-if="item.name" class="symbol-name-extra">{{ item.name }}</span>
                      </div>
                    </a-select-option>
                    <!-- 添加交易对选项 -->
                    <a-select-option key="__add_symbol_option__" value="__add_symbol_option__" class="add-symbol-option">
                      <div style="width: 100%; text-align: center; padding: 4px 0; color: #1890ff; cursor: pointer;">
                        <a-icon type="plus" style="margin-right: 4px;" />
                        <span>{{ $t('trading-assistant.form.addSymbol') }}</span>
                      </div>
                    </a-select-option>
                  </a-select>
                  <div class="form-item-hint">
                    {{ isEditMode ? $t('trading-assistant.form.symbolHintCrypto') :
                      $t('trading-assistant.form.symbolsHint') }}
                  </div>
                </a-form-item>

                <a-row :gutter="16">
                  <a-col :xs="24" :sm="24" :md="12" :lg="12">
                    <a-form-item :label="$t('trading-assistant.form.initialCapital')">
                      <a-input-number
                        v-decorator="['initial_capital', { rules: [{ required: true, message: $t('trading-assistant.validation.initialCapitalRequired') }], initialValue: 1000 }]"
                        :min="10"
                        :step="100"
                        :precision="2"
                        style="width: 100%" />
                    </a-form-item>
                  </a-col>
                  <a-col :xs="24" :sm="24" :md="12" :lg="12">
                    <a-form-item :label="$t('trading-assistant.form.marketType')">
                      <a-radio-group
                        v-decorator="['market_type', { initialValue: 'swap' }]"
                        @change="handleMarketTypeChange">
                        <a-radio value="swap">{{ $t('trading-assistant.form.marketTypeFutures') }}</a-radio>
                        <a-radio value="spot">{{ $t('trading-assistant.form.marketTypeSpot') }}</a-radio>
                      </a-radio-group>
                      <div class="form-item-hint">
                        {{ $t('trading-assistant.form.marketTypeHint') }}
                      </div>
                    </a-form-item>
                  </a-col>
                </a-row>

                <a-row :gutter="16">
                  <a-col :xs="24" :sm="24" :md="12" :lg="12">
                    <a-form-item :label="`${$t('trading-assistant.form.leverage')} (x)`">
                      <a-input-number
                        v-decorator="['leverage', { initialValue: 1, rules: [{ required: true, message: $t('trading-assistant.validation.leverageRequired') }] }]"
                        :min="1"
                        :max="form.getFieldValue('market_type') === 'spot' ? 1 : 125"
                        :step="1"
                        style="width: 100%"
                        :disabled="form.getFieldValue('market_type') === 'spot'" />
                      <div class="form-item-hint">
                        <span v-if="form.getFieldValue('market_type') === 'spot'">
                          {{ $t('trading-assistant.form.spotLeverageFixed') }}
                        </span>
                        <span v-else>
                          {{ $t('trading-assistant.form.leverageHint') }}
                        </span>
                      </div>
                    </a-form-item>
                  </a-col>
                  <a-col :xs="24" :sm="24" :md="12" :lg="12">
                    <a-form-item :label="$t('trading-assistant.form.tradeDirection')">
                      <a-radio-group
                        v-decorator="['trade_direction', { initialValue: 'long' }]"
                        :disabled="form.getFieldValue('market_type') === 'spot'">
                        <a-radio value="long">{{ $t('trading-assistant.form.tradeDirectionLong') }}</a-radio>
                        <a-radio value="short" :disabled="form.getFieldValue('market_type') === 'spot'">
                          {{ $t('trading-assistant.form.tradeDirectionShort') }}
                        </a-radio>
                        <a-radio value="both" :disabled="form.getFieldValue('market_type') === 'spot'">
                          {{ $t('trading-assistant.form.tradeDirectionBoth') }}
                        </a-radio>
                      </a-radio-group>
                      <div
                        v-if="form.getFieldValue('market_type') === 'spot'"
                        class="form-item-hint"
                        style="color: #ff9800;">
                        {{ $t('trading-assistant.form.spotOnlyLongHint') }}
                      </div>
                    </a-form-item>
                  </a-col>
                </a-row>

                <a-row :gutter="16">
                  <a-col :xs="24" :sm="24" :md="12" :lg="12">
                    <a-form-item :label="$t('trading-assistant.form.klinePeriod')">
                      <a-select
                        v-decorator="['timeframe', { initialValue: '1H', rules: [{ required: true }] }]"
                        :placeholder="$t('trading-assistant.placeholders.selectKlinePeriod')"
                        :getPopupContainer="(triggerNode) => triggerNode.parentNode">
                        <a-select-option value="1m">{{ $t('trading-assistant.form.timeframe1m') }}</a-select-option>
                        <a-select-option value="5m">{{ $t('trading-assistant.form.timeframe5m') }}</a-select-option>
                        <a-select-option value="15m">{{ $t('trading-assistant.form.timeframe15m') }}</a-select-option>
                        <a-select-option value="30m">{{ $t('trading-assistant.form.timeframe30m') }}</a-select-option>
                        <a-select-option value="1H">{{ $t('trading-assistant.form.timeframe1H') }}</a-select-option>
                        <a-select-option value="4H">{{ $t('trading-assistant.form.timeframe4H') }}</a-select-option>
                        <a-select-option value="1D">{{ $t('trading-assistant.form.timeframe1D') }}</a-select-option>
                      </a-select>
                    </a-form-item>
                  </a-col>
                  <a-col :xs="24" :sm="24" :md="12" :lg="12"></a-col>
                </a-row>
              </a-form>
            </div>

            <!-- Local mode: indicator strategy only (no AI strategy) -->
          </div>

          <!-- Step 2: params (backtest-like / trading params) -->
          <div v-show="currentStep === 1" class="step-content">
            <!-- 指标策略：策略参数 -->
            <div v-if="strategyType === 'indicator'">
              <a-form :form="form" layout="vertical">
                <!-- Backtest-like configuration (aligned with indicator-analysis BacktestModal) -->
                <a-collapse v-model="backtestCollapseKeys" :bordered="false" style="background: #fafafa;">
                  <a-collapse-panel key="risk" :header="$t('dashboard.indicator.backtest.panel.risk')">
                    <a-row :gutter="24">
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.stopLossPct')">
                          <a-input-number
                            v-decorator="['stop_loss_pct', { initialValue: 0 }]"
                            :min="0"
                            :max="100"
                            :step="0.01"
                            :precision="4"
                            style="width: 220px" />
                        </a-form-item>
                      </a-col>
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.takeProfitPct')">
                          <a-input-number
                            v-decorator="['take_profit_pct', { initialValue: 0 }]"
                            :min="0"
                            :max="1000"
                            :step="0.01"
                            :precision="4"
                            style="width: 220px" />
                        </a-form-item>
                      </a-col>
                    </a-row>

                    <a-row :gutter="24">
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.trailingEnabled')">
                          <a-switch
                            v-decorator="['trailing_enabled', { valuePropName: 'checked', initialValue: false }]"
                            @change="onTrailingToggle" />
                        </a-form-item>
                      </a-col>
                      <a-col :span="12"></a-col>
                    </a-row>

                    <template v-if="trailingEnabledUi">
                      <a-row :gutter="24">
                        <a-col :span="12">
                          <a-form-item :label="$t('dashboard.indicator.backtest.field.trailingStopPct')">
                            <a-input-number
                              v-decorator="['trailing_stop_pct', { initialValue: 0 }]"
                              :min="0"
                              :max="100"
                              :step="0.01"
                              :precision="4"
                              style="width: 220px" />
                          </a-form-item>
                        </a-col>
                        <a-col :span="12">
                          <a-form-item :label="$t('dashboard.indicator.backtest.field.trailingActivationPct')">
                            <a-input-number
                              v-decorator="['trailing_activation_pct', { initialValue: 0 }]"
                              :min="0"
                              :max="1000"
                              :step="0.01"
                              :precision="4"
                              style="width: 220px" />
                          </a-form-item>
                        </a-col>
                      </a-row>
                    </template>
                  </a-collapse-panel>

                  <a-collapse-panel key="scale" :header="$t('dashboard.indicator.backtest.panel.scale')">
                    <a-row :gutter="24">
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.trendAddEnabled')">
                          <a-switch
                            v-decorator="['trend_add_enabled', { valuePropName: 'checked', initialValue: false }]"
                            @change="onTrendAddToggle" />
                        </a-form-item>
                      </a-col>
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.dcaAddEnabled')">
                          <a-switch
                            v-decorator="['dca_add_enabled', { valuePropName: 'checked', initialValue: false }]"
                            @change="onDcaAddToggle" />
                        </a-form-item>
                      </a-col>
                    </a-row>
                    <a-row :gutter="24">
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.trendAddStepPct')">
                          <a-input-number
                            v-decorator="['trend_add_step_pct', { initialValue: 0 }]"
                            :min="0"
                            :max="1000"
                            :step="0.01"
                            :precision="4"
                            style="width: 220px"
                            @change="onScaleParamsChange" />
                        </a-form-item>
                      </a-col>
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.dcaAddStepPct')">
                          <a-input-number
                            v-decorator="['dca_add_step_pct', { initialValue: 0 }]"
                            :min="0"
                            :max="1000"
                            :step="0.01"
                            :precision="4"
                            style="width: 220px"
                            @change="onScaleParamsChange" />
                        </a-form-item>
                      </a-col>
                    </a-row>
                    <a-row :gutter="24">
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.trendAddSizePct')">
                          <a-input-number
                            v-decorator="['trend_add_size_pct', { initialValue: 0 }]"
                            :min="0"
                            :max="100"
                            :step="0.1"
                            :precision="4"
                            style="width: 220px"
                            @change="onScaleParamsChange" />
                        </a-form-item>
                      </a-col>
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.dcaAddSizePct')">
                          <a-input-number
                            v-decorator="['dca_add_size_pct', { initialValue: 0 }]"
                            :min="0"
                            :max="100"
                            :step="0.1"
                            :precision="4"
                            style="width: 220px"
                            @change="onScaleParamsChange" />
                        </a-form-item>
                      </a-col>
                    </a-row>
                    <a-row :gutter="24">
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.trendAddMaxTimes')">
                          <a-input-number
                            v-decorator="['trend_add_max_times', { initialValue: 0 }]"
                            :min="0"
                            :max="50"
                            :step="1"
                            :precision="0"
                            style="width: 220px"
                            @change="onScaleParamsChange" />
                        </a-form-item>
                      </a-col>
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.dcaAddMaxTimes')">
                          <a-input-number
                            v-decorator="['dca_add_max_times', { initialValue: 0 }]"
                            :min="0"
                            :max="50"
                            :step="1"
                            :precision="0"
                            style="width: 220px"
                            @change="onScaleParamsChange" />
                        </a-form-item>
                      </a-col>
                    </a-row>
                  </a-collapse-panel>

                  <a-collapse-panel key="reduce" :header="$t('dashboard.indicator.backtest.panel.reduce')">
                    <a-row :gutter="24">
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.trendReduceEnabled')">
                          <a-switch
                            v-decorator="['trend_reduce_enabled', { valuePropName: 'checked', initialValue: false }]" />
                        </a-form-item>
                      </a-col>
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.adverseReduceEnabled')">
                          <a-switch
                            v-decorator="['adverse_reduce_enabled', { valuePropName: 'checked', initialValue: false }]" />
                        </a-form-item>
                      </a-col>
                    </a-row>
                    <a-row :gutter="24">
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.trendReduceStepPct')">
                          <a-input-number
                            v-decorator="['trend_reduce_step_pct', { initialValue: 0 }]"
                            :min="0"
                            :max="1000"
                            :step="0.01"
                            :precision="4"
                            style="width: 220px" />
                        </a-form-item>
                      </a-col>
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.adverseReduceStepPct')">
                          <a-input-number
                            v-decorator="['adverse_reduce_step_pct', { initialValue: 0 }]"
                            :min="0"
                            :max="1000"
                            :step="0.01"
                            :precision="4"
                            style="width: 220px" />
                        </a-form-item>
                      </a-col>
                    </a-row>
                    <a-row :gutter="24">
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.trendReduceSizePct')">
                          <a-input-number
                            v-decorator="['trend_reduce_size_pct', { initialValue: 0 }]"
                            :min="0"
                            :max="100"
                            :step="0.1"
                            :precision="4"
                            style="width: 220px" />
                        </a-form-item>
                      </a-col>
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.adverseReduceSizePct')">
                          <a-input-number
                            v-decorator="['adverse_reduce_size_pct', { initialValue: 0 }]"
                            :min="0"
                            :max="100"
                            :step="0.1"
                            :precision="4"
                            style="width: 220px" />
                        </a-form-item>
                      </a-col>
                    </a-row>
                    <a-row :gutter="24">
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.trendReduceMaxTimes')">
                          <a-input-number
                            v-decorator="['trend_reduce_max_times', { initialValue: 0 }]"
                            :min="0"
                            :max="50"
                            :step="1"
                            :precision="0"
                            style="width: 100%" />
                        </a-form-item>
                      </a-col>
                      <a-col :span="12">
                        <a-form-item :label="$t('dashboard.indicator.backtest.field.adverseReduceMaxTimes')">
                          <a-input-number
                            v-decorator="['adverse_reduce_max_times', { initialValue: 0 }]"
                            :min="0"
                            :max="50"
                            :step="1"
                            :precision="0"
                            style="width: 100%" />
                        </a-form-item>
                      </a-col>
                    </a-row>
                  </a-collapse-panel>

                  <a-collapse-panel key="position" :header="$t('dashboard.indicator.backtest.panel.position')">
                    <a-row :gutter="24">
                      <a-col :span="12">
                        <a-form-item
                          :label="$t('dashboard.indicator.backtest.field.entryPct')"
                          :help="$t('dashboard.indicator.backtest.hint.entryPctMax', { maxPct: Number(entryPctMaxUi || 0).toFixed(0) })">
                          <a-input-number
                            v-decorator="['entry_pct', { initialValue: 100 }]"
                            :min="0"
                            :max="entryPctMaxUi"
                            :step="0.1"
                            :precision="4"
                            style="width: 220px"
                            @change="onEntryPctChange" />
                        </a-form-item>
                      </a-col>
                      <a-col :span="12"></a-col>
                    </a-row>
                  </a-collapse-panel>
                </a-collapse>

                <!-- Indicator strategy: AI decision filter -->
                <div class="ai-filter-box">
                  <div class="ai-filter-header">
                    <div class="ai-filter-title">
                      <a-icon type="robot" />
                      <span>{{ $t('trading-assistant.form.enableAiFilter') }}</span>
                    </div>
                    <a-switch :checked="aiFilterEnabledUi" @change="onAiFilterToggle" />
                  </div>
                  <div class="ai-filter-hint">{{ $t('trading-assistant.form.enableAiFilterHint') }}</div>
                </div>
              </a-form>
            </div>

            <!-- Local mode: indicator strategy only (no AI strategy) -->
          </div>

          <!-- Step 3: signal push & optional live trading (crypto only) -->
          <div v-show="currentStep === 2" class="step-content">
            <a-form :form="form" layout="vertical" autocomplete="off">
              <a-form-item :label="$t('trading-assistant.form.executionMode')">
                <a-radio-group
                  v-decorator="['execution_mode', { initialValue: 'signal' }]"
                  :disabled="!canUseLiveTrading"
                  @change="onExecutionModeChange">
                  <a-radio value="signal">{{ $t('trading-assistant.form.executionModeSignal') }}</a-radio>
                  <a-radio value="live" :disabled="!canUseLiveTrading">{{ $t('trading-assistant.form.executionModeLive')
                  }}</a-radio>
                </a-radio-group>
                <div v-if="!canUseLiveTrading" class="form-item-hint" style="color: #ff9800;">
                  {{ $t('trading-assistant.form.liveTradingNotSupportedHint') }}
                </div>
              </a-form-item>

              <a-form-item :label="$t('trading-assistant.form.notifyChannels')">
                <a-checkbox-group
                  v-decorator="['notify_channels', { initialValue: ['browser'] }]"
                  @change="onNotifyChannelsChange">
                  <a-checkbox value="browser">{{ $t('trading-assistant.notify.browser') }}</a-checkbox>
                  <a-checkbox value="email">{{ $t('trading-assistant.notify.email') }}</a-checkbox>
                  <a-checkbox value="telegram">{{ $t('trading-assistant.notify.telegram') }}</a-checkbox>
                  <a-checkbox value="discord">{{ $t('trading-assistant.notify.discord') }}</a-checkbox>
                  <a-checkbox value="webhook">{{ $t('trading-assistant.notify.webhook') }}</a-checkbox>
                  <a-checkbox value="phone">{{ $t('trading-assistant.notify.phone') }}</a-checkbox>
                </a-checkbox-group>
                <div class="form-item-hint">{{ $t('trading-assistant.form.notifyChannelsHint') }}</div>
              </a-form-item>

              <!-- Notification settings hint -->
              <a-alert
                v-if="unconfiguredChannels.length > 0"
                type="warning"
                showIcon
                style="margin-bottom: 16px">
                <template #message>
                  <span>
                    {{ $t('trading-assistant.form.notificationConfigMissing', { channels: unconfiguredChannels.join(', ') }) }}
                    <router-link to="/profile" style="margin-left: 8px">
                      <a-icon type="setting" /> {{ $t('trading-assistant.form.goToProfile') }}
                    </router-link>
                  </span>
                </template>
              </a-alert>

              <a-alert
                v-else-if="notifyChannelsUi.length > 0 && !notifyChannelsUi.includes('browser') || (notifyChannelsUi.length > 1)"
                type="info"
                showIcon
                style="margin-bottom: 16px">
                <template #message>
                  <span>
                    {{ $t('trading-assistant.form.notificationFromProfile') }}
                    <router-link to="/profile" style="margin-left: 8px">
                      <a-icon type="setting" /> {{ $t('trading-assistant.form.goToProfile') }}
                    </router-link>
                  </span>
                </template>
              </a-alert>

              <a-divider v-if="executionModeUi === 'live' && canUseLiveTrading" />

              <!-- Live trading: exchange credentials -->
              <div v-if="executionModeUi === 'live' && canUseLiveTrading">
                <a-alert
                  type="info"
                  show-icon
                  style="margin-bottom: 12px;"
                  :message="$t('trading-assistant.form.liveTradingConfigTitle')"
                  :description="$t('trading-assistant.form.liveTradingConfigHint')" />

                <!-- ========== Broker Configuration (US/HK Stocks) ========== -->
                <template v-if="isIBKRMarket">
                  <a-form-item :label="$t('trading-assistant.form.broker')">
                    <a-select
                      v-decorator="['broker_id', {
                        initialValue: 'ibkr',
                        rules: [{ required: true, message: $t('trading-assistant.validation.brokerRequired') }]
                      }]"
                      :placeholder="$t('trading-assistant.placeholders.selectBroker')"
                      :getPopupContainer="getModalPopupContainer"
                      @change="handleBrokerSelectChange">
                      <a-select-option v-for="broker in brokerOptions" :key="broker.value" :value="broker.value">
                        {{ broker.displayName }}
                      </a-select-option>
                    </a-select>
                  </a-form-item>

                  <!-- IBKR specific configuration -->
                  <template v-if="currentBrokerId === 'ibkr'">
                    <a-alert
                      type="warning"
                      show-icon
                      style="margin-bottom: 16px;"
                      :message="$t('trading-assistant.form.localDeploymentRequired')"
                      :description="$t('trading-assistant.form.localDeploymentHint')" />
                    <a-alert
                      type="info"
                      show-icon
                      style="margin-bottom: 16px;"
                      :message="$t('trading-assistant.form.ibkrConnectionTitle')"
                      :description="$t('trading-assistant.form.ibkrConnectionHint')" />

                    <a-form-item :label="$t('trading-assistant.form.ibkrHost')">
                      <a-input
                        v-decorator="['ibkr_host', { initialValue: '127.0.0.1' }]"
                        placeholder="127.0.0.1"
                        @change="handleApiConfigChange" />
                    </a-form-item>

                    <a-form-item :label="$t('trading-assistant.form.ibkrPort')">
                      <a-input-number
                        v-decorator="['ibkr_port', { initialValue: 7497 }]"
                        placeholder="7497"
                        :min="1"
                        :max="65535"
                        style="width: 100%"
                        @change="handleApiConfigChange" />
                      <div class="form-item-hint">{{ $t('trading-assistant.form.ibkrPortHint') }}</div>
                    </a-form-item>

                    <a-form-item :label="$t('trading-assistant.form.ibkrClientId')">
                      <a-input-number
                        v-decorator="['ibkr_client_id', { initialValue: 1 }]"
                        placeholder="1"
                        :min="1"
                        :max="999"
                        style="width: 100%"
                        @change="handleApiConfigChange" />
                    </a-form-item>

                    <a-form-item :label="$t('trading-assistant.form.ibkrAccount')">
                      <a-input
                        v-decorator="['ibkr_account', { initialValue: '' }]"
                        :placeholder="$t('trading-assistant.placeholders.ibkrAccount')"
                        @change="handleApiConfigChange" />
                      <div class="form-item-hint">{{ $t('trading-assistant.form.ibkrAccountHint') }}</div>
                    </a-form-item>
                  </template>

                  <!-- Future broker configurations can be added here -->
                  <!-- <template v-else-if="currentBrokerId === 'futu'">...</template> -->
                </template>

                <!-- ========== MT5/Forex Broker Configuration ========== -->
                <template v-else-if="isMT5Market">
                  <a-form-item :label="$t('trading-assistant.form.forexBroker')">
                    <a-select
                      v-decorator="['forex_broker_id', {
                        initialValue: 'mt5',
                        rules: [{ required: true, message: $t('trading-assistant.validation.brokerRequired') }]
                      }]"
                      :placeholder="$t('trading-assistant.placeholders.selectBroker')"
                      :getPopupContainer="getModalPopupContainer"
                      @change="handleForexBrokerSelectChange">
                      <a-select-option v-for="broker in forexBrokerOptions" :key="broker.value" :value="broker.value">
                        {{ broker.displayName }}
                      </a-select-option>
                    </a-select>
                  </a-form-item>

                  <!-- MT5 specific configuration -->
                  <template v-if="currentBrokerId === 'mt5'">
                    <a-alert
                      type="warning"
                      show-icon
                      style="margin-bottom: 16px;"
                      :message="$t('trading-assistant.form.localDeploymentRequired')"
                      :description="$t('trading-assistant.form.localDeploymentHint')" />
                    <a-alert
                      type="info"
                      show-icon
                      style="margin-bottom: 16px;"
                      :message="$t('trading-assistant.form.mt5ConnectionTitle')"
                      :description="$t('trading-assistant.form.mt5ConnectionHint')" />

                    <a-form-item :label="$t('trading-assistant.form.mt5Server')">
                      <a-input
                        v-decorator="['mt5_server', {
                          rules: [{ required: true, message: $t('trading-assistant.validation.mt5ServerRequired') }]
                        }]"
                        :placeholder="$t('trading-assistant.placeholders.mt5Server')"
                        @change="handleApiConfigChange" />
                      <div class="form-item-hint">{{ $t('trading-assistant.form.mt5ServerHint') }}</div>
                    </a-form-item>

                    <a-form-item :label="$t('trading-assistant.form.mt5Login')">
                      <a-input-number
                        v-decorator="['mt5_login', {
                          rules: [{ required: true, message: $t('trading-assistant.validation.mt5LoginRequired') }]
                        }]"
                        :placeholder="$t('trading-assistant.placeholders.mt5Login')"
                        :min="1"
                        style="width: 100%"
                        @change="handleApiConfigChange" />
                    </a-form-item>

                    <a-form-item :label="$t('trading-assistant.form.mt5Password')">
                      <a-input-password
                        v-decorator="['mt5_password', {
                          rules: [{ required: true, message: $t('trading-assistant.validation.mt5PasswordRequired') }]
                        }]"
                        :placeholder="$t('trading-assistant.placeholders.mt5Password')"
                        @change="handleApiConfigChange" />
                    </a-form-item>

                    <a-form-item :label="$t('trading-assistant.form.mt5TerminalPath')">
                      <a-input
                        v-decorator="['mt5_terminal_path']"
                        :placeholder="$t('trading-assistant.placeholders.mt5TerminalPath')"
                        @change="handleApiConfigChange" />
                      <div class="form-item-hint">{{ $t('trading-assistant.form.mt5TerminalPathHint') }}</div>
                    </a-form-item>
                  </template>

                  <!-- Future forex broker configurations can be added here -->
                  <!-- <template v-else-if="currentBrokerId === 'mt4'">...</template> -->
                </template>

                <!-- ========== Crypto Exchange Configuration ========== -->
                <template v-else>
                  <a-form-item :label="$t('trading-assistant.form.savedCredential')">
                    <a-select
                      v-decorator="['credential_id', { getValueFromEvent: (val) => val || undefined }]"
                      :placeholder="$t('trading-assistant.placeholders.selectSavedCredential')"
                      allow-clear
                      show-search
                      option-filter-prop="children"
                      :loading="loadingExchangeCredentials"
                      @change="handleCredentialSelectChange">
                      <a-select-option v-for="cred in exchangeCredentials" :key="cred.id" :value="cred.id">
                        {{ formatCredentialLabel(cred) }}
                      </a-select-option>
                    </a-select>
                    <div class="form-item-hint">{{ $t('trading-assistant.form.savedCredentialHint') }}</div>
                  </a-form-item>

                  <a-form-item :label="$t('trading-assistant.form.exchange')">
                    <a-select
                      v-decorator="['exchange_id', {
                        rules: [{ required: true, message: $t('trading-assistant.validation.exchangeRequired') }],
                        getValueFromEvent: (val) => val || undefined
                      }]"
                      :placeholder="$t('trading-assistant.placeholders.selectExchange')"
                      allow-clear
                      show-search
                      option-filter-prop="children"
                      @change="handleExchangeSelectChange">
                      <a-select-option
                        v-for="exchange in cryptoExchangeOptions"
                        :key="exchange.value"
                        :value="exchange.value">
                        {{ exchange.displayName }}
                      </a-select-option>
                    </a-select>
                  </a-form-item>

                  <a-form-item :label="$t('trading-assistant.form.apiKey')">
                    <a-input-password
                      v-decorator="['api_key', { rules: [{ required: true, message: $t('trading-assistant.validation.apiKeyRequired') }] }]"
                      :placeholder="$t('trading-assistant.placeholders.inputApiKey')"
                      autocomplete="new-password"
                      @change="handleApiConfigChange" />
                  </a-form-item>

                  <a-form-item :label="$t('trading-assistant.form.secretKey')">
                    <a-input-password
                      v-decorator="['secret_key', { rules: [{ required: true, message: $t('trading-assistant.validation.secretKeyRequired') }] }]"
                      :placeholder="$t('trading-assistant.placeholders.inputSecretKey')"
                      autocomplete="new-password"
                      @change="handleApiConfigChange" />
                  </a-form-item>

                  <a-form-item v-if="needsPassphrase" :label="$t('trading-assistant.form.passphrase')">
                    <a-input-password
                      v-decorator="['passphrase', { rules: [{ required: true, message: $t('trading-assistant.validation.passphraseRequired') }] }]"
                      :placeholder="$t('trading-assistant.placeholders.inputPassphrase')"
                      autocomplete="new-password"
                      @change="handleApiConfigChange" />
                  </a-form-item>

                  <a-form-item
                    v-if="showDemoTradingSwitch"
                    :label="`${getExchangeDisplayName(currentExchangeId)} Demo Trading`"
                    key="demo-trading-switch">
                    <a-switch v-decorator="['enable_demo_trading', { valuePropName: 'checked', initialValue: false }]">
                      <a-icon slot="checkedChildren" type="check" />
                      <a-icon slot="unCheckedChildren" type="close" />
                    </a-switch>
                  </a-form-item>

                  <a-form-item>
                    <a-checkbox
                      v-decorator="['save_credential', { valuePropName: 'checked', initialValue: false }]"
                      @change="onSaveCredentialChange">
                      {{ $t('trading-assistant.form.saveCredential') }}
                    </a-checkbox>
                  </a-form-item>

                  <a-form-item v-if="saveCredentialUi" :label="$t('trading-assistant.form.credentialName')">
                    <a-input
                      v-decorator="['credential_name']"
                      :placeholder="$t('trading-assistant.placeholders.inputCredentialName')" />
                  </a-form-item>
                </template>

                <!-- Test Connection Button (shared by both IBKR and Crypto) -->
                <a-form-item>
                  <a-button type="default" :loading="testing" @click="handleTestConnection" block>
                    <a-icon type="wallet" />
                    {{ $t('trading-assistant.form.testConnection') }}
                  </a-button>
                  <div v-if="testResult" class="test-result" :class="testResult.success ? 'success' : 'error'">
                    {{ testResult.message }}
                  </div>
                </a-form-item>
              </div>
            </a-form>
          </div>
        </div>
      </a-spin>

      <template slot="footer">
        <a-button @click="handleCloseModal">{{ $t('trading-assistant.form.cancel') }}</a-button>
        <a-button v-show="currentStep > 0" @click="handlePrev">
          {{ $t('trading-assistant.form.prev') }}
        </a-button>
        <a-button v-show="currentStep < 2" type="primary" @click="handleNext" :loading="saving">
          {{ $t('trading-assistant.form.next') }}
        </a-button>
        <a-button v-show="currentStep === 2" type="primary" @click="handleSubmit" :loading="saving">
          {{ editingStrategy ? $t('trading-assistant.form.confirmEdit') : $t('trading-assistant.form.confirmCreate') }}
        </a-button>
      </template>
    </a-modal>

    <!-- 添加交易对弹窗 -->
    <a-modal
      :title="$t('trading-assistant.form.addSymbolTitle')"
      :visible="showAddSymbolModal"
      @ok="handleConfirmAddSymbol"
      @cancel="handleCloseAddSymbolModal"
      :confirmLoading="addingSymbol"
      width="600px"
      :okText="$t('trading-assistant.form.confirmAdd')"
      :cancelText="$t('trading-assistant.form.cancel')"
      :maskClosable="false"
      :keyboard="false">
      <div class="add-symbol-modal-content">
        <!-- 市场类型Tab -->
        <a-tabs v-model="addSymbolMarket" @change="handleAddSymbolMarketChange" class="market-tabs">
          <a-tab-pane
            v-for="marketType in addSymbolMarketTypes"
            :key="marketType.value"
            :tab="$t(marketType.i18nKey || `dashboard.analysis.market.${marketType.value}`)">
          </a-tab-pane>
        </a-tabs>

        <!-- 搜索输入框 -->
        <div class="symbol-search-section">
          <a-input-search
            v-model="addSymbolKeyword"
            :placeholder="$t('dashboard.analysis.modal.addStock.searchOrInputPlaceholder')"
            @search="handleSearchSymbol"
            @change="handleSymbolSearchInputChange"
            :loading="searchingSymbol"
            size="large"
            allow-clear>
            <a-button slot="enterButton" type="primary" icon="search">
              {{ $t('dashboard.analysis.modal.addStock.search') }}
            </a-button>
          </a-input-search>
        </div>

        <!-- 搜索结果 -->
        <div v-if="symbolSearchResults.length > 0" class="search-results-section">
          <div class="section-title">
            <a-icon type="search" style="margin-right: 4px;" />
            {{ $t('dashboard.analysis.modal.addStock.searchResults') }}
          </div>
          <a-list
            :data-source="symbolSearchResults"
            :loading="searchingSymbol"
            size="small"
            class="symbol-list">
            <a-list-item slot="renderItem" slot-scope="item" class="symbol-list-item" @click="handleSelectAddSymbol(item)">
              <a-list-item-meta>
                <template slot="title">
                  <div class="symbol-item-content">
                    <span class="symbol-code">{{ item.symbol }}</span>
                    <span class="symbol-name">{{ item.name }}</span>
                    <a-tag v-if="item.exchange" size="small" color="blue" style="margin-left: 8px;">
                      {{ item.exchange }}
                    </a-tag>
                  </div>
                </template>
              </a-list-item-meta>
            </a-list-item>
          </a-list>
        </div>

        <!-- 热门标的 -->
        <div class="hot-symbols-section">
          <div class="section-title">
            <a-icon type="fire" style="color: #ff4d4f; margin-right: 4px;" />
            {{ $t('dashboard.analysis.modal.addStock.hotSymbols') }}
          </div>
          <a-spin :spinning="loadingHotSymbols">
            <a-list
              v-if="hotSymbols.length > 0"
              :data-source="hotSymbols"
              size="small"
              class="symbol-list">
              <a-list-item slot="renderItem" slot-scope="item" class="symbol-list-item" @click="handleSelectAddSymbol(item)">
                <a-list-item-meta>
                  <template slot="title">
                    <div class="symbol-item-content">
                      <span class="symbol-code">{{ item.symbol }}</span>
                      <span class="symbol-name">{{ item.name }}</span>
                      <a-tag v-if="item.exchange" size="small" color="orange" style="margin-left: 8px;">
                        {{ item.exchange }}
                      </a-tag>
                    </div>
                  </template>
                </a-list-item-meta>
              </a-list-item>
            </a-list>
            <a-empty v-else :description="$t('dashboard.analysis.modal.addStock.noHotSymbols')" :image="false" />
          </a-spin>
        </div>

        <!-- 选中的标的显示 -->
        <div v-if="selectedAddSymbol" class="selected-symbol-section">
          <div class="section-title">
            <a-icon type="check-circle" style="color: #52c41a; margin-right: 4px;" />
            {{ $t('dashboard.analysis.modal.addStock.selectedSymbol') }}
          </div>
          <div class="selected-symbol-info">
            <a-tag :color="getMarketColor(addSymbolMarket)" style="margin-right: 8px;">{{ addSymbolMarket }}</a-tag>
            <span class="symbol-code">{{ selectedAddSymbol.symbol }}</span>
            <span v-if="selectedAddSymbol.name" class="symbol-name">{{ selectedAddSymbol.name }}</span>
          </div>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script>
import { getStrategyList, startStrategy, stopStrategy, deleteStrategy, updateStrategy, testExchangeConnection, getStrategyEquityCurve, batchCreateStrategies, batchStartStrategies, batchStopStrategies, batchDeleteStrategies } from '@/api/strategy'
import { getWatchlist, addWatchlist, searchSymbols, getHotSymbols } from '@/api/market'
import { listExchangeCredentials, getExchangeCredential, createExchangeCredential } from '@/api/credentials'
import { getNotificationSettings } from '@/api/user'
import { baseMixin } from '@/store/app-mixin'
import request from '@/utils/request'
import TradingRecords from './components/TradingRecords.vue'
import PositionRecords from './components/PositionRecords.vue'

// 常见加密货币交易对
const CRYPTO_SYMBOLS = [
  'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'ADA/USDT',
  'XRP/USDT', 'DOGE/USDT', 'DOT/USDT', 'MATIC/USDT', 'AVAX/USDT',
  'LINK/USDT', 'UNI/USDT', 'LTC/USDT', 'ATOM/USDT', 'ETC/USDT'
]

// Crypto exchange options
const EXCHANGE_OPTIONS = [
  { value: 'binance', labelKey: 'binance' },
  { value: 'okx', labelKey: 'okx' },
  { value: 'bitget', labelKey: 'bitget' },
  { value: 'bybit', labelKey: 'bybit' },
  { value: 'coinbaseexchange', labelKey: 'coinbaseexchange' },
  { value: 'kraken', labelKey: 'kraken' },
  { value: 'kucoin', labelKey: 'kucoin' },
  { value: 'gate', labelKey: 'gate' },
  { value: 'bitfinex', labelKey: 'bitfinex' },
  { value: 'deepcoin', labelKey: 'deepcoin' }
]

// Traditional broker options (US/HK stocks) - extensible for future brokers
const BROKER_OPTIONS = [
  { value: 'ibkr', labelKey: 'ibkr', name: 'Interactive Brokers' }
  // Future brokers can be added here:
  // { value: 'td', labelKey: 'td', name: 'TD Ameritrade' },
  // { value: 'schwab', labelKey: 'schwab', name: 'Charles Schwab' },
  // { value: 'futu', labelKey: 'futu', name: 'Futu (富途)' },
  // { value: 'tiger', labelKey: 'tiger', name: 'Tiger Brokers (老虎证券)' },
]

// Forex broker options
const FOREX_BROKER_OPTIONS = [
  { value: 'mt5', labelKey: 'mt5', name: 'MetaTrader 5' }
  // Future forex brokers can be added here:
  // { value: 'mt4', labelKey: 'mt4', name: 'MetaTrader 4' },
  // { value: 'ctrader', labelKey: 'ctrader', name: 'cTrader' },
]

export default {
  name: 'TradingAssistant',
  mixins: [baseMixin],
  components: {
    TradingRecords,
    PositionRecords
  },
  computed: {
    isDarkTheme () {
      return this.navTheme === 'dark' || this.navTheme === 'realdark'
    },
    needsPassphrase () {
      // Exchanges that require passphrase
      return ['okx', 'okex', 'coinbaseexchange', 'kucoin', 'bitget', 'deepcoin'].includes(this.currentExchangeId)
    },
    // Check if current market uses IBKR (US Stock / HK Stock)
    isIBKRMarket () {
      return ['USStock', 'HShare'].includes(this.selectedMarketCategory)
    },
    // Check if current market uses MT5 (Forex)
    isMT5Market () {
      return this.selectedMarketCategory === 'Forex'
    },
    // Check if current market uses any broker (not crypto exchange)
    isBrokerMarket () {
      return this.isIBKRMarket || this.isMT5Market
    },
    // 预处理交易所列表，包含显示名称，提升性能
    formattedExchangeOptions () {
      return EXCHANGE_OPTIONS.map(exchange => {
        let label = ''
        try {
          if (exchange.labelKey) {
            const translationKey = `trading-assistant.exchangeNames.${exchange.labelKey}`
            const translated = this.$t(translationKey)
            if (translated !== translationKey) {
              label = translated
            }
          }
        } catch (e) {
          // 忽略翻译错误
        }

        if (!label) {
          label = exchange.value.charAt(0).toUpperCase() + exchange.value.slice(1)
        }
        return {
          ...exchange,
          displayName: label
        }
      })
    },
    totalPnl () {
      if (this.currentEquity === null || !this.selectedStrategy || !this.selectedStrategy.initial_capital) {
        return null
      }
      return this.currentEquity - (this.selectedStrategy.initial_capital || 0)
    },
    totalPnlPercent () {
      if (this.totalPnl === null || !this.selectedStrategy || !this.selectedStrategy.initial_capital) {
        return null
      }
      if (this.selectedStrategy.initial_capital === 0) return 0
      return (this.totalPnl / this.selectedStrategy.initial_capital) * 100
    },
    getEquityColorClass () {
      if (this.totalPnl === null) return ''
      return this.totalPnl >= 0 ? 'text-success' : 'text-danger'
    },
    getPnlColorClass () {
      if (this.totalPnl === null) return ''
      return this.totalPnl >= 0 ? 'text-success' : 'text-danger'
    },
    isCryptoMarket () {
      // IMPORTANT: do not rely on form.getFieldValue for reactivity (Ant Form is not reactive).
      // Always depend on selectedMarketCategory to make UI reactive.
      const cat = this.selectedMarketCategory || 'Crypto'
      return String(cat).toLowerCase() === 'crypto'
    },
    // Check if selected market supports live trading (Crypto, USStock/HShare with IBKR, or Forex with MT5)
    canUseLiveTrading () {
      const cat = this.selectedMarketCategory || 'Crypto'
      // Crypto always supports live trading via crypto exchanges
      if (String(cat).toLowerCase() === 'crypto') {
        return true
      }
      // USStock/HShare can use IBKR for live trading
      if (['USStock', 'HShare'].includes(cat)) {
        return true
      }
      // Forex can use MT5 for live trading
      if (cat === 'Forex') {
        return true
      }
      return false
    },
    // Check if current market + exchange combination supports live trading
    isLiveTradingAvailable () {
      const cat = this.selectedMarketCategory || 'Crypto'
      const exchangeId = this.currentExchangeId || ''
      // Crypto markets use crypto exchanges
      if (String(cat).toLowerCase() === 'crypto') {
        return ['binance', 'okx', 'bitget', 'bybit', 'coinbaseexchange', 'kraken', 'kucoin', 'gate', 'bitfinex'].includes(exchangeId)
      }
      // USStock/HShare use IBKR
      if (['USStock', 'HShare'].includes(cat)) {
        return this.currentBrokerId === 'ibkr'
      }
      // Forex uses MT5
      if (cat === 'Forex') {
        return this.currentBrokerId === 'mt5'
      }
      return false
    },
    // 是否显示模拟交易开关
    showDemoTradingSwitch () {
      // 目前仅支持 Binance 的 Demo Trading
      return this.currentExchangeId && this.currentExchangeId.toLowerCase() === 'binance'
    },
    // Broker options for US/HK stocks (with i18n support)
    brokerOptions () {
      return BROKER_OPTIONS.map(broker => {
        let label = ''
        try {
          const translationKey = `trading-assistant.brokerNames.${broker.labelKey}`
          const translated = this.$t(translationKey)
          if (translated !== translationKey) {
            label = translated
          }
        } catch (e) { }
        if (!label) {
          label = broker.name || broker.value.toUpperCase()
        }
        return {
          ...broker,
          displayName: label
        }
      })
    },
    // Forex broker options (with i18n support)
    forexBrokerOptions () {
      return FOREX_BROKER_OPTIONS.map(broker => {
        let label = ''
        try {
          const translationKey = `trading-assistant.brokerNames.${broker.labelKey}`
          const translated = this.$t(translationKey)
          if (translated !== translationKey) {
            label = translated
          }
        } catch (e) { }
        if (!label) {
          label = broker.name || broker.value.toUpperCase()
        }
        return {
          ...broker,
          displayName: label
        }
      })
    },
    // Crypto exchange options only
    cryptoExchangeOptions () {
      return EXCHANGE_OPTIONS.map(exchange => {
        let label = ''
        try {
          if (exchange.labelKey) {
            const translationKey = `trading-assistant.exchangeNames.${exchange.labelKey}`
            const translated = this.$t(translationKey)
            if (translated !== translationKey) {
              label = translated
            }
          }
        } catch (e) { }
        if (!label) {
          label = exchange.value.charAt(0).toUpperCase() + exchange.value.slice(1)
        }
        return {
          ...exchange,
          displayName: label
        }
      })
    },
    // 策略分组显示
    groupedStrategies () {
      if (this.groupByMode === 'symbol') {
        return this.groupedBySymbol
      }
      return this.groupedByStrategy
    },
    // 按策略分组（原有逻辑）
    groupedByStrategy () {
      const groups = {}
      const ungrouped = []

      for (const s of this.strategies) {
        const groupId = s.strategy_group_id
        if (groupId && groupId.trim()) {
          if (!groups[groupId]) {
            groups[groupId] = {
              id: groupId,
              baseName: s.group_base_name || s.strategy_name.split('-')[0],
              strategies: [],
              // 统计信息
              runningCount: 0,
              stoppedCount: 0
            }
          }
          groups[groupId].strategies.push(s)
          if (s.status === 'running') {
            groups[groupId].runningCount++
          } else {
            groups[groupId].stoppedCount++
          }
        } else {
          ungrouped.push(s)
        }
      }

      // 转换为数组，按创建时间排序
      const groupList = Object.values(groups).sort((a, b) => {
        const aTime = Math.max(...a.strategies.map(s => s.created_at || 0))
        const bTime = Math.max(...b.strategies.map(s => s.created_at || 0))
        return bTime - aTime
      })

      return { groups: groupList, ungrouped }
    },
    // 按 Symbol 分组
    groupedBySymbol () {
      const groups = {}
      const ungrouped = []

      for (const s of this.strategies) {
        const tc = s.trading_config || {}
        const symbol = tc.symbol
        if (symbol && symbol.trim()) {
          if (!groups[symbol]) {
            groups[symbol] = {
              id: `symbol_${symbol}`,
              baseName: symbol,
              strategies: [],
              runningCount: 0,
              stoppedCount: 0
            }
          }
          // 添加策略详情信息
          const strategyInfo = {
            ...s,
            displayInfo: {
              strategyName: s.strategy_name || s.group_base_name || 'Unnamed',
              timeframe: tc.timeframe || '-',
              indicatorName: s.indicator_name || (s.indicator_config && s.indicator_config.name) || '-'
            }
          }
          groups[symbol].strategies.push(strategyInfo)
          if (s.status === 'running') {
            groups[symbol].runningCount++
          } else {
            groups[symbol].stoppedCount++
          }
        } else {
          ungrouped.push(s)
        }
      }

      // 转换为数组，按 symbol 名称排序
      const groupList = Object.values(groups).sort((a, b) => {
        return a.baseName.localeCompare(b.baseName)
      })

      return { groups: groupList, ungrouped }
    },
    // Check if selected channels are configured in user profile
    unconfiguredChannels () {
      const missing = []
      if (this.notifyChannelsUi.includes('telegram')) {
        // Check if telegram token or chat id is missing
        if (!this.userNotificationSettings.telegram_bot_token && !this.userNotificationSettings.telegram_chat_id) {
          missing.push('Telegram')
        }
      }
      if (this.notifyChannelsUi.includes('email')) {
        if (!this.userNotificationSettings.email) {
          missing.push('Email')
        }
      }
      if (this.notifyChannelsUi.includes('discord')) {
        if (!this.userNotificationSettings.discord_webhook) {
          missing.push('Discord')
        }
      }
      if (this.notifyChannelsUi.includes('webhook')) {
        if (!this.userNotificationSettings.webhook_url) {
          missing.push('Webhook')
        }
      }
      // Phone/SMS check if needed
      // if (this.notifyChannelsUi.includes('phone') && !this.userNotificationSettings.phone) { ... }

      return missing
    }
  },
  data () {
    return {
      loading: false,
      loadingRecords: false,
      strategies: [],
      selectedStrategy: null,
      showFormModal: false,
      // Only indicator strategy in local mode
      strategyType: 'indicator',
      selectedMarketCategory: 'Crypto', // AShare / USStock / Crypto / Forex
      currentStep: 0,
      saving: false,
      loadingIndicators: false,
      availableIndicators: [],
      selectedIndicator: null,
      indicatorParams: [], // 指标参数声明
      indicatorParamValues: {}, // 用户设置的参数值
      cryptoSymbols: CRYPTO_SYMBOLS,
      // Watchlist symbols (same source as indicator-analysis page)
      loadingWatchlist: false,
      watchlist: [],
      exchangeOptions: EXCHANGE_OPTIONS,
      currentExchangeId: '',
      currentBrokerId: 'ibkr',
      testing: false,
      testResult: null,
      connectionTestResult: null,
      indicatorsLoaded: false, // 标记指标是否已加载
      editingStrategy: null, // 正在编辑的策略
      currentEquity: null, // 当前净值
      equityPollingTimer: null, // 净值轮询定时器
      // Backtest-like UI state (same as indicator-analysis BacktestModal step1)
      backtestCollapseKeys: ['risk'],
      trailingEnabledUi: false,
      entryPctMaxUi: 100,
      aiFilterEnabledUi: false,
      isEditMode: false, // 是否为编辑模式
      supportedIPs: [], // 白名单IP列表
      executionModeUi: 'signal',
      notifyChannelsUi: ['browser'],
      // User's notification settings from profile
      userNotificationSettings: {
        default_channels: ['browser'],
        telegram_bot_token: '',
        telegram_chat_id: '',
        email: '',
        phone: '',
        discord_webhook: '',
        webhook_url: '',
        webhook_token: ''
      },
      // Exchange credentials vault
      loadingExchangeCredentials: false,
      exchangeCredentials: [],
      saveCredentialUi: false,
      suppressApiClearOnce: false,
      // 多币种选择（创建模式）
      selectedSymbols: [],
      // 策略组折叠状态
      collapsedGroups: {},
      // 分组模式: 'strategy' 或 'symbol'
      groupByMode: 'strategy',
      // 添加交易对弹窗相关
      showAddSymbolModal: false,
      addSymbolMarket: 'Crypto',
      addSymbolMarketTypes: [
        { value: 'Crypto', i18nKey: 'dashboard.analysis.market.Crypto' },
        { value: 'USStock', i18nKey: 'dashboard.analysis.market.USStock' },
        { value: 'HShare', i18nKey: 'dashboard.analysis.market.HShare' },
        { value: 'AShare', i18nKey: 'dashboard.analysis.market.AShare' },
        { value: 'Forex', i18nKey: 'dashboard.analysis.market.Forex' },
        { value: 'Futures', i18nKey: 'dashboard.analysis.market.Futures' }
      ],
      addSymbolKeyword: '',
      searchingSymbol: false,
      symbolSearchResults: [],
      selectedAddSymbol: null,
      hasSearchedSymbol: false,
      addingSymbol: false,
      hotSymbols: [],
      loadingHotSymbols: false,
      searchTimer: null
      // Market category is inferred from Step 1 watchlist symbol ("Market:SYMBOL").
    }
  },
  beforeCreate () {
    this.form = this.$form.createForm(this)
  },
  mounted () {
    this.loadStrategies()
    this.loadUserNotificationSettings()
  },
  beforeDestroy () {
    this.stopEquityPolling()
  },
  methods: {
    async loadUserNotificationSettings () {
      // Load user's default notification settings from profile
      try {
        const res = await getNotificationSettings()
        if (res.code === 1 && res.data) {
          this.userNotificationSettings = {
            default_channels: res.data.default_channels || ['browser'],
            telegram_bot_token: res.data.telegram_bot_token || '',
            telegram_chat_id: res.data.telegram_chat_id || '',
            email: res.data.email || '',
            phone: res.data.phone || '',
            discord_webhook: res.data.discord_webhook || '',
            webhook_url: res.data.webhook_url || '',
            webhook_token: res.data.webhook_token || ''
          }
        }
      } catch (e) {
        // Silently fail, use default values
      }
    },
    async loadWatchlist () {
      this.loadingWatchlist = true
      try {
        const res = await getWatchlist({ userid: 1 })
        if (res && res.code === 1) {
          this.watchlist = Array.isArray(res.data) ? res.data : []
        } else {
          this.watchlist = []
        }
      } catch (e) {
        this.watchlist = []
      } finally {
        this.loadingWatchlist = false
      }
    },
    // ====== 添加交易对弹窗相关方法 ======
    handleCloseAddSymbolModal () {
      this.showAddSymbolModal = false
      this.addSymbolKeyword = ''
      this.symbolSearchResults = []
      this.selectedAddSymbol = null
      this.hasSearchedSymbol = false
    },
    handleAddSymbolMarketChange (market) {
      this.addSymbolMarket = market
      this.addSymbolKeyword = ''
      this.symbolSearchResults = []
      this.selectedAddSymbol = null
      this.hasSearchedSymbol = false
      // 加载该市场的热门标的
      this.loadHotSymbols(market)
    },
    // 搜索输入框变化时的处理（防抖）
    handleSymbolSearchInputChange (e) {
      const keyword = e.target.value
      this.addSymbolKeyword = keyword

      // 清除之前的定时器
      if (this.searchTimer) {
        clearTimeout(this.searchTimer)
      }

      // 如果关键词为空，清空搜索结果和状态
      if (!keyword || keyword.trim() === '') {
        this.symbolSearchResults = []
        this.hasSearchedSymbol = false
        this.selectedAddSymbol = null
        return
      }

      // 防抖：500ms后执行搜索
      this.searchTimer = setTimeout(() => {
        this.searchSymbolsInModal(keyword)
      }, 500)
    },
    // 搜索或直接添加（整合逻辑）
    async handleSearchSymbol (keyword) {
      if (!keyword || !keyword.trim()) {
        return
      }

      if (!this.addSymbolMarket) {
        this.$message.warning(this.$t('dashboard.analysis.modal.addStock.pleaseSelectMarket'))
        return
      }

      // 如果有搜索结果，不处理（让用户选择）
      if (this.symbolSearchResults.length > 0) {
        return
      }

      // 如果没有搜索结果，直接添加
      if (this.hasSearchedSymbol && this.symbolSearchResults.length === 0) {
        this.handleDirectAdd()
      } else {
        // 执行搜索
        this.searchSymbolsInModal(keyword)
      }
    },
    // 搜索标的（在添加股票弹窗中）
    async searchSymbolsInModal (keyword) {
      if (!keyword || keyword.trim() === '') {
        this.symbolSearchResults = []
        this.hasSearchedSymbol = false
        return
      }

      if (!this.addSymbolMarket) {
        return
      }

      this.searchingSymbol = true
      this.hasSearchedSymbol = true

      try {
        const res = await searchSymbols({
          market: this.addSymbolMarket,
          keyword: keyword.trim()
        })
        if (res && res.code === 1 && Array.isArray(res.data)) {
          this.symbolSearchResults = res.data
        } else {
          this.symbolSearchResults = []
        }
      } catch (e) {
        this.symbolSearchResults = []
      } finally {
        this.searchingSymbol = false
      }
    },
    // 直接添加（搜索无结果时）
    handleDirectAdd () {
      if (!this.addSymbolKeyword || !this.addSymbolKeyword.trim()) {
        this.$message.warning(this.$t('dashboard.analysis.modal.addStock.pleaseEnterSymbol'))
        return
      }

      if (!this.addSymbolMarket) {
        this.$message.warning(this.$t('dashboard.analysis.modal.addStock.pleaseSelectMarket'))
        return
      }

      // 设置选中的标的（手动输入，名称会在后端获取）
      this.selectedAddSymbol = {
        market: this.addSymbolMarket,
        symbol: this.addSymbolKeyword.trim().toUpperCase(),
        name: '' // 名称由后端通过API获取
      }
    },
    handleSelectAddSymbol (item) {
      this.selectedAddSymbol = {
        market: this.addSymbolMarket,
        symbol: item.symbol,
        name: item.name || ''
      }
    },
    // 加载热门标的
    async loadHotSymbols (market) {
      if (!market) {
        market = this.addSymbolMarket || 'Crypto'
      }

      if (!market) {
        return
      }

      this.loadingHotSymbols = true
      try {
        const res = await getHotSymbols({
          market: market,
          limit: 10
        })
        if (res && res.code === 1 && res.data) {
          this.hotSymbols = res.data
        } else {
          this.hotSymbols = []
        }
      } catch (error) {
        this.hotSymbols = []
      } finally {
        this.loadingHotSymbols = false
      }
    },
    async handleConfirmAddSymbol () {
      // 确定要添加的交易对
      let market = ''
      let symbol = ''

      // 检查是否选中了标的（从数据库选择或手动输入）
      if (this.selectedAddSymbol) {
        market = this.selectedAddSymbol.market
        symbol = this.selectedAddSymbol.symbol.toUpperCase()
      } else if (this.addSymbolKeyword && this.addSymbolKeyword.trim()) {
        // 如果没有选中，但搜索框有输入，使用搜索框的值
        if (!this.addSymbolMarket) {
          this.$message.warning(this.$t('dashboard.analysis.modal.addStock.pleaseSelectMarket'))
          return
        }
        market = this.addSymbolMarket
        symbol = this.addSymbolKeyword.trim().toUpperCase()
      } else {
        this.$message.warning(this.$t('dashboard.analysis.modal.addStock.pleaseSelectOrEnterSymbol'))
        return
      }

      this.addingSymbol = true
      try {
        // 调用添加自选API
        const res = await addWatchlist({
          userid: 1,
          market: market,
          symbol: symbol
        })
        if (res && res.code === 1) {
          this.$message.success(this.$t('dashboard.analysis.message.addStockSuccess'))
          // 重新加载自选列表
          await this.loadWatchlist()
          // 自动选中新添加的交易对
          const newValue = `${market}:${symbol}`
          if (this.isEditMode) {
            this.form.setFieldsValue({ symbol: newValue })
            this.handleWatchlistSymbolChange(newValue)
          } else {
            // 多选模式：添加到已选列表
            if (!this.selectedSymbols.includes(newValue)) {
              this.selectedSymbols = [...this.selectedSymbols, newValue]
            }
            this.handleMultiSymbolChange(this.selectedSymbols)
          }
          // 关闭弹窗
          this.handleCloseAddSymbolModal()
        } else {
          this.$message.error(res?.msg || this.$t('dashboard.analysis.message.addStockFailed'))
        }
      } catch (e) {
        const errorMsg = e?.response?.data?.msg || e?.message || this.$t('dashboard.analysis.message.addStockFailed')
        this.$message.error(errorMsg)
      } finally {
        this.addingSymbol = false
      }
    },
    // ====== 添加交易对弹窗相关方法 END ======
    filterWatchlistOption (input, option) {
      const value = option.componentOptions?.propsData?.value || ''
      // 始终显示"添加"选项
      if (value === '__add_symbol_option__') return true
      return String(value).toLowerCase().includes(String(input || '').toLowerCase())
    },
    filterWatchlistOptionWithAdd (input, option) {
      const value = option.componentOptions?.propsData?.value || ''
      // 始终显示"添加"选项
      if (value === '__add_symbol_option__') return true
      return String(value).toLowerCase().includes(String(input || '').toLowerCase())
    },
    handleMultiSymbolChangeWithAdd (vals) {
      // 检查是否点击了"添加"选项
      if (vals && vals.includes('__add_symbol_option__')) {
        // 从选中列表中移除特殊选项
        this.selectedSymbols = vals.filter(v => v !== '__add_symbol_option__')
        // 打开添加弹窗
        this.showAddSymbolModal = true
        // 加载热门标的
        this.loadHotSymbols(this.addSymbolMarket)
        return
      }
      this.handleMultiSymbolChange(vals)
    },
    getMarketColor (market) {
      const colors = {
        USStock: 'green',
        Crypto: 'purple',
        Forex: 'gold',
        Futures: 'cyan',
        AShare: 'blue',
        HShare: 'orange'
      }
      return colors[market] || 'default'
    },
    handleWatchlistSymbolChange (val) {
      // 检查是否点击了"添加"选项
      if (val === '__add_symbol_option__') {
        // 重置表单值（不选中特殊选项）
        this.$nextTick(() => {
          this.form.setFieldsValue({ symbol: undefined })
        })
        // 打开添加弹窗
        this.showAddSymbolModal = true
        // 加载热门标的
        this.loadHotSymbols(this.addSymbolMarket)
        return
      }
      // val format: "Market:SYMBOL" (same as indicator-analysis page)
      if (!val || typeof val !== 'string' || !val.includes(':')) {
        return
      }
      const idx = val.indexOf(':')
      const market = val.slice(0, idx)
      // Keep selection reactive for Step 3 execution gating
      this.selectedMarketCategory = market || 'Crypto'

      // Auto-set broker ID based on market category
      if (this.selectedMarketCategory === 'Forex') {
        this.currentBrokerId = 'mt5'
        try {
          this.form && this.form.setFieldsValue && this.form.setFieldsValue({ forex_broker_id: 'mt5' })
        } catch (e) { }
      } else if (['USStock', 'HShare'].includes(this.selectedMarketCategory)) {
        this.currentBrokerId = 'ibkr'
        try {
          this.form && this.form.setFieldsValue && this.form.setFieldsValue({ broker_id: 'ibkr' })
        } catch (e) { }
      }

      // Markets without live trading support: force back to signal mode
      // Crypto, USStock, HShare, Forex support live trading; others do not
      const supportsLiveTrading = ['Crypto', 'USStock', 'HShare', 'Forex'].includes(this.selectedMarketCategory)
      if (!supportsLiveTrading) {
        this.executionModeUi = 'signal'
        try {
          this.form && this.form.setFieldsValue && this.form.setFieldsValue({ execution_mode: 'signal' })
        } catch (e) { }
      }

      // Clear exchange selection when market changes (different markets use different exchanges)
      this.currentExchangeId = ''
      try {
        this.form && this.form.setFieldsValue && this.form.setFieldsValue({ exchange_id: undefined })
      } catch (e) { }
    },
    handleMultiSymbolChange (vals) {
      // vals: array like ["Crypto:BTC/USDT", "Crypto:ETH/USDT"]
      this.selectedSymbols = vals || []

      // Update market type based on selected symbols
      if (vals && vals.length > 0) {
        const firstVal = vals[0]
        if (typeof firstVal === 'string' && firstVal.includes(':')) {
          const idx = firstVal.indexOf(':')
          const market = firstVal.slice(0, idx)
          this.selectedMarketCategory = market || 'Crypto'
        }
      }

      // Auto-set broker ID based on market category
      if (this.selectedMarketCategory === 'Forex') {
        this.currentBrokerId = 'mt5'
        try {
          this.form && this.form.setFieldsValue && this.form.setFieldsValue({ forex_broker_id: 'mt5' })
        } catch (e) { }
      } else if (['USStock', 'HShare'].includes(this.selectedMarketCategory)) {
        this.currentBrokerId = 'ibkr'
        try {
          this.form && this.form.setFieldsValue && this.form.setFieldsValue({ broker_id: 'ibkr' })
        } catch (e) { }
      }

      // Markets without live trading support: force back to signal mode
      const supportsLiveTrading = ['Crypto', 'USStock', 'HShare', 'Forex'].includes(this.selectedMarketCategory)
      if (!supportsLiveTrading) {
        this.executionModeUi = 'signal'
        try {
          this.form && this.form.setFieldsValue && this.form.setFieldsValue({ execution_mode: 'signal' })
        } catch (e) { }
      }

      // Clear exchange selection when market changes
      this.currentExchangeId = ''
      try {
        this.form && this.form.setFieldsValue && this.form.setFieldsValue({ exchange_id: undefined })
      } catch (e) { }
    },
    async loadExchangeCredentials () {
      this.loadingExchangeCredentials = true
      try {
        const res = await listExchangeCredentials({ user_id: 1 })
        if (res && res.code === 1) {
          this.exchangeCredentials = (res.data && res.data.items) || []
        } else {
          this.exchangeCredentials = []
          this.$message.warning(res?.msg || this.$t('trading-assistant.messages.loadFailed'))
        }
      } catch (e) {
        this.exchangeCredentials = []
        this.$message.warning(this.$t('trading-assistant.exchange.testFailed'))
      } finally {
        this.loadingExchangeCredentials = false
      }
    },
    formatCredentialLabel (cred) {
      if (!cred) return ''
      const name = (cred.name || '').trim()
      const ex = cred.exchange_id || ''
      const hint = cred.api_key_hint || ''
      return name ? `${ex.toUpperCase()} - ${name} (${hint})` : `${ex.toUpperCase()} (${hint})`
    },
    async handleCredentialSelectChange (credentialId) {
      // Selecting a saved credential auto-fills exchange fields
      if (!credentialId) {
        return
      }

      // First try to find in local list to avoid API call delay/failure
      const localCred = this.exchangeCredentials.find(c => String(c.id) === String(credentialId))

      // Function to apply config
      const applyConfig = async (cfg) => {
        if (!cfg) return

        // 1. Update exchange ID to ensure correct fields (like passphrase) are rendered
        this.currentExchangeId = cfg.exchange_id || ''

        // 2. Wait for UI to update (render passphrase field if needed)
        await this.$nextTick()

        // 3. Set form values
        // Prevent handleExchangeSelectChange() from clearing API fields when we programmatically set exchange_id.
        this.suppressApiClearOnce = true
        this.form.setFieldsValue({
          exchange_id: cfg.exchange_id,
          api_key: cfg.api_key,
          secret_key: cfg.secret_key,
          passphrase: cfg.passphrase || ''
        })

        this.testResult = null
        this.connectionTestResult = null
      }

      try {
        // Try to fetch full config including secrets
        const res = await getExchangeCredential(credentialId, { user_id: 1 })
        if (res && res.code === 1 && res.data && res.data.config) {
          await applyConfig(res.data.config)
        } else if (localCred) {
          // Fallback to local data if API fails or returns no config
          // Note: Local list usually doesn't have secrets, but just in case
          await applyConfig(localCred)
        }
      } catch (e) {
        // Fallback to local data on error
        if (localCred) {
          await applyConfig(localCred)
        }
      }
    },
    onSaveCredentialChange (e) {
      const checked = !!(e && e.target && e.target.checked)
      this.saveCredentialUi = checked
      try {
        this.form && this.form.setFieldsValue && this.form.setFieldsValue({ save_credential: checked })
      } catch (err) { }
    },
    onExecutionModeChange (e) {
      const v = e && e.target ? e.target.value : e
      this.executionModeUi = v || 'signal'
      // If market doesn't support live trading, force signal mode
      if (!this.canUseLiveTrading && this.executionModeUi !== 'signal') {
        this.executionModeUi = 'signal'
        try {
          this.form && this.form.setFieldsValue && this.form.setFieldsValue({ execution_mode: 'signal' })
        } catch (err) { }
      }
    },
    onNotifyChannelsChange (vals) {
      this.notifyChannelsUi = Array.isArray(vals) ? vals : []
    },
    formatCurrency (value) {
      if (value === null || value === undefined) return '-'
      return '$' + value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    },
    formatPnl (value) {
      if (value === null || value === undefined) return '-'
      const prefix = value >= 0 ? '+' : ''
      return prefix + '$' + Math.abs(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    },
    formatPnlPercent (value) {
      if (value === null || value === undefined) return '-'
      const prefix = value >= 0 ? '+' : ''
      return prefix + Math.abs(value).toFixed(2) + '%'
    },
    async loadStrategies () {
      this.loading = true
      try {
        const res = await getStrategyList()
        if (res.code === 1) {
          // 显示所有策略（包括指标策略和AI策略）
          const allStrategies = res.data.strategies || []
          this.strategies = allStrategies
          // 如果有选中的策略，更新它
          if (this.selectedStrategy) {
            const updated = this.strategies.find(s => s.id === this.selectedStrategy.id)
            if (updated) {
              this.selectedStrategy = updated
            } else {
              // 如果选中的策略被过滤掉了，清空选中状态
              this.selectedStrategy = null
            }
          }
        } else {
          this.$message.error(res.msg || this.$t('trading-assistant.messages.loadFailed'))
        }
      } catch (error) {
        this.$message.error(this.$t('trading-assistant.messages.loadFailed'))
      } finally {
        this.loading = false
      }
    },
    handleCreateStrategy () {
      // Local mode: open indicator strategy modal directly
      this.isEditMode = false
      this.editingStrategy = null
      this.strategyType = 'indicator'
      this.currentStep = 0
      this.currentExchangeId = ''
      this.currentBrokerId = 'ibkr'
      this.selectedIndicator = null
      this.testResult = null
      this.connectionTestResult = null
      this.executionModeUi = 'signal'
      this.notifyChannelsUi = ['browser']
      this.saveCredentialUi = false
      this.backtestCollapseKeys = ['risk']
      this.trailingEnabledUi = false
      this.entryPctMaxUi = 100
      this.aiFilterEnabledUi = false
      this.selectedMarketCategory = 'Crypto'
      this.selectedSymbols = []

      this.form.resetFields()
      this.form.setFieldsValue({
        execution_mode: 'signal',
        notify_channels: ['browser'],
        save_credential: false
      })
      this.showFormModal = true

      this.$nextTick(() => {
        this.loadWatchlist()
        this.loadIndicators()
        this.loadExchangeCredentials()
      })
    },
    handleEditStrategy (strategy) {
      // 如果策略正在运行，提示用户先停止
      if (strategy.status === 'running') {
        this.$message.warning(this.$t('trading-assistant.messages.runningWarning'))
        return
      }

      // Local mode: indicator strategy only
      this.strategyType = 'indicator'

      this.isEditMode = true
      this.editingStrategy = strategy
      this.currentStep = 0
      this.currentExchangeId = ''
      this.selectedIndicator = null
      this.testResult = null
      this.connectionTestResult = null
      this.form.resetFields()
      this.backtestCollapseKeys = ['risk']
      this.trailingEnabledUi = false
      this.entryPctMaxUi = 100
      this.aiFilterEnabledUi = false

      // IMPORTANT:
      // Ensure modal is visible BEFORE filling form values, otherwise some fields are not registered yet
      // (especially Step 2/3 fields) and setFieldsValue may silently drop values.
      this.showFormModal = true

      // Delay loading to ensure modal/form items are mounted.
      this.$nextTick(async () => {
        // Keep data sources in sync (same as create flow)
        this.loadWatchlist()
        this.loadIndicators()
        this.loadExchangeCredentials()
        await this.loadStrategyDataToForm(strategy)
      })
    },
    async loadStrategyDataToForm (strategy) {
      // 先加载指标列表（如果需要）
      if (!this.indicatorsLoaded) {
        await this.loadIndicators()
      }

      // 使用 nextTick 确保表单已初始化
      await this.$nextTick()

      // Market / execution / notification defaults (backward compatible)
      this.selectedMarketCategory = strategy.market_category || 'Crypto'
      const executionMode = strategy.execution_mode || 'signal'
      this.executionModeUi = executionMode
      const notifyChannels = (strategy.notification_config && strategy.notification_config.channels) || ['browser']
      this.notifyChannelsUi = Array.isArray(notifyChannels) ? notifyChannels : ['browser']

      // Initialize trading config UI states first
      let trailingEnabled = false
      // Initialize AI filter state
      let aiFilterEnabled = false

      if (strategy.trading_config) {
        const tc = strategy.trading_config || {}
        const trailingObj = (tc.trailing && typeof tc.trailing === 'object') ? tc.trailing : null
        trailingEnabled = (tc.trailing_enabled !== undefined) ? !!tc.trailing_enabled : !!(trailingObj && trailingObj.enabled)

        // Check AI filter - handle various truthy values
        const aiVal = tc.enable_ai_filter
        aiFilterEnabled = aiVal === true || aiVal === 'true' || aiVal === 1 || aiVal === '1'

        // Determine which collapse panels to open based on config to ensure fields are rendered
        const scaleObj = (tc.scale && typeof tc.scale === 'object') ? tc.scale : null
        const posObj = (tc.position && typeof tc.position === 'object') ? tc.position : null
        const panels = new Set(['risk']) // Always keep risk panel open or as default

        // Check Scale panel content
        if (
          tc.trend_add_enabled || tc.dca_add_enabled ||
          (scaleObj && (scaleObj.trendAdd?.enabled || scaleObj.dcaAdd?.enabled))
        ) {
          panels.add('scale')
        }

        // Check Reduce panel content
        if (
          tc.trend_reduce_enabled || tc.adverse_reduce_enabled ||
          (scaleObj && (scaleObj.trendReduce?.enabled || scaleObj.adverseReduce?.enabled))
        ) {
          panels.add('reduce')
        }

        // Check Position panel content - open if entry_pct is customized or if we just want to show it
        // Considering "Entry sizing" parameter missing issue, better to expand it if data exists
        if (tc.entry_pct !== undefined || (posObj && posObj.entryPct !== undefined)) {
          panels.add('position')
        }

        this.backtestCollapseKeys = Array.from(panels)
      }
      this.trailingEnabledUi = trailingEnabled
      this.aiFilterEnabledUi = aiFilterEnabled

      // Wait for DOM update to ensure v-if fields (trailing) and Collapse panels are rendered
      await this.$nextTick()

      // First, set the "switch" fields that might control v-if visibility of other fields
      // For ai_filter, it relies on aiFilterEnabledUi which is updated above, so form value is secondary for UI display
      // But we still need to set form value for submission
      this.form.setFieldsValue({
        enable_ai_filter: aiFilterEnabled
      })

      // Wait for form value to update and v-if to re-render (for ai_filter)
      await this.$nextTick()

      this.form.setFieldsValue({
        execution_mode: this.executionModeUi,
        notify_channels: this.notifyChannelsUi,
        notify_email: strategy.notification_config?.targets?.email || '',
        notify_phone: strategy.notification_config?.targets?.phone || '',
        notify_telegram: strategy.notification_config?.targets?.telegram || '',
        notify_discord: strategy.notification_config?.targets?.discord || '',
        notify_webhook: strategy.notification_config?.targets?.webhook || ''
      })

      // 加载指标数据
      if (strategy.indicator_config && strategy.indicator_config.indicator_id) {
        // 查找对应的指标，确保ID类型一致（处理 string vs number 问题）
        const targetId = strategy.indicator_config.indicator_id
        // 使用字符串比较处理类型不匹配问题（string vs number）
        const indicator = this.availableIndicators.find(ind => {
          return String(ind.id) === String(targetId)
        })

        if (indicator) {
          // 找到匹配的指标，使用指标对象中的ID（确保类型一致）
          const finalId = String(indicator.id)
          this.form.setFieldsValue({
            indicator_id: finalId
          })
          await this.handleIndicatorChange(finalId)

          // 恢复已保存的指标参数值 - 使用 $set 确保响应式
          const savedParams = strategy.trading_config?.indicator_params
          if (savedParams && typeof savedParams === 'object') {
            Object.keys(savedParams).forEach(key => {
              if (key in this.indicatorParamValues) {
                this.$set(this.indicatorParamValues, key, savedParams[key])
              }
            })
          }
        } else {
          // 如果找不到，仍然设置值，但可能显示为ID
          this.form.setFieldsValue({
            indicator_id: String(targetId)
          })
        }
      }

      // Load exchange/broker configuration
      if (strategy.exchange_config) {
        const exchangeId = strategy.exchange_config.exchange_id || ''
        const isLive = this.executionModeUi === 'live'
        const supportsLiveTrading = ['Crypto', 'USStock', 'HShare', 'Forex'].includes(this.selectedMarketCategory)
        const isBrokerMarket = ['USStock', 'HShare'].includes(this.selectedMarketCategory)
        const isForexMarket = this.selectedMarketCategory === 'Forex'

        if (isLive && supportsLiveTrading) {
          if (isBrokerMarket) {
            // Broker configuration (US/HK stocks)
            this.currentBrokerId = exchangeId || 'ibkr'
            this.form.setFieldsValue({
              broker_id: exchangeId || 'ibkr',
              ibkr_host: strategy.exchange_config.ibkr_host || '127.0.0.1',
              ibkr_port: strategy.exchange_config.ibkr_port || 7497,
              ibkr_client_id: strategy.exchange_config.ibkr_client_id || 1,
              ibkr_account: strategy.exchange_config.ibkr_account || ''
            })
          } else if (isForexMarket) {
            // MT5 configuration (Forex)
            this.currentBrokerId = exchangeId || 'mt5'
            this.form.setFieldsValue({
              forex_broker_id: exchangeId || 'mt5',
              mt5_server: strategy.exchange_config.mt5_server || '',
              mt5_login: strategy.exchange_config.mt5_login || '',
              mt5_password: strategy.exchange_config.mt5_password || '',
              mt5_terminal_path: strategy.exchange_config.mt5_terminal_path || ''
            })
          } else {
            // Crypto exchange configuration
            this.currentExchangeId = exchangeId
            this.suppressApiClearOnce = true
            this.form.setFieldsValue({
              exchange_id: exchangeId,
              credential_id: strategy.exchange_config.credential_id || undefined,
              api_key: strategy.exchange_config.api_key || '',
              secret_key: strategy.exchange_config.secret_key || '',
              passphrase: strategy.exchange_config.passphrase || ''
            })

            // If a vault credential is selected, auto-fill secrets from vault
            const credId = strategy.exchange_config.credential_id
            if (credId) {
              await this.handleCredentialSelectChange(credId)
            }
          }
        }

        // Update UI state
        if (isBrokerMarket || isForexMarket) {
          this.currentBrokerId = exchangeId || (isForexMarket ? 'mt5' : 'ibkr')
        } else {
          this.currentExchangeId = exchangeId
        }
      }

      // 加载交易配置
      if (strategy.trading_config) {
        const tc = strategy.trading_config || {}
        const trailingObj = (tc.trailing && typeof tc.trailing === 'object') ? tc.trailing : null
        const scaleObj = (tc.scale && typeof tc.scale === 'object') ? tc.scale : null
        const posObj = (tc.position && typeof tc.position === 'object') ? tc.position : null

        // Backward compatible: nested configs from indicator-analysis backtest modal
        const trendAddObj = scaleObj && scaleObj.trendAdd ? scaleObj.trendAdd : null
        const dcaAddObj = scaleObj && scaleObj.dcaAdd ? scaleObj.dcaAdd : null
        const trendReduceObj = scaleObj && scaleObj.trendReduce ? scaleObj.trendReduce : null
        const adverseReduceObj = scaleObj && scaleObj.adverseReduce ? scaleObj.adverseReduce : null

        // Backward compatible: show symbol as "Market:SYMBOL" for watchlist dropdown
        const rawSymbol = tc.symbol
        const symbolValue = (typeof rawSymbol === 'string' && rawSymbol.includes(':'))
          ? rawSymbol
          : `${this.selectedMarketCategory}:${rawSymbol}`
        this.form.setFieldsValue({
          strategy_name: strategy.strategy_name,
          symbol: symbolValue,
          initial_capital: tc.initial_capital,
          leverage: tc.leverage,
          trade_direction: tc.trade_direction || 'long',
          timeframe: tc.timeframe || '1H',
          market_type: (tc.market_type === 'futures' ? 'swap' : (tc.market_type || 'swap')),
          take_profit_pct: tc.take_profit_pct || 0,
          stop_loss_pct: tc.stop_loss_pct || 0,
          // Trailing: support both flat fields and nested trailing object
          trailing_enabled: trailingEnabled,
          trailing_stop_pct: (tc.trailing_stop_pct !== undefined) ? (tc.trailing_stop_pct || 0) : (trailingObj ? (trailingObj.pct || 0) : 0),
          trailing_activation_pct: (tc.trailing_activation_pct !== undefined) ? (tc.trailing_activation_pct || 0) : (trailingObj ? (trailingObj.activationPct || 0) : 0),
          // Scale / reduce: support both flat fields and nested objects
          trend_add_enabled: (tc.trend_add_enabled !== undefined) ? !!tc.trend_add_enabled : !!(trendAddObj && trendAddObj.enabled),
          trend_add_step_pct: (tc.trend_add_step_pct !== undefined) ? (tc.trend_add_step_pct || 0) : (trendAddObj ? (trendAddObj.stepPct || 0) : 0),
          trend_add_size_pct: (tc.trend_add_size_pct !== undefined) ? (tc.trend_add_size_pct || 0) : (trendAddObj ? (trendAddObj.sizePct || 0) : 0),
          trend_add_max_times: (tc.trend_add_max_times !== undefined) ? (tc.trend_add_max_times || 0) : (trendAddObj ? (trendAddObj.maxTimes || 0) : 0),
          dca_add_enabled: (tc.dca_add_enabled !== undefined) ? !!tc.dca_add_enabled : !!(dcaAddObj && dcaAddObj.enabled),
          dca_add_step_pct: (tc.dca_add_step_pct !== undefined) ? (tc.dca_add_step_pct || 0) : (dcaAddObj ? (dcaAddObj.stepPct || 0) : 0),
          dca_add_size_pct: (tc.dca_add_size_pct !== undefined) ? (tc.dca_add_size_pct || 0) : (dcaAddObj ? (dcaAddObj.sizePct || 0) : 0),
          dca_add_max_times: (tc.dca_add_max_times !== undefined) ? (tc.dca_add_max_times || 0) : (dcaAddObj ? (dcaAddObj.maxTimes || 0) : 0),
          trend_reduce_enabled: (tc.trend_reduce_enabled !== undefined) ? !!tc.trend_reduce_enabled : !!(trendReduceObj && trendReduceObj.enabled),
          trend_reduce_step_pct: (tc.trend_reduce_step_pct !== undefined) ? (tc.trend_reduce_step_pct || 0) : (trendReduceObj ? (trendReduceObj.stepPct || 0) : 0),
          trend_reduce_size_pct: (tc.trend_reduce_size_pct !== undefined) ? (tc.trend_reduce_size_pct || 0) : (trendReduceObj ? (trendReduceObj.sizePct || 0) : 0),
          trend_reduce_max_times: (tc.trend_reduce_max_times !== undefined) ? (tc.trend_reduce_max_times || 0) : (trendReduceObj ? (trendReduceObj.maxTimes || 0) : 0),
          adverse_reduce_enabled: (tc.adverse_reduce_enabled !== undefined) ? !!tc.adverse_reduce_enabled : !!(adverseReduceObj && adverseReduceObj.enabled),
          adverse_reduce_step_pct: (tc.adverse_reduce_step_pct !== undefined) ? (tc.adverse_reduce_step_pct || 0) : (adverseReduceObj ? (adverseReduceObj.stepPct || 0) : 0),
          adverse_reduce_size_pct: (tc.adverse_reduce_size_pct !== undefined) ? (tc.adverse_reduce_size_pct || 0) : (adverseReduceObj ? (adverseReduceObj.sizePct || 0) : 0),
          adverse_reduce_max_times: (tc.adverse_reduce_max_times !== undefined) ? (tc.adverse_reduce_max_times || 0) : (adverseReduceObj ? (adverseReduceObj.maxTimes || 0) : 0),
          entry_pct: (tc.entry_pct === 0 || tc.entry_pct) ? tc.entry_pct : (posObj && posObj.entryPct ? posObj.entryPct : 100),
          // AI智能决策过滤
          enable_ai_filter: aiFilterEnabled
        })

        this.$nextTick(() => {
          this.recalcEntryPctMaxUi()
          this.normalizeEntryPct()
        })
      }
    },
    handleSelectStrategy (strategy) {
      this.selectedStrategy = strategy
      this.currentEquity = null // 重置当前净值
      this.loadStrategyDetails()
      this.startEquityPolling() // 开始轮询净值
    },
    async loadStrategyDetails () {
      if (!this.selectedStrategy) {
        return Promise.resolve()
      }
      // 加载净值数据
      try {
        const res = await getStrategyEquityCurve(this.selectedStrategy.id)
        if (res.code === 1 && res.data) {
          // Local backend returns an array curve: [{ time, equity }, ...]
          if (Array.isArray(res.data) && res.data.length > 0) {
            const last = res.data[res.data.length - 1]
            this.currentEquity = last.equity
          } else {
            const base = this.selectedStrategy.trading_config?.initial_capital || this.selectedStrategy.initial_capital
            this.currentEquity = base || null
          }
        }
      } catch (error) {
      }
    },
    startEquityPolling () {
      this.stopEquityPolling()
      if (!this.selectedStrategy) return

      // 初始加载一次
      this.loadStrategyDetails()

      // 每30秒轮询一次
      this.equityPollingTimer = setInterval(() => {
        this.loadStrategyDetails()
      }, 30000)
    },
    stopEquityPolling () {
      if (this.equityPollingTimer) {
        clearInterval(this.equityPollingTimer)
        this.equityPollingTimer = null
      }
    },
    handleCloseModal () {
      this.showFormModal = false
      this.editingStrategy = null
      this.isEditMode = false
      this.strategyType = 'indicator'
      this.currentStep = 0
      this.currentExchangeId = ''
      this.selectedIndicator = null
      this.testResult = null
      this.connectionTestResult = null
      this.indicatorsLoaded = false
      this.availableIndicators = []
      this.backtestCollapseKeys = ['risk']
      this.trailingEnabledUi = false
      this.entryPctMaxUi = 100
      this.aiFilterEnabledUi = false

      this.form.resetFields()
    },
    handleRefresh () {
      this.loadStrategies()
      this.showFormModal = false
    },
    handleMenuClick (key, strategy) {
      switch (key) {
        case 'start':
          this.handleStartStrategy(strategy.id)
          break
        case 'stop':
          this.handleStopStrategy(strategy.id)
          break
        case 'edit':
          this.handleEditStrategy(strategy)
          break
        case 'delete':
          this.handleDeleteStrategy(strategy)
          break
      }
    },
    toggleGroup (groupId) {
      this.$set(this.collapsedGroups, groupId, !this.collapsedGroups[groupId])
    },
    async handleGroupMenuClick (key, group) {
      const strategyIds = group.strategies.map(s => s.id)
      switch (key) {
        case 'startAll':
          await this.handleBatchStartStrategies(strategyIds, group.baseName)
          break
        case 'stopAll':
          await this.handleBatchStopStrategies(strategyIds, group.baseName)
          break
        case 'deleteAll':
          await this.handleBatchDeleteStrategies(strategyIds, group.baseName)
          break
      }
    },
    async handleBatchStartStrategies (strategyIds, groupName) {
      try {
        const res = await batchStartStrategies({ strategy_ids: strategyIds })
        if (res.code === 1) {
          const count = res.data?.success_ids?.length || strategyIds.length
          this.$message.success(this.$t('trading-assistant.messages.batchStartSuccess', { count }))
          this.loadStrategies()
        } else {
          this.$message.error(res.msg || this.$t('trading-assistant.messages.batchStartFailed'))
        }
      } catch (error) {
        this.$message.error(this.$t('trading-assistant.messages.batchStartFailed'))
      }
    },
    async handleBatchStopStrategies (strategyIds, groupName) {
      try {
        const res = await batchStopStrategies({ strategy_ids: strategyIds })
        if (res.code === 1) {
          const count = res.data?.success_ids?.length || strategyIds.length
          this.$message.success(this.$t('trading-assistant.messages.batchStopSuccess', { count }))
          this.loadStrategies()
        } else {
          this.$message.error(res.msg || this.$t('trading-assistant.messages.batchStopFailed'))
        }
      } catch (error) {
        this.$message.error(this.$t('trading-assistant.messages.batchStopFailed'))
      }
    },
    async handleBatchDeleteStrategies (strategyIds, groupName) {
      const confirmText = this.$t('trading-assistant.messages.batchDeleteConfirm', {
        count: strategyIds.length,
        name: groupName
      })
      this.$confirm({
        title: this.$t('trading-assistant.deleteAll'),
        content: confirmText,
        okText: this.$t('trading-assistant.deleteAll'),
        okType: 'danger',
        cancelText: this.$t('trading-assistant.form.cancel'),
        onOk: async () => {
          try {
            const res = await batchDeleteStrategies({ strategy_ids: strategyIds })
            if (res.code === 1) {
              const count = res.data?.success_ids?.length || strategyIds.length
              this.$message.success(this.$t('trading-assistant.messages.batchDeleteSuccess', { count }))
              // 如果删除的策略包含当前选中的策略，清空选中状态
              if (this.selectedStrategy && strategyIds.includes(this.selectedStrategy.id)) {
                this.selectedStrategy = null
                this.stopEquityPolling()
              }
              this.loadStrategies()
            } else {
              this.$message.error(res.msg || this.$t('trading-assistant.messages.batchDeleteFailed'))
            }
          } catch (error) {
            this.$message.error(this.$t('trading-assistant.messages.batchDeleteFailed'))
          }
        }
      })
    },
    async handleStartStrategy (id) {
      try {
        const res = await startStrategy(id)
        if (res.code === 1) {
          this.$message.success(this.$t('trading-assistant.messages.startSuccess'))
          this.loadStrategies()
          // 更新选中的策略状态
          if (this.selectedStrategy && this.selectedStrategy.id === id) {
            this.selectedStrategy.status = 'running'
          }
        } else {
          this.$message.error(res.msg || this.$t('trading-assistant.messages.startFailed'))
        }
      } catch (error) {
        this.$message.error(this.$t('trading-assistant.messages.startFailed'))
      }
    },
    async handleStopStrategy (id) {
      try {
        const res = await stopStrategy(id)
        if (res.code === 1) {
          this.$message.success(this.$t('trading-assistant.messages.stopSuccess'))
          this.loadStrategies()
          // 更新选中的策略状态
          if (this.selectedStrategy && this.selectedStrategy.id === id) {
            this.selectedStrategy.status = 'stopped'
          }
        } else {
          this.$message.error(res.msg || this.$t('trading-assistant.messages.stopFailed'))
        }
      } catch (error) {
        this.$message.error(this.$t('trading-assistant.messages.stopFailed'))
      }
    },
    handleDeleteStrategy (strategy) {
      const confirmText = this.$t('trading-assistant.messages.deleteConfirmWithName', {
        name: strategy.strategy_name
      })
      this.$confirm({
        title: this.$t('trading-assistant.deleteStrategy'),
        content: confirmText,
        okText: this.$t('trading-assistant.deleteStrategy'),
        okType: 'danger',
        cancelText: this.$t('trading-assistant.form.cancel'),
        onOk: async () => {
          try {
            const res = await deleteStrategy(strategy.id)
            if (res.code === 1) {
              this.$message.success(this.$t('trading-assistant.messages.deleteSuccess'))
              if (this.selectedStrategy && this.selectedStrategy.id === strategy.id) {
                this.selectedStrategy = null
                this.stopEquityPolling() // 停止轮询
              }
              this.loadStrategies()
            } else {
              this.$message.error(res.msg || this.$t('trading-assistant.messages.deleteFailed'))
            }
          } catch (error) {
            this.$message.error(this.$t('trading-assistant.messages.deleteFailed'))
          }
        }
      })
    },
    getStatusColor (status) {
      const colors = {
        running: 'green',
        stopped: 'default',
        error: 'red'
      }
      return colors[status] || 'default'
    },
    getStatusText (status) {
      return this.$t(`trading-assistant.status.${status}`) || status
    },
    getStrategyTypeText (type) {
      return this.$t(`trading-assistant.strategyType.${type}`) || type
    },
    getTradeDirectionText (direction) {
      if (!direction) return ''
      const directionMap = {
        long: this.$t('trading-assistant.form.tradeDirectionLong') || '做多',
        short: this.$t('trading-assistant.form.tradeDirectionShort') || '做空',
        both: this.$t('trading-assistant.form.tradeDirectionBoth') || '双向'
      }
      return directionMap[direction] || direction
    },
    // 指标相关方法
    async handleIndicatorSelectFocus () {
      // 懒加载：只在用户点击选择框时才加载指标
      if (!this.indicatorsLoaded && !this.loadingIndicators) {
        await this.loadIndicators()
      }
    },
    async loadIndicators () {
      if (this.loadingIndicators) {
        // 如果正在加载，等待加载完成
        return new Promise((resolve) => {
          const checkInterval = setInterval(() => {
            if (!this.loadingIndicators) {
              clearInterval(checkInterval)
              resolve()
            }
          }, 100)
        })
      }

      if (this.indicatorsLoaded) {
        return Promise.resolve()
      }

      // 获取用户ID
      const userInfo = this.$store.getters.userInfo || {}
      const userId = userInfo.id || 1

      this.loadingIndicators = true
      try {
        // 使用和 indicator-analysis 页面相同的接口
        const res = await request({
          url: '/api/indicator/getIndicators',
          method: 'get',
          params: {
            userid: userId
          }
        })

        if (res.code === 1 && res.data) {
          // 将所有指标（包括选购的和自己创建的）合并到一个数组
          const indicators = res.data.map(item => ({
            id: item.id,
            name: item.name,
            description: item.description,
            type: item.indicator_type || item.indicatorType || 'python',
            code: item.code,
            is_buy: item.is_buy,
            source: item.is_buy === 1 ? 'bought' : 'custom'
          }))

          this.availableIndicators = indicators
          this.indicatorsLoaded = true
        } else {
          this.availableIndicators = []
          this.$message.warning(res.msg || this.$t('trading-assistant.messages.loadIndicatorsFailed'))
        }
      } catch (error) {
        this.availableIndicators = []
        this.$message.warning(this.$t('trading-assistant.messages.loadIndicatorsFailed'))
      } finally {
        this.loadingIndicators = false
      }
    },
    async handleIndicatorChange (indicatorId) {
      const idStr = String(indicatorId)
      this.selectedIndicator = this.availableIndicators.find(ind => String(ind.id) === idStr)

      // 获取指标参数声明
      this.indicatorParams = []
      this.indicatorParamValues = {}
      if (indicatorId) {
        try {
          const res = await this.$http.get('/api/indicator/getIndicatorParams', {
            params: { indicator_id: indicatorId }
          })
          // 响应拦截器已返回 response.data，所以直接访问 res.code 和 res.data
          if (res && res.code === 1 && Array.isArray(res.data)) {
            this.indicatorParams = res.data
            // 初始化参数值为默认值 - 先构建完整对象再赋值，确保响应式
            const paramValues = {}
            res.data.forEach(p => {
              paramValues[p.name] = p.default
            })
            this.indicatorParamValues = paramValues
          }
        } catch (err) {
          console.warn('Failed to load indicator params:', err)
        }
      }
    },
    handleMarketTypeChange (e) {
      const marketType = e.target.value
      // 如果切换到现货，自动设置交易方向为做多，杠杆为1
      if (marketType === 'spot') {
        this.form.setFieldsValue({
          trade_direction: 'long',
          leverage: 1
        })
      }
    },
    // --- Backtest-like UI helpers (Ant Form getFieldValue is not reactive) ---
    recalcEntryPctMaxUi () {
      if (!this.form) {
        this.entryPctMaxUi = 100
        return
      }
      const trendOn = !!this.form.getFieldValue('trend_add_enabled')
      const dcaOn = !!this.form.getFieldValue('dca_add_enabled')
      const trendTimes = Number(this.form.getFieldValue('trend_add_max_times') || 0)
      const dcaTimes = Number(this.form.getFieldValue('dca_add_max_times') || 0)
      const trendSizePct = Number(this.form.getFieldValue('trend_add_size_pct') || 0)
      const dcaSizePct = Number(this.form.getFieldValue('dca_add_size_pct') || 0)

      const reservePct = (trendOn ? trendTimes * trendSizePct : 0) + (dcaOn ? dcaTimes * dcaSizePct : 0)
      const maxEntryPct = Math.max(0, Math.min(100, 100 - reservePct))
      this.entryPctMaxUi = maxEntryPct
    },
    normalizeEntryPct () {
      if (!this.form) return
      const current = Number(this.form.getFieldValue('entry_pct') || 0)
      const max = Number(this.entryPctMaxUi || 100)
      if (current > max) {
        this.form.setFieldsValue({ entry_pct: max })
      }
    },
    onTrendAddToggle (checked) {
      if (!this.form) return
      // Mutual exclusion to avoid double scale-in on the same candle.
      if (checked) {
        this.form.setFieldsValue({ dca_add_enabled: false })
      }
      this.$nextTick(() => {
        this.recalcEntryPctMaxUi()
        this.normalizeEntryPct()
      })
    },
    onDcaAddToggle (checked) {
      if (!this.form) return
      if (checked) {
        this.form.setFieldsValue({ trend_add_enabled: false })
      }
      this.$nextTick(() => {
        this.recalcEntryPctMaxUi()
        this.normalizeEntryPct()
      })
    },
    onScaleParamsChange () {
      this.$nextTick(() => {
        this.recalcEntryPctMaxUi()
        this.normalizeEntryPct()
      })
    },
    onEntryPctChange () {
      this.$nextTick(() => this.normalizeEntryPct())
    },
    onTrailingToggle (checked) {
      if (!this.form) return
      this.trailingEnabledUi = !!checked
      // Only show fields when enabled; also clear values when disabled.
      if (!checked) {
        this.form.setFieldsValue({ trailing_stop_pct: 0, trailing_activation_pct: 0 })
      }
    },
    onAiFilterToggle (checked) {
      this.aiFilterEnabledUi = !!checked
      // Ensure rc-form value is always in sync even if decorator event binding gets overridden.
      try {
        this.form && this.form.setFieldsValue && this.form.setFieldsValue({ enable_ai_filter: !!checked })
      } catch (e) { }
    },
    filterIndicatorOption (input, option) {
      const text = option.componentOptions.children[0].children[0].text
      return text.toLowerCase().indexOf(input.toLowerCase()) >= 0
    },
    filterSymbolOption (input, option) {
      return option.componentOptions.children[0].text.toLowerCase().indexOf(input.toLowerCase()) >= 0
    },
    getIndicatorTypeColor (type) {
      const colors = {
        trend: 'blue',
        momentum: 'green',
        volatility: 'orange',
        volume: 'purple',
        custom: 'default'
      }
      return colors[type] || 'default'
    },
    getIndicatorTypeName (type) {
      return this.$t(`trading-assistant.indicatorType.${type}`) || type
    },
    // 交易所相关方法
    getExchangeName (exchange) {
      if (exchange.labelKey) {
        const translationKey = `trading-assistant.exchangeNames.${exchange.labelKey}`
        const translated = this.$t(translationKey)
        // 如果翻译不存在，返回键值本身，否则返回翻译后的名称
        if (translated === translationKey) {
          // 翻译不存在，返回交易所ID的首字母大写
          return exchange.value.charAt(0).toUpperCase() + exchange.value.slice(1)
        }
        return translated
      }
      return exchange.label || exchange.value
    },
    getExchangeDisplayName (exchangeId) {
      if (!exchangeId) return ''
      // 查找对应的交易所选项
      const exchange = this.exchangeOptions.find(ex => ex.value === exchangeId)
      if (exchange) {
        return this.getExchangeName(exchange)
      }
      // 如果找不到，返回格式化的交易所ID
      return exchangeId.charAt(0).toUpperCase() + exchangeId.slice(1)
    },
    getExchangeTagColor (exchangeId) {
      // 为不同交易所设置不同的标签颜色
      const colorMap = {
        binance: 'gold',
        okx: 'blue',
        coinbaseexchange: 'cyan',
        kraken: 'purple',
        bitfinex: 'geekblue',
        huobi: 'orange',
        gate: 'green',
        mexc: 'lime',
        kucoin: 'volcano',
        bybit: 'red',
        bitget: 'magenta',
        bitmex: 'red',
        deribit: 'blue',
        phemex: 'cyan',
        bitmart: 'geekblue',
        bitstamp: 'purple',
        bittrex: 'orange',
        poloniex: 'green',
        gemini: 'lime',
        cryptocom: 'volcano',
        blockchaincom: 'magenta',
        bitflyer: 'red',
        upbit: 'blue',
        bithumb: 'cyan',
        coinone: 'purple',
        zb: 'geekblue',
        lbank: 'orange',
        bibox: 'green',
        bigone: 'lime',
        bitrue: 'volcano',
        coinex: 'magenta',
        ftx: 'red',
        ftxus: 'blue',
        binanceus: 'gold',
        binancecoinm: 'gold',
        binanceusdm: 'gold',
        ibkr: 'green'
      }
      return colorMap[exchangeId] || 'default'
    },
    handleApiConfigChange () {
      // 当API配置字段变化时，清空测试结果，需要重新测试
      this.testResult = null
      this.connectionTestResult = null
    },
    getModalPopupContainer () {
      // Return document.body for Select dropdown to avoid modal scroll issues
      return window.document.body
    },
    handleBrokerSelectChange (value) {
      this.currentBrokerId = value || 'ibkr'
      this.testResult = null
      this.connectionTestResult = null
    },
    handleForexBrokerSelectChange (value) {
      this.currentBrokerId = value || 'mt5'
      this.testResult = null
      this.connectionTestResult = null
    },
    handleExchangeSelectChange (value) {
      this.currentExchangeId = value || ''
      this.testResult = null
      this.connectionTestResult = null

      // If exchange_id is set programmatically (e.g. by selecting a saved credential),
      // don't clear the api fields we just filled.
      if (this.suppressApiClearOnce) {
        this.suppressApiClearOnce = false
        return
      }

      // Clear API fields when exchange changes, as we rely on "Saved credential"
      // to auto-fill api_key/secret_key. User must re-enter if changing exchange.
      this.$nextTick(() => {
        const fieldsToClear = {
          api_key: undefined,
          secret_key: undefined,
          passphrase: undefined,
          enable_demo_trading: false // Reset demo switch too
        }
        setTimeout(() => {
          this.form.setFieldsValue(fieldsToClear)
        }, 100)
      })
    },
    getPlaceholder (fieldType) {
      const placeholders = {
        okx: {
          api_key: '请输入API Key',
          secret_key: '请输入Secret Key',
          passphrase: '请输入Passphrase（创建API时设置）'
        },
        okex: {
          api_key: '请输入API Key',
          secret_key: '请输入Secret Key',
          passphrase: '请输入Passphrase（创建API时设置）'
        },
        binance: {
          api_key: '请输入API Key',
          secret_key: '请输入Secret Key'
        },
        coinbaseexchange: {
          api_key: '请输入API Key（或Key Name）',
          secret_key: '请输入API Secret（或Private Key）',
          passphrase: '请输入Passphrase（Legacy Pro API需要）'
        },
        kucoin: {
          api_key: '请输入API Key',
          secret_key: '请输入Secret Key',
          passphrase: '请输入Passphrase'
        },
        gate: {
          api_key: '请输入API Key',
          secret_key: '请输入Secret Key'
        },
        mexc: {
          api_key: '请输入Access Key',
          secret_key: '请输入Secret Key'
        },
        kraken: {
          api_key: '请输入API Key',
          secret_key: '请输入Secret Key'
        },
        bitfinex: {
          api_key: '请输入API Key',
          secret_key: '请输入Secret Key'
        },
        bybit: {
          api_key: '请输入API Key',
          secret_key: '请输入Secret Key'
        },
        bitget: {
          api_key: '请输入API Key',
          secret_key: '请输入Secret Key',
          passphrase: '请输入Passphrase（Legacy Pro API需要）'
        }
      }

      const exchangePlaceholders = placeholders[this.currentExchangeId] || {}
      if (exchangePlaceholders[fieldType]) {
        return exchangePlaceholders[fieldType]
      }
      // 默认占位符使用多语言
      const fieldLabels = {
        'api_key': this.$t('trading-assistant.placeholders.inputApiKey'),
        'secret_key': this.$t('trading-assistant.placeholders.inputSecretKey'),
        'passphrase': this.$t('trading-assistant.placeholders.inputPassphrase')
      }
      return fieldLabels[fieldType] || this.$t('trading-assistant.placeholders.inputApiKey')
    },
    async handleTestConnection () {
      this.testResult = null
      this.testing = true

      try {
        // IBKR uses different connection test (host/port instead of api_key/secret)
        if (this.isIBKRMarket) {
          const values = this.form.getFieldsValue(['ibkr_host', 'ibkr_port', 'ibkr_client_id', 'ibkr_account'])
          const host = values.ibkr_host || '127.0.0.1'
          const port = values.ibkr_port || 7497
          const clientId = values.ibkr_client_id || 1
          const account = values.ibkr_account || ''

          try {
            // Call IBKR connect API
            const res = await this.$http.post('/api/ibkr/connect', {
              host: host,
              port: parseInt(port),
              clientId: parseInt(clientId),
              account: account
            })

            // Note: request.js interceptor returns response.data directly, so res is the JSON object
            if (res && res.success) {
              this.testResult = {
                success: true,
                message: this.$t('trading-assistant.exchange.ibkrConnectionSuccess')
              }
              this.$message.success(this.$t('trading-assistant.exchange.ibkrConnectionSuccess'))
            } else {
              this.testResult = {
                success: false,
                message: res?.error || this.$t('trading-assistant.exchange.ibkrConnectionFailed')
              }
              this.$message.error(this.testResult.message)
            }
          } catch (error) {
            const baseError = error.response?.data?.error || error?.error || error.message || this.$t('trading-assistant.exchange.ibkrConnectionFailed')
            this.testResult = {
              success: false,
              message: `${baseError} - ${this.$t('trading-assistant.exchange.checkLocalDeployment')}`
            }
            this.$message.error(this.testResult.message)
          } finally {
            this.testing = false
          }
          return
        }

        // MT5 uses different connection test (server/login/password)
        if (this.isMT5Market) {
          const values = this.form.getFieldsValue(['mt5_server', 'mt5_login', 'mt5_password', 'mt5_terminal_path'])
          const server = values.mt5_server || ''
          const login = values.mt5_login || ''
          const password = values.mt5_password || ''
          const terminalPath = values.mt5_terminal_path || ''

          if (!server || !login || !password) {
            this.testResult = {
              success: false,
              message: this.$t('trading-assistant.exchange.fillComplete')
            }
            this.$message.error(this.testResult.message)
            this.testing = false
            return
          }

          try {
            // Call MT5 connect API
            const res = await this.$http.post('/api/mt5/connect', {
              server: server,
              login: parseInt(login),
              password: password,
              terminal_path: terminalPath
            })

            // Note: request.js interceptor returns response.data directly, so res is the JSON object
            if (res && res.success) {
              this.testResult = {
                success: true,
                message: this.$t('trading-assistant.exchange.mt5ConnectionSuccess')
              }
              this.$message.success(this.$t('trading-assistant.exchange.mt5ConnectionSuccess'))
            } else {
              this.testResult = {
                success: false,
                message: res?.error || this.$t('trading-assistant.exchange.mt5ConnectionFailed')
              }
              this.$message.error(this.testResult.message)
            }
          } catch (error) {
            const baseError = error.response?.data?.error || error?.error || error.message || this.$t('trading-assistant.exchange.mt5ConnectionFailed')
            this.testResult = {
              success: false,
              message: `${baseError} - ${this.$t('trading-assistant.exchange.checkLocalDeployment')}`
            }
            this.$message.error(this.testResult.message)
          } finally {
            this.testing = false
          }
          return
        }

        // Crypto exchanges: validate api_key/secret_key fields
        const fieldsToValidate = ['exchange_id', 'api_key', 'secret_key']
        if (this.needsPassphrase) {
          fieldsToValidate.push('passphrase')
        }

        this.form.validateFields(fieldsToValidate, async (err, values) => {
          if (err) {
            this.testing = false
            this.$message.error(this.$t('trading-assistant.exchange.fillComplete'))
            return
          }

          try {
            const marketType = (this.form.getFieldValue('market_type') || 'swap')
            const exchangeConfig = {
              exchange_id: values.exchange_id,
              api_key: values.api_key,
              secret_key: values.secret_key,
              market_type: String(marketType || 'swap'),
              enableDemoTrading: !!this.form.getFieldValue('enable_demo_trading')
            }

            if (this.needsPassphrase && values.passphrase) {
              exchangeConfig.passphrase = values.passphrase
            }

            const res = await testExchangeConnection(exchangeConfig)

            this.testResult = {
              success: res.code === 1,
              message: res.msg || (res.code === 1 ? this.$t('trading-assistant.exchange.connectionSuccess') : this.$t('trading-assistant.exchange.connectionFailed'))
            }
            this.connectionTestResult = null

            if (this.testResult.success) {
              this.$message.success(this.$t('trading-assistant.exchange.connectionSuccess'))
            } else {
              this.$message.error(this.testResult.message || this.$t('trading-assistant.exchange.testFailed'))
            }
          } catch (error) {
            this.testResult = {
              success: false,
              message: error.message || this.$t('trading-assistant.exchange.testFailed')
            }
            this.$message.error(this.testResult.message)
          } finally {
            this.testing = false
          }
        })
      } catch (error) {
        this.testResult = {
          success: false,
          message: this.$t('trading-assistant.exchange.testFailed')
        }
        this.$message.error(this.$t('trading-assistant.exchange.testFailed'))
        this.testing = false
      }
    },
    // 表单步骤控制
    handleNext () {
      if (this.currentStep === 0) {
        // Step 1: basic config (strategy name/symbol/capital/leverage/market type/timeframe)
        // 编辑模式验证 symbol，创建模式验证 selectedSymbols（多选）
        const fieldsToValidate = [
          'indicator_id',
          'strategy_name',
          'initial_capital',
          'market_type',
          'leverage',
          'trade_direction',
          'timeframe'
        ]
        // 编辑模式需要验证 symbol 字段
        if (this.isEditMode) {
          fieldsToValidate.push('symbol')
        }
        this.form.validateFields(fieldsToValidate, (err, values) => {
          if (err) return

          // 创建模式：验证多币种选择
          if (!this.isEditMode) {
            if (!this.selectedSymbols || this.selectedSymbols.length === 0) {
              this.$message.warning(this.$t('trading-assistant.validation.symbolsRequired'))
              return
            }
          }

          // Enforce spot limitations
          try {
            const marketType = (values && values.market_type) || this.form.getFieldValue('market_type')
            if (marketType === 'spot') {
              this.form.setFieldsValue({ leverage: 1, trade_direction: 'long' })
            }
          } catch (e) { }

          // Init backtest-like UI states for Step 2 (Ant Form is not reactive).
          this.backtestCollapseKeys = ['risk']
          try {
            this.trailingEnabledUi = !!this.form.getFieldValue('trailing_enabled')
          } catch (e) {
            this.trailingEnabledUi = false
          }
          this.$nextTick(() => {
            this.recalcEntryPctMaxUi()
            this.normalizeEntryPct()
          })

          this.currentStep++
        })
      } else if (this.currentStep === 1) {
        // Step 2: backtest-like configs are optional; proceed directly.
        // Sync UI states from form (Ant Form values are not always reactive)
        try {
          const execMode = this.form.getFieldValue('execution_mode') || 'signal'
          this.executionModeUi = execMode
          const chans = this.form.getFieldValue('notify_channels') || ['browser']
          this.notifyChannelsUi = Array.isArray(chans) ? chans : ['browser']
        } catch (e) { }
        this.currentStep++
      }
    },
    handlePrev () {
      if (this.currentStep > 0) {
        this.currentStep--
      }
    },
    async handleSubmit () {
      this.form.validateFields(async (err, values) => {
        if (!err) {
          try {
            this.saving = true
            const isLive = this.canUseLiveTrading && values.execution_mode === 'live'

            if (isLive) {
              const testResult = this.testResult
              if (!testResult) {
                this.$message.warning(this.$t('trading-assistant.validation.testConnectionRequired'))
                this.saving = false
                return
              }
              if (!testResult.success) {
                this.$message.warning(this.$t('trading-assistant.validation.testConnectionFailed'))
                this.saving = false
                return
              }
            }

            // Use user's notification settings from profile for targets
            const notificationConfig = {
              channels: values.notify_channels || [],
              targets: {
                email: this.userNotificationSettings.email || '',
                phone: this.userNotificationSettings.phone || '',
                telegram: this.userNotificationSettings.telegram_chat_id || '',
                telegram_bot_token: this.userNotificationSettings.telegram_bot_token || '',
                discord: this.userNotificationSettings.discord_webhook || '',
                webhook: this.userNotificationSettings.webhook_url || '',
                webhook_token: this.userNotificationSettings.webhook_token || ''
              }
            }
            if (!notificationConfig.channels || notificationConfig.channels.length === 0) {
              this.$message.warning(this.$t('trading-assistant.validation.notifyChannelRequired'))
              this.saving = false
              return
            }

            // Indicator strategy submit logic (local mode)
            const indicatorIdStr = String(values.indicator_id)
            const indicator = this.availableIndicators.find(ind => String(ind.id) === indicatorIdStr)
            if (!indicator) {
              this.$message.error(this.$t('trading-assistant.validation.indicatorRequired'))
              this.saving = false
              return
            }

            // AI filter values: source of truth is the reactive UI state to avoid rc-form edge cases.
            const enableAiFilter = !!this.aiFilterEnabledUi

            const marketType = (values.market_type === 'futures' ? 'swap' : (values.market_type || 'swap'))
            let leverage = values.leverage || 1
            let tradeDirection = values.trade_direction || 'long'

            if (marketType === 'spot') {
              leverage = 1
              tradeDirection = 'long'
              this.$message.info(this.$t('trading-assistant.messages.spotLimitations'))
            } else {
              if (leverage < 1) leverage = 1
              if (leverage > 125) leverage = 125
            }

            // 构建基础 payload
            const basePayload = {
              strategy_name: values.strategy_name,
              market_category: this.selectedMarketCategory || 'Crypto',
              execution_mode: values.execution_mode || 'signal',
              notification_config: notificationConfig,
              indicator_config: {
                indicator_id: indicator.id,
                indicator_name: indicator.name,
                indicator_code: indicator.code || ''
              },
              exchange_config: isLive ? (this.isIBKRMarket ? {
                // Broker configuration (US/HK stocks)
                exchange_id: values.broker_id || this.currentBrokerId || 'ibkr',
                // IBKR specific fields
                ibkr_host: values.ibkr_host || '127.0.0.1',
                ibkr_port: values.ibkr_port || 7497,
                ibkr_client_id: values.ibkr_client_id || 1,
                ibkr_account: values.ibkr_account || ''
              } : this.isMT5Market ? {
                // MT5/Forex broker configuration
                exchange_id: values.forex_broker_id || this.currentBrokerId || 'mt5',
                // MT5 specific fields
                mt5_server: values.mt5_server || '',
                mt5_login: values.mt5_login || '',
                mt5_password: values.mt5_password || '',
                mt5_terminal_path: values.mt5_terminal_path || ''
              } : {
                // Crypto exchange configuration
                exchange_id: values.exchange_id,
                credential_id: values.credential_id,
                api_key: values.api_key,
                secret_key: values.secret_key,
                enableDemoTrading: !!values.enable_demo_trading,
                passphrase: this.needsPassphrase ? values.passphrase : undefined
              }) : undefined,
              trading_config: {
                initial_capital: values.initial_capital,
                leverage: leverage,
                trade_direction: tradeDirection,
                timeframe: values.timeframe,
                market_type: marketType,
                // Order execution settings moved to backend env config (ORDER_MODE, MAKER_WAIT_SEC, MAKER_OFFSET_BPS)
                margin_mode: 'cross',
                signal_mode: 'confirmed',
                // Backtest-like configs
                take_profit_pct: values.take_profit_pct || 0,
                stop_loss_pct: values.stop_loss_pct || 0,
                trailing_enabled: !!values.trailing_enabled,
                trailing_stop_pct: values.trailing_stop_pct || 0,
                trailing_activation_pct: values.trailing_activation_pct || 0,
                trend_add_enabled: !!values.trend_add_enabled,
                trend_add_step_pct: values.trend_add_step_pct || 0,
                trend_add_size_pct: values.trend_add_size_pct || 0,
                trend_add_max_times: values.trend_add_max_times || 0,
                dca_add_enabled: !!values.dca_add_enabled,
                dca_add_step_pct: values.dca_add_step_pct || 0,
                dca_add_size_pct: values.dca_add_size_pct || 0,
                dca_add_max_times: values.dca_add_max_times || 0,
                trend_reduce_enabled: !!values.trend_reduce_enabled,
                trend_reduce_step_pct: values.trend_reduce_step_pct || 0,
                trend_reduce_size_pct: values.trend_reduce_size_pct || 0,
                trend_reduce_max_times: values.trend_reduce_max_times || 0,
                adverse_reduce_enabled: !!values.adverse_reduce_enabled,
                adverse_reduce_step_pct: values.adverse_reduce_step_pct || 0,
                adverse_reduce_size_pct: values.adverse_reduce_size_pct || 0,
                adverse_reduce_max_times: values.adverse_reduce_max_times || 0,
                entry_pct: (values.entry_pct === 0 || values.entry_pct) ? values.entry_pct : 100,
                commission: values.commission || 0,
                slippage: values.slippage || 0,
                // AI智能决策过滤
                enable_ai_filter: enableAiFilter,
                // 指标参数（外部传递）
                indicator_params: this.indicatorParamValues
              }
            }

            let res
            if (this.editingStrategy) {
              // 编辑模式：更新单个策略
              let parsedSymbol = values.symbol
              if (typeof parsedSymbol === 'string' && parsedSymbol.includes(':')) {
                const idx = parsedSymbol.indexOf(':')
                basePayload.market_category = parsedSymbol.slice(0, idx) || basePayload.market_category
                parsedSymbol = parsedSymbol.slice(idx + 1)
              }
              basePayload.trading_config.symbol = parsedSymbol
              res = await updateStrategy(this.editingStrategy.id, basePayload)
            } else {
              // 创建模式：批量创建策略
              basePayload.user_id = 1
              basePayload.strategy_type = 'IndicatorStrategy'
              basePayload.symbols = this.selectedSymbols // 多币种数组

              res = await batchCreateStrategies(basePayload)
            }

            if (res.code === 1) {
              if (this.isEditMode) {
                this.$message.success(this.$t('trading-assistant.messages.updateSuccess'))
              } else {
                const totalCreated = res.data?.total_created || this.selectedSymbols.length
                this.$message.success(this.$t('trading-assistant.messages.batchCreateSuccess', { count: totalCreated }))
              }
              // Save credential to vault (crypto exchanges only, IBKR/MT5 don't need this)
              if (isLive && values.save_credential && !this.isIBKRMarket && !this.isMT5Market) {
                try {
                  await createExchangeCredential({
                    user_id: 1,
                    name: values.credential_name || '',
                    exchange_id: values.exchange_id,
                    api_key: values.api_key,
                    secret_key: values.secret_key,
                    passphrase: values.passphrase || ''
                  })
                  this.loadExchangeCredentials()
                } catch (e) {
                  // Silent fail: vault is optional.
                }
              }
              this.handleRefresh()
            } else {
              this.$message.error(res.msg || (this.isEditMode ? this.$t('trading-assistant.messages.updateFailed') : this.$t('trading-assistant.messages.createFailed')))
            }
          } catch (error) {
            this.$message.error(this.isEditMode ? this.$t('trading-assistant.messages.updateFailed') : this.$t('trading-assistant.messages.createFailed'))
          } finally {
            this.saving = false
          }
        }
      })
    },
    getFormValues () {
      return new Promise((resolve, reject) => {
        this.form.validateFields((err, values) => {
          if (err) {
            reject(err)
          } else {
            resolve(values)
          }
        })
      })
    },
    getDropdownContainer (triggerNode) {
      // 始终将下拉菜单挂载到body，避免被父容器裁剪
      return document.body
    }
  }
}
</script>

<style lang="less" scoped>
// 主色调变量
@primary-color: #1890ff;
@primary-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
@success-color: #0ecb81;
@danger-color: #f6465d;
@warning-color: #f0b90b;
@card-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
@card-shadow-hover: 0 8px 32px rgba(0, 0, 0, 0.12);
@border-radius-lg: 16px;
@border-radius-md: 12px;
@border-radius-sm: 8px;

.trading-assistant {
  padding: 0px;
  height: calc(100vh - 120px);
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);

  .strategy-layout {
    height: calc(100vh - 120px);
  }

  // 移动端适配
  @media (max-width: 768px) {
    min-height: auto;
    margin: -24px;

    .strategy-layout {
      height: auto;
      min-height: calc(100vh - 120px);
    }

    .strategy-list-col {
      margin-bottom: 12px;
      height: auto;
      max-height: 50vh;

      .strategy-list-card {
        height: auto;
        max-height: 50vh;

        .card-title {
          flex-wrap: wrap;
          gap: 8px;
          padding: 12px 16px;

          span {
            font-size: 14px;
            font-weight: 600;
          }

          .ant-btn {
            font-size: 12px;
            padding: 0 10px;
            height: 28px;
            line-height: 28px;
          }
        }

        /deep/ .ant-card-body {
          max-height: calc(50vh - 60px);
          overflow-y: auto;
          padding: 8px;
          -webkit-overflow-scrolling: touch;
        }

        /deep/ .ant-card-head {
          padding: 0;
          min-height: 48px;
        }

        .strategy-list-item {
          padding: 12px 8px;
          margin-bottom: 4px;
          border-radius: 8px;

          /deep/ .ant-list-item-meta {
            width: 100%;
          }

          /deep/ .ant-list-item-action {
            margin-left: 8px;
          }

          .strategy-item-header {
            width: 100%;

            .strategy-name-wrapper {
              width: 100%;
              display: flex;
              align-items: center;
              gap: 6px;
              margin-bottom: 6px;
              flex-wrap: wrap;

              .strategy-type-tag {
                font-size: 10px;
                padding: 2px 6px;
                line-height: 1.4;
                margin: 0;
              }

              .exchange-tag {
                font-size: 10px;
                padding: 2px 6px;
                line-height: 1.4;
                margin: 0;

                .anticon {
                  font-size: 10px;
                  margin-right: 2px;
                }
              }

              .strategy-name {
                font-size: 14px;
                font-weight: 600;
                flex: 1;
                min-width: 0;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
              }
            }
          }

          /deep/ .ant-list-item-meta-description {
            .strategy-item-info {
              display: flex !important;
              flex-direction: row;
              align-items: center;
              gap: 6px;
              margin-top: 4px;
              font-size: 11px;
              flex-wrap: wrap;

              .info-item {
                display: flex;
                align-items: center;
                gap: 3px;
                flex-shrink: 0;
                font-size: 11px;

                .anticon {
                  font-size: 11px;
                }
              }

              .status-label {
                font-size: 10px;
                padding: 2px 6px;
                line-height: 1.4;
              }
            }
          }
        }
      }
    }

    .strategy-detail-col {
      height: auto;
      min-height: calc(50vh - 60px);

      .strategy-detail-panel {
        gap: 12px;

        .strategy-header-card {
          /deep/ .ant-card-body {
            padding: 16px 12px;
          }

          /deep/ .ant-card-head {
            padding: 0;
          }

          .strategy-header {
            flex-direction: column;
            gap: 12px;

            .header-left {
              width: 100%;

              .strategy-title {
                font-size: 18px;
                font-weight: 600;
                margin-bottom: 12px;
                line-height: 1.4;
                word-break: break-word;
              }

              .strategy-meta {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 8px;
                align-items: start;

                /deep/ .ant-tag {
                  grid-column: 1 / -1;
                  justify-self: start;
                  margin: 0;
                  font-size: 11px;
                  padding: 4px 8px;
                }

                .meta-item {
                  display: flex;
                  align-items: flex-start;
                  gap: 4px;
                  font-size: 12px;
                  line-height: 1.5;
                  word-break: break-word;

                  .anticon {
                    font-size: 12px;
                    flex-shrink: 0;
                    margin-top: 2px;
                  }

                  // 确保文本可换行
                  &>span {
                    word-break: break-word;
                    line-height: 1.5;
                    flex: 1;
                  }

                  // 对于包含数值的span
                  span:not(.anticon) {
                    display: inline;
                    word-break: break-word;
                    overflow-wrap: break-word;
                  }
                }

                // 如果参数过多，使用单列布局
                @media (max-width: 480px) {
                  grid-template-columns: 1fr;

                  /deep/ .ant-tag {
                    grid-column: 1;
                  }
                }
              }
            }

            .header-right {
              width: 100%;
              display: flex;
              justify-content: flex-start;
              gap: 8px;
              flex-wrap: wrap;

              .ant-btn {
                flex: 1;
                min-width: 100px;
                font-size: 13px;
                padding: 0 12px;
                height: 36px;
                line-height: 36px;

                .anticon {
                  margin-right: 4px;
                }
              }
            }
          }
        }

        .strategy-content-card {
          /deep/ .ant-card-body {
            padding: 12px 8px;
            overflow-x: hidden;
          }

          /deep/ .ant-card-head {
            padding: 0 8px;
          }

          /deep/ .ant-tabs {
            .ant-tabs-nav {
              padding: 0 4px;

              .ant-tabs-tab {
                font-size: 13px;
                padding: 8px 10px;
                margin: 0 2px;
                white-space: nowrap;
              }
            }

            .ant-tabs-content {
              padding-top: 12px;
              overflow-x: hidden;

              .ant-tabs-tabpane {
                overflow-x: auto;
                -webkit-overflow-scrolling: touch;
              }
            }
          }
        }
      }
    }
  }

  // 超小屏幕适配
  @media (max-width: 480px) {
    .strategy-list-col {
      max-height: 45vh;

      .strategy-list-card {
        max-height: 45vh;

        /deep/ .ant-card-body {
          max-height: calc(45vh - 60px);
        }
      }
    }

    .strategy-detail-col {
      .strategy-detail-panel {
        .strategy-header-card {
          .strategy-header {
            .header-left {
              .strategy-meta {
                grid-template-columns: 1fr;
                gap: 6px;

                .meta-item {
                  font-size: 11px;
                  line-height: 1.6;
                }
              }
            }

            .header-right {
              .ant-btn {
                width: 100%;
                flex: none;
              }
            }
          }
        }
      }
    }
  }

  .strategy-list-col {
    height: 100%;

    .strategy-list-card {
      height: 100%;
      display: flex;
      flex-direction: column;
      border-radius: @border-radius-lg;
      box-shadow: @card-shadow;
      border: none;
      overflow: hidden;
      transition: box-shadow 0.3s ease;

      &:hover {
        box-shadow: @card-shadow-hover;
      }

      .card-title {
        display: flex;
        justify-content: space-between;
        align-items: center;

        span {
          font-size: 16px;
          font-weight: 700;
          background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
        }

        .ant-btn-primary {
          border-radius: @border-radius-sm;
          background: linear-gradient(135deg, @primary-color 0%, #40a9ff 100%);
          border: none;
          box-shadow: 0 4px 12px rgba(24, 144, 255, 0.35);
          transition: all 0.3s ease;

          &:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(24, 144, 255, 0.45);
          }
        }
      }

      // 分组模式切换
      .group-mode-switch {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 0 12px;
        border-bottom: 1px solid #f0f0f0;
        margin-bottom: 12px;

        .group-mode-label {
          font-size: 13px;
          color: #8c8c8c;
          font-weight: 500;
        }

        /deep/ .ant-radio-group {
          .ant-radio-button-wrapper {
            font-size: 12px;
            padding: 0 10px;
            height: 26px;
            line-height: 24px;
            border-radius: 4px;

            &:first-child {
              border-radius: 4px 0 0 4px;
            }

            &:last-child {
              border-radius: 0 4px 4px 0;
            }

            .anticon {
              margin-right: 4px;
            }
          }
        }
      }

      /deep/ .ant-card-body {
        flex: 1;
        overflow-y: auto;
        background: #fff;
        padding: 12px;
      }

      /deep/ .ant-card-head {
        background: linear-gradient(180deg, #fff 0%, #fafbfc 100%);
        border-bottom: 1px solid #f0f0f0;
      }

      // 策略分组列表
      .strategy-grouped-list {
        .strategy-group {
          margin-bottom: 12px;
          background: #fff;
          border-radius: @border-radius-md;
          border: 1px solid #e8ecf1;
          overflow: hidden;

          .strategy-group-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 12px;
            background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
            cursor: pointer;
            transition: all 0.2s ease;

            &:hover {
              background: linear-gradient(135deg, #e8f4fd 0%, #e3f0fc 100%);
            }

            .group-header-left {
              display: flex;
              align-items: center;
              gap: 8px;
              flex: 1;
              min-width: 0;

              .collapse-icon {
                font-size: 12px;
                color: #8c8c8c;
                transition: transform 0.2s ease;
              }

              .group-icon {
                font-size: 16px;
                color: @primary-color;
              }

              .group-name {
                font-weight: 600;
                font-size: 14px;
                color: #1e3a5f;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
              }
            }

            .group-header-right {
              display: flex;
              align-items: center;
              gap: 8px;

              .group-status {
                font-size: 11px;
                padding: 2px 8px;
                border-radius: 10px;

                &.running {
                  background: rgba(14, 203, 129, 0.1);
                  color: @success-color;
                }

                &.stopped {
                  background: rgba(246, 70, 93, 0.1);
                  color: @danger-color;
                }
              }
            }
          }

          .strategy-group-content {
            padding: 4px 8px 8px;

            .strategy-list-item {
              display: flex;
              justify-content: space-between;
              align-items: center;
              padding: 8px 10px;
              margin-bottom: 4px;
              margin-left: 20px;
              border-left: 2px solid #e8ecf1;
              background: #fafbfc;
              border-radius: 0 @border-radius-sm @border-radius-sm 0;

              &:last-child {
                margin-bottom: 0;
              }

              &:hover {
                background: #f0f7ff;
                border-left-color: @primary-color;
              }

              &.active {
                background: #e6f4ff;
                border-left-color: @primary-color;
                border-left-width: 3px;
              }

              .strategy-item-content {
                flex: 1;
                min-width: 0;
              }

              .strategy-item-actions {
                flex-shrink: 0;
              }
            }
          }
        }
      }

      .strategy-list-item {
        cursor: pointer;
        padding: 14px 16px;
        border-radius: @border-radius-md;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        position: relative;
        margin-bottom: 8px;
        background: #fafbfc;
        border: 1px solid transparent;

        &:hover {
          background: linear-gradient(135deg, #f0f7ff 0%, #f5f9ff 100%);
          border-color: rgba(24, 144, 255, 0.2);
          transform: translateX(4px);
          box-shadow: 0 2px 12px rgba(24, 144, 255, 0.1);
        }

        &.active {
          background: linear-gradient(135deg, #e6f4ff 0%, #f0f9ff 100%);
          border-color: @primary-color;
          border-left: 4px solid @primary-color;
          box-shadow: 0 4px 16px rgba(24, 144, 255, 0.15);
        }

        // 移动端优化点击区域
        @media (max-width: 768px) {
          padding: 12px 8px;
          margin: 0 4px 4px 4px;

          &.active {
            border-left-width: 2px;
          }
        }

        .strategy-item-header {
          display: flex;
          justify-content: space-between;
          align-items: center;

          .strategy-name-wrapper {
            display: flex;
            align-items: center;
            gap: 10px;
            flex: 1;
            min-width: 0;

            .strategy-name {
              font-weight: 600;
              font-size: 14px;
              flex-shrink: 0;
              color: #1e3a5f;
              transition: color 0.2s ease;
            }

            .exchange-tag {
              flex-shrink: 0;
              display: inline-flex;
              align-items: center;
              font-size: 11px;
              line-height: 1.5;
              padding: 2px 8px;
              border-radius: 6px;
              background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
              border: 1px solid rgba(102, 126, 234, 0.2);
              color: #667eea;
              transition: all 0.2s ease;

              .anticon {
                font-size: 11px;
              }
            }

            .strategy-type-tag {
              flex-shrink: 0;
              display: inline-flex;
              align-items: center;
              font-size: 10px;
              line-height: 1.5;
              margin-left: 4px;
              padding: 2px 8px;
              border-radius: 6px;
              background: linear-gradient(135deg, rgba(156, 39, 176, 0.1) 0%, rgba(103, 58, 183, 0.1) 100%);
              border: 1px solid rgba(156, 39, 176, 0.2);

              .anticon {
                font-size: 10px;
                margin-right: 3px;
              }
            }
          }

          /deep/ .status-stopped {
            color: @danger-color !important;
            border-color: @danger-color !important;
          }
        }

        /deep/ .ant-list-item-meta-description {
          max-width: calc(100% - 20px); // 留出空间给右侧操作按钮和选中边框
          overflow: hidden;

          .strategy-item-info {
            display: flex !important;
            gap: 12px; // 减小间距
            margin-top: 8px;
            font-size: 12px;
            color: var(--text-color-secondary, #8c8c8c);
            align-items: center;
            flex-wrap: nowrap; // 禁止换行
            max-width: 100%;
            overflow: hidden;

            .status-label {
              display: inline-flex;
              align-items: center;
              gap: 6px;
              padding: 4px 12px;
              border-radius: 16px;
              font-size: 11px;
              font-weight: 600;
              line-height: 1;
              border: 1px solid transparent;
              flex-shrink: 0;
              background: linear-gradient(135deg, #f0f2f5 0%, #e8eaed 100%);
              color: #595959;
              transition: all 0.2s ease;

              &::before {
                content: '';
                width: 6px;
                height: 6px;
                border-radius: 50%;
                background: currentColor;
              }
            }

            .status-running {
              background: linear-gradient(135deg, rgba(14, 203, 129, 0.15) 0%, rgba(14, 203, 129, 0.08) 100%);
              color: @success-color;
              border-color: rgba(14, 203, 129, 0.3);
              box-shadow: 0 2px 8px rgba(14, 203, 129, 0.2);

              &::before {
                animation: statusPulse 2s infinite;
                box-shadow: 0 0 8px @success-color;
              }
            }

            .status-stopped {
              background: linear-gradient(135deg, rgba(246, 70, 93, 0.15) 0%, rgba(246, 70, 93, 0.08) 100%);
              color: @danger-color;
              border-color: rgba(246, 70, 93, 0.3);
            }

            .status-error {
              background: linear-gradient(135deg, rgba(255, 77, 79, 0.15) 0%, rgba(255, 77, 79, 0.08) 100%);
              color: #ff4d4f;
              border-color: rgba(255, 77, 79, 0.3);
            }

            @keyframes statusPulse {

              0%,
              100% {
                opacity: 1;
              }

              50% {
                opacity: 0.5;
              }
            }

            .info-item {
              display: flex;
              align-items: center;
              gap: 4px;
              flex-shrink: 1;
              min-width: 0;
              overflow: hidden;
              text-overflow: ellipsis;
              white-space: nowrap;

              &.strategy-name-text {
                font-weight: 500;
                color: #1e3a5f;
                max-width: 120px;
              }
            }

            /deep/ .ant-tag {
              margin-right: 0;
              font-size: 11px;
              line-height: 18px;
              padding: 0 6px;
            }
          }
        }
      }
    }
  }

  .strategy-detail-col {
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow-y: auto;

    .empty-detail {
      height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(135deg, rgba(255, 255, 255, 0.8) 0%, rgba(248, 250, 252, 0.9) 100%);
      border-radius: @border-radius-lg;
      border: 2px dashed #e0e6ed;
      transition: all 0.3s ease;

      &:hover {
        border-color: @primary-color;
        background: linear-gradient(135deg, rgba(24, 144, 255, 0.02) 0%, rgba(24, 144, 255, 0.05) 100%);
      }

      /deep/ .ant-empty-image {
        opacity: 0.6;
      }

      /deep/ .ant-empty-description {
        color: #8c8c8c;
        font-size: 14px;
      }
    }

    .strategy-detail-panel {
      display: flex;
      flex-direction: column;
      gap: 16px;
      min-height: 100%;

      .strategy-header-card {
        flex-shrink: 0; // 防止头部被压缩
        background: linear-gradient(135deg, #fff 0%, #f8fafc 100%);
        border: none;
        border-radius: @border-radius-lg;
        box-shadow: @card-shadow;
        transition: all 0.3s ease;

        &:hover {
          box-shadow: @card-shadow-hover;
        }

        /deep/ .ant-card-head {
          background: transparent;
          border-bottom: none;
        }

        /deep/ .ant-card-body {
          background: transparent;
          padding: 20px;
        }

        .strategy-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          gap: 24px;

          .header-left {
            flex: 1;
            min-width: 0;

            .strategy-title-row {
              display: flex;
              align-items: center;
              gap: 12px;
              margin-bottom: 16px;
              flex-wrap: wrap;

              .strategy-title {
                font-size: 20px;
                font-weight: 700;
                margin: 0;
                background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
              }

              .status-badge {
                display: inline-flex;
                align-items: center;
                gap: 8px;
                padding: 6px 14px;
                border-radius: 20px;
                font-size: 13px;
                font-weight: 600;
                transition: all 0.3s ease;

                .status-dot {
                  width: 8px;
                  height: 8px;
                  border-radius: 50%;
                  animation: pulse 2s infinite;
                }

                &.status-running {
                  background: linear-gradient(135deg, rgba(14, 203, 129, 0.15) 0%, rgba(14, 203, 129, 0.08) 100%);
                  color: @success-color;
                  border: 1px solid rgba(14, 203, 129, 0.3);

                  .status-dot {
                    background: @success-color;
                    box-shadow: 0 0 12px @success-color;
                  }
                }

                &.status-stopped {
                  background: linear-gradient(135deg, rgba(246, 70, 93, 0.15) 0%, rgba(246, 70, 93, 0.08) 100%);
                  color: @danger-color;
                  border: 1px solid rgba(246, 70, 93, 0.3);

                  .status-dot {
                    background: @danger-color;
                    animation: none;
                  }
                }

                &.status-error {
                  background: linear-gradient(135deg, rgba(255, 77, 79, 0.15) 0%, rgba(255, 77, 79, 0.08) 100%);
                  color: #ff4d4f;
                  border: 1px solid rgba(255, 77, 79, 0.3);

                  .status-dot {
                    background: #ff4d4f;
                    animation: none;
                  }
                }
              }
            }

            // 关键数据卡片网格
            .key-stats-grid {
              display: flex;
              flex-wrap: wrap;
              gap: 12px;
              margin-bottom: 14px;

              .stat-card {
                display: flex;
                align-items: center;
                gap: 10px;
                padding: 10px 14px;
                background: #fff;
                border-radius: @border-radius-sm;
                border: 1px solid #f0f0f0;
                transition: all 0.2s ease;

                &:hover {
                  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
                }

                .stat-icon {
                  width: 36px;
                  height: 36px;
                  border-radius: 8px;
                  display: flex;
                  align-items: center;
                  justify-content: center;
                  font-size: 16px;
                  flex-shrink: 0;

                  &.investment {
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: #fff;
                  }

                  &.equity {
                    background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
                    color: #fff;
                  }

                  &.pnl {
                    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                    color: #fff;
                  }
                }

                .stat-content {
                  flex: 1;
                  min-width: 0;

                  .stat-label {
                    font-size: 11px;
                    color: #8c8c8c;
                    margin-bottom: 2px;
                  }

                  .stat-value {
                    font-size: 15px;
                    font-weight: 700;
                    color: #1e3a5f;
                    line-height: 1.2;

                    .pnl-percent {
                      font-size: 12px;
                      font-weight: 500;
                      opacity: 0.8;
                    }
                  }
                }

                &.pnl-card {
                  &.profit .stat-content .stat-value {
                    color: @success-color;
                  }

                  &.loss .stat-content .stat-value {
                    color: @danger-color;
                  }
                }
              }
            }

            // 策略标签
            .strategy-tags {
              display: flex;
              flex-wrap: wrap;
              gap: 8px;

              .tag-item {
                display: inline-flex;
                align-items: center;
                gap: 4px;
                padding: 4px 10px;
                background: #f5f7fa;
                border-radius: 14px;
                font-size: 12px;
                color: #5a6872;
                border: 1px solid #e8ecf1;

                .anticon {
                  font-size: 12px;
                  color: @primary-color;
                }
              }
            }
          }

          .header-right {
            flex-shrink: 0;

            .action-btn {
              min-width: 120px;
              height: 38px;
              border-radius: @border-radius-sm;
              font-size: 14px;
              font-weight: 600;
              display: flex;
              align-items: center;
              justify-content: center;
              gap: 6px;
              transition: all 0.2s ease;

              .anticon {
                font-size: 16px;
              }

              &.start-btn {
                background: linear-gradient(135deg, @success-color 0%, #26d87d 100%);
                border: none;
                box-shadow: 0 2px 8px rgba(14, 203, 129, 0.3);

                &:hover {
                  box-shadow: 0 4px 12px rgba(14, 203, 129, 0.4);
                }
              }

              &.stop-btn {
                background: linear-gradient(135deg, @danger-color 0%, #ff6b7a 100%);
                border: none;
                box-shadow: 0 2px 8px rgba(246, 70, 93, 0.3);

                &:hover {
                  box-shadow: 0 4px 12px rgba(246, 70, 93, 0.4);
                }
              }
            }
          }
        }
      }

      @keyframes pulse {

        0%,
        100% {
          opacity: 1;
          transform: scale(1);
        }

        50% {
          opacity: 0.6;
          transform: scale(1.1);
        }
      }

      .strategy-content-card {
        flex: 1;
        display: flex;
        flex-direction: column;
        background: #fff;
        border: none;
        border-radius: @border-radius-lg;
        box-shadow: @card-shadow;
        transition: all 0.3s ease;
        min-height: 400px; // 确保有足够的最小高度

        &:hover {
          box-shadow: @card-shadow-hover;
        }

        /deep/ .ant-card-head {
          background: linear-gradient(180deg, #fafbfc 0%, #fff 100%);
          border-bottom: 1px solid #f0f0f0;
          flex-shrink: 0;
        }

        /deep/ .ant-card-body {
          flex: 1;
          display: flex;
          flex-direction: column;
          padding: 16px;
          background: #fff;

          .ant-tabs {
            flex: 1;
            display: flex;
            flex-direction: column;

            .ant-tabs-bar {
              flex-shrink: 0;
            }

            .ant-tabs-content {
              flex: 1;
            }

            .ant-tabs-tabpane {

              .trading-records,
              .position-records {
                width: 100%;
              }
            }
          }
        }
      }
    }
  }

  &.theme-dark {
    background: linear-gradient(180deg, #0d1117 0%, #161b22 100%);
    color: var(--dark-text-color, #fff);

    // 左侧策略列表卡片
    .strategy-list-col {
      .strategy-list-card {
        background: linear-gradient(180deg, #1e222d 0%, #1a1e28 100%);
        border: 1px solid rgba(255, 255, 255, 0.06);
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.25);

        .card-title span {
          background: linear-gradient(135deg, #e0e6ed 0%, #c5ccd6 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
        }

        /deep/ .ant-card-head {
          background: linear-gradient(180deg, #252a36 0%, #1e222d 100%);
          border-bottom-color: rgba(255, 255, 255, 0.06);

          .ant-card-head-title {
            color: #d1d4dc;
          }
        }

        /deep/ .ant-card-body {
          background: transparent;
        }

        /deep/ .ant-empty-description {
          color: #868993;
        }

        /deep/ .ant-list {
          .ant-list-item {
            border-bottom-color: rgba(255, 255, 255, 0.06);

            .ant-list-item-meta-title {
              color: #d1d4dc;
            }

            .ant-list-item-meta-description {
              color: #868993;
            }
          }
        }
      }

      .strategy-list-item {
        background: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.04);

        &:hover {
          background: linear-gradient(135deg, rgba(24, 144, 255, 0.08) 0%, rgba(24, 144, 255, 0.04) 100%);
          border-color: rgba(24, 144, 255, 0.2);
        }

        &.active {
          background: linear-gradient(135deg, rgba(24, 144, 255, 0.12) 0%, rgba(24, 144, 255, 0.06) 100%);
          border-color: @primary-color;
          box-shadow: 0 4px 20px rgba(24, 144, 255, 0.2);
        }

        .strategy-name {
          color: #e0e6ed;
        }

        .strategy-item-info {
          color: #868993;
        }
      }
    }

    // 右侧策略详情卡片
    .strategy-detail-col {
      .strategy-header-card {
        background: linear-gradient(135deg, #1e222d 0%, #1a1e28 100%);
        border: 1px solid rgba(255, 255, 255, 0.06);
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.25);

        /deep/ .ant-card-head {
          background: transparent;
          border-bottom: none;
        }

        /deep/ .ant-card-body {
          background: transparent;
        }

        .strategy-title-row {
          .strategy-title {
            background: linear-gradient(135deg, #e0e6ed 0%, #c5ccd6 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
          }
        }

        .key-stats-grid {
          .stat-card {
            background: rgba(255, 255, 255, 0.03);
            border-color: rgba(255, 255, 255, 0.06);

            &:hover {
              background: rgba(255, 255, 255, 0.06);
              border-color: rgba(255, 255, 255, 0.1);
            }

            .stat-content {
              .stat-label {
                color: #868993;
              }

              .stat-value {
                color: #e0e6ed;
              }
            }
          }
        }

        .strategy-tags {
          .tag-item {
            background: rgba(255, 255, 255, 0.04);
            border-color: rgba(255, 255, 255, 0.08);
            color: #a0a8b3;

            &:hover {
              background: rgba(24, 144, 255, 0.1);
              border-color: rgba(24, 144, 255, 0.3);
            }
          }
        }
      }

      .strategy-content-card {
        background: linear-gradient(180deg, #1e222d 0%, #1a1e28 100%);
        border: 1px solid rgba(255, 255, 255, 0.06);
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.25);

        /deep/ .ant-card-head {
          background: rgba(255, 255, 255, 0.02);
          border-bottom-color: rgba(255, 255, 255, 0.06);

          .ant-card-head-title {
            color: #d1d4dc;
          }
        }

        /deep/ .ant-card-body {
          background: transparent;
        }

        /deep/ .ant-tabs {
          .ant-tabs-nav {
            .ant-tabs-tab {
              color: #868993;

              &:hover {
                color: #d1d4dc;
              }

              &.ant-tabs-tab-active {
                .ant-tabs-tab-btn {
                  color: #1890ff;
                }
              }
            }

            .ant-tabs-ink-bar {
              background: linear-gradient(90deg, @primary-color 0%, #40a9ff 100%);
            }
          }

          .ant-tabs-content {
            color: #d1d4dc;
          }
        }

        /deep/ .ant-empty-description {
          color: #868993;
        }
      }
    }

    // 空状态
    .empty-detail {
      /deep/ .ant-empty-description {
        color: #868993;
      }
    }
  }
}

/* AI filter box (Step 2) */
.ai-filter-box {
  margin-top: 12px;
  padding: 14px 14px 12px;
  border: 1px solid #e8e8e8;
  border-radius: 10px;
  background: linear-gradient(180deg, #fafcff 0%, #ffffff 100%);
}

.ai-filter-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.ai-filter-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #262626;
}

.ai-filter-title .anticon {
  color: #1890ff;
}

.ai-filter-hint {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.5;
  color: #8c8c8c;
}

.symbol-option {
  display: flex;
  align-items: center;
}

.symbol-name {
  font-weight: 600;
  color: #8f8d8d;
  margin-right: 8px;
}

.symbol-name-extra {
  font-size: 12px;
  color: #999;
  margin-left: 4px;
}

// 弹窗样式
.steps-container {
  margin-bottom: 24px;

  @media (max-width: 768px) {
    margin-bottom: 16px;

    /deep/ .ant-steps-item-title {
      font-size: 12px;
    }

    /deep/ .ant-steps-item-icon {
      width: 24px;
      height: 24px;
      line-height: 24px;
      font-size: 12px;
    }
  }
}

.form-container {
  min-height: 400px;
  padding: 24px 0;

  .step-content {
    animation: fadeIn 0.3s;
  }

  @media (max-width: 768px) {
    min-height: 300px;
    padding: 16px 0;

    /deep/ .ant-form-item-label {
      padding-bottom: 4px;

      label {
        font-size: 13px;
      }
    }

    /deep/ .ant-input,
    /deep/ .ant-input-number,
    /deep/ .ant-select {
      font-size: 14px;
    }

    /deep/ .ant-radio-group {
      display: flex;
      flex-direction: column;
      gap: 8px;

      .ant-radio-wrapper {
        font-size: 13px;
      }
    }
  }

  @media (max-width: 480px) {
    min-height: 250px;
    padding: 12px 0;

    /deep/ .ant-form-item-label label {
      font-size: 12px;
    }

    /deep/ .ant-input,
    /deep/ .ant-input-number,
    /deep/ .ant-select {
      font-size: 13px;
    }
  }
}

.strategy-type-selector {
  padding: 16px 0;

  .market-category-selector {
    margin-bottom: 16px;

    .selector-label {
      font-weight: 600;
      margin-bottom: 8px;
      color: #262626;
    }

    /deep/ .ant-radio-group {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
  }

  .strategy-type-card {
    cursor: pointer;
    transition: all 0.3s;
    height: 100%;
    min-height: 180px;
    display: flex;
    align-items: center;
    justify-content: center;

    &:hover {
      border-color: #1890ff;
      box-shadow: 0 2px 8px rgba(24, 144, 255, 0.2);
    }

    &.selected {
      border-color: #1890ff;
      background-color: #e6f7ff;
      box-shadow: 0 2px 8px rgba(24, 144, 255, 0.3);
    }

    .strategy-type-content {
      text-align: center;
      padding: 16px;

      .strategy-type-icon {
        font-size: 48px;
        color: #1890ff;
        margin-bottom: 16px;
      }

      h3 {
        font-size: 18px;
        font-weight: 600;
        margin-bottom: 8px;
        color: #1f1f1f;
      }

      p {
        font-size: 14px;
        color: #8c8c8c;
        margin: 0;
        line-height: 1.6;
      }
    }
  }
}

.indicator-option {
  display: flex;
  justify-content: space-between;
  align-items: center;

  .indicator-name {
    flex: 1;
  }
}

.indicator-description {
  padding: 12px;
  background-color: var(--bg-color-secondary, #f5f5f5);
  border-radius: 4px;
  color: var(--text-color, #666);
  font-size: 14px;
  line-height: 1.6;
}

.indicator-params-form {
  padding: 12px;
  background-color: var(--bg-color-secondary, #f5f7fa);
  border-radius: 6px;
  border: 1px dashed var(--border-color, #e0e0e0);
}

.indicator-params-form .param-item {
  margin-bottom: 12px;
}

.indicator-params-form .param-label {
  display: block;
  font-size: 13px;
  color: var(--text-color, #666);
  margin-bottom: 4px;
  font-weight: 500;
}

.form-item-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-color-secondary, #8c8c8c);
}

.test-result {
  margin-top: 8px;
  padding: 8px;
  border-radius: 4px;
  font-size: 14px;

  &.success {
    background-color: #f6ffed;
    border: 1px solid #b7eb8f;
    color: #52c41a;
  }
}

.ip-whitelist-tip {
  margin-top: 12px;
  padding: 12px;
  background-color: #e6f7ff;
  border: 1px solid #91d5ff;
  border-radius: 4px;
  font-size: 13px;
  color: #1890ff;
  line-height: 1.6;

  .anticon {
    margin-right: 6px;
    color: #1890ff;
  }

  .ip-list {
    margin-top: 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;

    .ant-tag {
      margin: 0;
      font-family: 'Courier New', monospace;
      font-size: 12px;
    }
  }

  &.error {
    background-color: #fff2f0;
    border: 1px solid #ffccc7;
    color: #ff4d4f;
  }
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/deep/ .danger-item {
  color: #ff4d4f;
}

// 移动端弹窗样式
/deep/ .mobile-modal {
  .ant-modal {
    top: 20px;
    padding-bottom: 0;
  }

  .ant-modal-content {
    max-height: calc(100vh - 40px);
    display: flex;
    flex-direction: column;
  }

  .ant-modal-body {
    flex: 1;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    padding: 16px;
  }

  .ant-modal-footer {
    padding: 12px 16px;
    border-top: 1px solid #e8e8e8;
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    flex-wrap: wrap;

    .ant-btn {
      font-size: 13px;
      padding: 0 12px;
      height: 32px;
    }
  }
}

// 添加交易对弹窗样式
.add-symbol-modal-content {
  .market-tabs {
    margin-bottom: 16px;
  }

  .symbol-search-section {
    margin-bottom: 16px;
  }

  .section-title {
    font-weight: 500;
    margin-bottom: 8px;
    color: rgba(0, 0, 0, 0.85);
    display: flex;
    align-items: center;
  }

  .search-results-section,
  .hot-symbols-section {
    margin-bottom: 16px;
  }

  .symbol-list {
    .symbol-list-item {
      cursor: pointer;
      transition: background-color 0.3s;
      padding: 8px 12px;
      border-radius: 4px;

      &:hover {
        background-color: #f5f5f5;
      }
    }
  }

  .symbol-item-content {
    display: flex;
    align-items: center;

    .symbol-code {
      font-weight: 500;
      margin-right: 8px;
    }

    .symbol-name {
      color: rgba(0, 0, 0, 0.45);
    }
  }

  .selected-symbol-section {
    padding: 12px;
    background-color: #f6ffed;
    border: 1px solid #b7eb8f;
    border-radius: 4px;
    margin-top: 16px;

    .selected-symbol-info {
      display: flex;
      align-items: center;
      margin-top: 8px;

      .symbol-code {
        font-weight: 500;
        margin-right: 8px;
      }

      .symbol-name {
        color: rgba(0, 0, 0, 0.45);
      }
    }
  }
}
</style>
