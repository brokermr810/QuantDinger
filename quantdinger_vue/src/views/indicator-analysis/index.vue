<template>
  <div class="chart-container" :class="{ 'theme-dark': isDarkTheme }">
    <div class="chart-header">
      <div class="header-top">
        <div class="header-left">
          <div class="search-section">
            <a-select
              v-model="searchSymbol"
              show-search
              :placeholder="$t('dashboard.indicator.selectSymbol')"
              class="symbol-select"
              dropdownClassName="dark-dropdown"
              :filter-option="filterSymbolOption"
              :not-found-content="null"
              :open="symbolSearchOpen"
              @search="handleSymbolSearch"
              @change="handleSymbolSelect"
              @dropdownVisibleChange="handleDropdownVisibleChange"
            >
              <a-icon slot="suffixIcon" type="search" style="color: #999" />
              <a-select-option
                v-for="item in symbolSuggestions"
                :key="item.value"
                :value="item.value"
              >
                <div class="symbol-option">
                  <a-tag :color="getMarketColor(item.market)" style="margin-right: 8px; margin-bottom: 0;">
                    {{ getMarketName(item.market) }}
                  </a-tag>
                  <span class="symbol-name">{{ item.symbol }}</span>
                  <span v-if="item.name" class="symbol-name-extra">{{ item.name }}</span>
                </div>
              </a-select-option>
              <a-select-option
                key="add-stock-option"
                value="__add_stock_option__"
                class="add-stock-option"
              >
                <div style="width: 100%; text-align: center; padding: 4px 0; color: #1890ff; cursor: pointer;">
                  <a-icon type="plus" style="margin-right: 4px;" />
                  <span>{{ $t('dashboard.analysis.watchlist.add') }}</span>
                </div>
              </a-select-option>
            </a-select>
          </div>

          <div class="timeframe-group">
            <div
              v-for="tf in ['1m','5m','15m','30m','1H','4H','1D','1W']"
              :key="tf"
              class="timeframe-item"
              :class="{ active: timeframe === tf }"
              @click="setTimeframe(tf)"
            >
              {{ tf }}
            </div>
          </div>
        </div>

        <div class="current-symbol" v-if="currentSymbol">
          <div class="symbol-info">
            <span class="symbol-label">{{ currentSymbol }}</span>
            <span class="market-tag">{{ currentMarket }}</span>
          </div>
          <div class="price-info" :class="priceChangeClass">
            <span class="symbol-price">{{ currentPrice }}</span>
            <span class="symbol-change">
              {{ priceChange > 0 ? '+' : '' }}{{ priceChange.toFixed(2) }}%
            </span>
          </div>
        </div>
      </div>
    </div>

    <div class="chart-content">
      <div class="chart-main-row">
        <!-- 手机端：币种和价格信息显示在K线图上方 -->
        <div class="mobile-symbol-price" v-if="currentSymbol">
          <div class="mobile-symbol-info">
            <span class="mobile-market-tag">{{ currentMarket }}</span><span>-</span>
            <span class="mobile-symbol-label">{{ currentSymbol }}</span>
          </div>
          <div class="mobile-price-info" :class="priceChangeClass">
            <span class="mobile-symbol-price">{{ currentPrice }}</span>
            <span class="mobile-symbol-change">
              {{ priceChange > 0 ? '+' : '' }}{{ priceChange.toFixed(2) }}%
            </span>
          </div>
        </div>

        <kline-chart
          ref="klineChart"
          :symbol="currentSymbol"
          :market="currentMarket"
          :timeframe="timeframe"
          :theme="chartTheme"
          :activeIndicators="activeIndicators"
          :realtimeEnabled="realtimeEnabled"
          @price-change="handlePriceChange"
          @retry="handleChartRetry"
          @indicator-toggle="handleIndicatorToggle"
        />

        <div class="chart-right">
          <div class="indicators-panel">
            <div class="panel-header">
              <span>{{ $t('dashboard.indicator.panel.title') }}</span>
              <div style="display: flex; align-items: center; margin-left: auto; gap: 8px;">
                <!-- 手机端：创建指标按钮 -->
                <a-button
                  v-if="isMobile"
                  type="primary"
                  size="small"
                  icon="plus"
                  @click="handleCreateIndicator"
                  class="mobile-header-create-btn"
                >
                  {{ $t('dashboard.indicator.create') }}
                </a-button>
                <!-- 实时更新开关 -->
                <a-tooltip :title="realtimeEnabled ? $t('dashboard.indicator.panel.realtimeOn') : $t('dashboard.indicator.panel.realtimeOff')">
                  <a-button
                    type="text"
                    @click="toggleRealtime"
                    class="realtime-toggle-btn"
                    :class="{ 'active': realtimeEnabled }"
                  >
                    <a-icon :type="realtimeEnabled ? 'sync' : 'pause-circle'" :spin="realtimeEnabled" />
                  </a-button>
                </a-tooltip>
              </div>
            </div>

            <div class="panel-body">
              <!-- PC端：两个区域各占一半 -->
              <template v-if="!isMobile">
                <!-- 我创建的指标 -->
                <div class="indicator-section" :class="{ 'section-empty': customIndicators.length === 0 }">
                  <div class="section-label">
                    <div class="section-label-left" @click="toggleCustomSection">
                      <a-icon :type="customSectionCollapsed ? 'right' : 'down'" class="collapse-icon" />
                      <span>{{ $t('dashboard.indicator.section.myCreated') }} ({{ customIndicators.length }})</span>
                    </div>
                    <a-button
                      type="primary"
                      size="small"
                      icon="plus"
                      @click.stop="handleCreateIndicator"
                      class="create-indicator-btn"
                    >
                      {{ $t('dashboard.indicator.create') }}
                    </a-button>
                  </div>
                  <div v-show="!customSectionCollapsed" class="section-content custom-scrollbar">
                    <div
                      v-for="indicator in customIndicators"
                      :key="'custom-' + indicator.id"
                      :class="['indicator-card', { 'indicator-active': isIndicatorActive('custom-' + indicator.id) }]"
                      @click="toggleIndicator(indicator, 'custom')"
                    >
                      <div class="card-content">
                        <div class="card-header">
                          <span class="card-name">{{ indicator.name }}</span>
                          <div class="card-actions">
                            <!-- 编辑图标 -->
                            <a-tooltip :title="$t('dashboard.indicator.action.edit')">
                              <a-icon
                                type="edit"
                                class="action-icon edit-icon"
                                @click.stop="handleEditIndicator(indicator)"
                              />
                            </a-tooltip>
                            <!-- 删除图标 -->
                            <a-tooltip :title="$t('dashboard.indicator.action.delete')">
                              <a-icon
                                type="delete"
                                class="action-icon delete-icon"
                                @click.stop="handleDeleteIndicator(indicator)"
                              />
                            </a-tooltip>
                            <!-- 启动开关 -->
                            <a-tooltip :title="isIndicatorActive('custom-' + indicator.id) ? $t('dashboard.indicator.action.stop') : $t('dashboard.indicator.action.start')">
                              <a-icon
                                :type="isIndicatorActive('custom-' + indicator.id) ? 'pause-circle' : 'play-circle'"
                                :class="['action-icon', 'toggle-icon', { active: isIndicatorActive('custom-' + indicator.id) }]"
                                @click.stop="toggleIndicator(indicator, 'custom')"
                              />
                            </a-tooltip>
                            <!-- 回测按钮 -->
                            <a-tooltip :title="$t('dashboard.indicator.backtest.title')">
                              <a-icon
                                type="experiment"
                                class="action-icon backtest-icon"
                                @click.stop="handleOpenBacktest(indicator)"
                              />
                            </a-tooltip>
                            <!-- 回测记录 -->
                            <a-tooltip :title="$t('dashboard.indicator.backtest.historyTitle')">
                              <a-icon
                                type="clock-circle"
                                class="action-icon backtest-history-icon"
                                @click.stop="handleOpenBacktestHistory(indicator)"
                              />
                            </a-tooltip>
                            <!-- 发布到社区 -->
                            <a-tooltip :title="indicator.publish_to_community ? $t('dashboard.indicator.action.unpublish') : $t('dashboard.indicator.action.publish')">
                              <a-icon
                                :type="indicator.publish_to_community ? 'cloud' : 'cloud-upload'"
                                :class="['action-icon', 'publish-icon', { published: indicator.publish_to_community }]"
                                @click.stop="handlePublishIndicator(indicator)"
                              />
                            </a-tooltip>
                          </div>
                        </div>
                        <span class="card-desc">{{ indicator.description || '' }}</span>
                      </div>
                    </div>
                    <!-- 空状态 -->
                    <div v-if="customIndicators.length === 0" class="empty-indicators">
                      <a-icon type="info-circle" />
                      <span>{{ $t('dashboard.indicator.empty') }}</span>
                    </div>
                  </div>
                </div>

                <!-- 我购买的指标 -->
                <div class="indicator-section" :class="{ 'section-empty': purchasedIndicators.length === 0 }">
                  <div class="section-label">
                    <div class="section-label-left" @click="purchasedSectionCollapsed = !purchasedSectionCollapsed">
                      <a-icon :type="purchasedSectionCollapsed ? 'right' : 'down'" class="collapse-icon" />
                      <span>{{ $t('dashboard.indicator.section.purchased') }} ({{ purchasedIndicators.length }})</span>
                    </div>
                  </div>
                  <div v-show="!purchasedSectionCollapsed" class="section-content custom-scrollbar">
                    <div
                      v-for="indicator in purchasedIndicators"
                      :key="'purchased-' + indicator.id"
                      :class="['indicator-card', 'purchased-indicator', { 'indicator-active': isIndicatorActive('purchased-' + indicator.id) }]"
                      @click="toggleIndicator(indicator, 'purchased')"
                    >
                      <div class="card-content">
                        <div class="card-header">
                          <span class="card-name">
                            <a-icon type="shopping" class="purchased-icon" />
                            {{ indicator.name }}
                          </span>
                          <div class="card-actions">
                            <!-- 购买的指标：只能启动/停止和回测，不能编辑删除 -->
                            <a-tooltip :title="isIndicatorActive('purchased-' + indicator.id) ? $t('dashboard.indicator.action.stop') : $t('dashboard.indicator.action.start')">
                              <a-icon
                                :type="isIndicatorActive('purchased-' + indicator.id) ? 'pause-circle' : 'play-circle'"
                                :class="['action-icon', 'toggle-icon', { active: isIndicatorActive('purchased-' + indicator.id) }]"
                                @click.stop="toggleIndicator(indicator, 'purchased')"
                              />
                            </a-tooltip>
                            <a-tooltip :title="$t('dashboard.indicator.backtest.title')">
                              <a-icon
                                type="experiment"
                                class="action-icon backtest-icon"
                                @click.stop="handleOpenBacktest(indicator)"
                              />
                            </a-tooltip>
                            <a-tooltip :title="$t('dashboard.indicator.backtest.historyTitle')">
                              <a-icon
                                type="clock-circle"
                                class="action-icon backtest-history-icon"
                                @click.stop="handleOpenBacktestHistory(indicator)"
                              />
                            </a-tooltip>
                          </div>
                        </div>
                        <span class="card-desc">{{ indicator.description || '' }}</span>
                      </div>
                    </div>
                    <!-- 空状态 -->
                    <div v-if="purchasedIndicators.length === 0" class="empty-indicators">
                      <a-icon type="shopping" />
                      <span>{{ $t('dashboard.indicator.emptyPurchased') }}</span>
                    </div>
                  </div>
                </div>

              </template>

              <!-- 手机端：显示指标列表 -->
              <template v-else>
                <div class="mobile-tab-content">
                  <div class="section-content custom-scrollbar">
                    <div
                      v-for="indicator in customIndicators"
                      :key="'custom-' + indicator.id"
                      :class="['indicator-card', { 'indicator-active': isIndicatorActive('custom-' + indicator.id) }]"
                      @click="toggleIndicator(indicator, 'custom')"
                    >
                      <div class="card-content">
                        <div class="card-header">
                          <span class="card-name">{{ indicator.name }}</span>
                          <div class="card-actions">
                            <!-- 编辑图标 -->
                            <a-tooltip :title="$t('dashboard.indicator.action.edit')">
                              <a-icon
                                type="edit"
                                class="action-icon edit-icon"
                                @click.stop="handleEditIndicator(indicator)"
                              />
                            </a-tooltip>
                            <!-- 删除图标 -->
                            <a-tooltip :title="$t('dashboard.indicator.action.delete')">
                              <a-icon
                                type="delete"
                                class="action-icon delete-icon"
                                @click.stop="handleDeleteIndicator(indicator)"
                              />
                            </a-tooltip>
                            <!-- 启动开关 -->
                            <a-tooltip :title="isIndicatorActive('custom-' + indicator.id) ? $t('dashboard.indicator.action.stop') : $t('dashboard.indicator.action.start')">
                              <a-icon
                                :type="isIndicatorActive('custom-' + indicator.id) ? 'pause-circle' : 'play-circle'"
                                :class="['action-icon', 'toggle-icon', { active: isIndicatorActive('custom-' + indicator.id) }]"
                                @click.stop="toggleIndicator(indicator, 'custom')"
                              />
                            </a-tooltip>
                            <!-- 回测按钮 -->
                            <a-tooltip :title="$t('dashboard.indicator.backtest.title')">
                              <a-icon
                                type="experiment"
                                class="action-icon backtest-icon"
                                @click.stop="handleOpenBacktest(indicator)"
                              />
                            </a-tooltip>
                            <!-- 回测记录 -->
                            <a-tooltip :title="$t('dashboard.indicator.backtest.historyTitle')">
                              <a-icon
                                type="clock-circle"
                                class="action-icon backtest-history-icon"
                                @click.stop="handleOpenBacktestHistory(indicator)"
                              />
                            </a-tooltip>
                            <!-- 发布到社区 -->
                            <a-tooltip :title="indicator.publish_to_community ? $t('dashboard.indicator.action.unpublish') : $t('dashboard.indicator.action.publish')">
                              <a-icon
                                :type="indicator.publish_to_community ? 'cloud' : 'cloud-upload'"
                                :class="['action-icon', 'publish-icon', { published: indicator.publish_to_community }]"
                                @click.stop="handlePublishIndicator(indicator)"
                              />
                            </a-tooltip>
                          </div>
                        </div>
                        <span class="card-desc">{{ indicator.description || '' }}</span>
                      </div>
                    </div>
                    <!-- 空状态 -->
                    <div v-if="customIndicators.length === 0" class="empty-indicators">
                      <a-icon type="info-circle" />
                      <span>{{ $t('dashboard.indicator.empty') }}</span>
                    </div>
                  </div>
                </div>

              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- 指标编辑器弹窗 -->
      <indicator-editor
        ref="indicatorEditor"
        :visible="showIndicatorEditor"
        :indicator="editingIndicator"
        :userId="userId"
        @run="handleRunIndicator"
        @save="handleSaveIndicator"
        @cancel="showIndicatorEditor = false; editingIndicator = null"
      />

      <!-- 回测弹窗 -->
      <backtest-modal
        :visible="showBacktestModal"
        :userId="userId"
        :indicator="backtestIndicator"
        :symbol="selectedSymbol"
        :market="selectedMarket"
        :timeframe="selectedTimeframe"
        @cancel="showBacktestModal = false; backtestIndicator = null"
      />

      <!-- 指标参数配置弹窗 -->
      <a-modal
        :visible="showParamsModal"
        :title="$t('dashboard.indicator.paramsConfig.title')"
        :confirmLoading="loadingParams"
        @ok="confirmIndicatorParams"
        @cancel="cancelIndicatorParams"
        :width="500"
      >
        <div v-if="pendingIndicator" class="params-config-modal">
          <div class="indicator-info">
            <span class="indicator-name">{{ pendingIndicator.name }}</span>
          </div>
          <a-divider />
          <div v-if="indicatorParams.length > 0" class="params-form">
            <div v-for="param in indicatorParams" :key="param.name" class="param-item">
              <div class="param-header">
                <label class="param-label">{{ param.name }}</label>
                <a-tooltip v-if="param.description" :title="param.description">
                  <a-icon type="question-circle" style="color: #999; margin-left: 4px;" />
                </a-tooltip>
              </div>
              <!-- 整数类型 -->
              <a-input-number
                v-if="param.type === 'int'"
                v-model="indicatorParamValues[param.name]"
                :precision="0"
                style="width: 100%;"
              />
              <!-- 浮点数类型 -->
              <a-input-number
                v-else-if="param.type === 'float'"
                v-model="indicatorParamValues[param.name]"
                :precision="4"
                style="width: 100%;"
              />
              <!-- 布尔类型 -->
              <a-switch
                v-else-if="param.type === 'bool'"
                v-model="indicatorParamValues[param.name]"
              />
              <!-- 字符串类型 -->
              <a-input
                v-else
                v-model="indicatorParamValues[param.name]"
              />
            </div>
          </div>
          <a-empty v-else :description="$t('dashboard.indicator.paramsConfig.noParams')" />
        </div>
      </a-modal>

      <!-- 回测记录抽屉 -->
      <backtest-history-drawer
        :visible="showBacktestHistoryDrawer"
        :userId="userId"
        :indicatorId="backtestHistoryIndicator ? backtestHistoryIndicator.id : null"
        :symbol="selectedSymbol"
        :market="selectedMarket"
        :timeframe="selectedTimeframe"
        :isMobile="isMobile"
        @cancel="showBacktestHistoryDrawer = false; backtestHistoryIndicator = null"
        @view="handleViewBacktestRun"
      />

      <!-- 回测记录详情 -->
      <backtest-run-viewer
        :visible="showBacktestRunViewer"
        :run="selectedBacktestRun"
        @cancel="showBacktestRunViewer = false; selectedBacktestRun = null"
      />

      <!-- 发布到社区弹窗 -->
      <a-modal
        :title="publishIndicator && publishIndicator.publish_to_community ? $t('dashboard.indicator.publish.editTitle') : $t('dashboard.indicator.publish.title')"
        :visible="showPublishModal"
        @ok="handleConfirmPublish"
        @cancel="showPublishModal = false; publishIndicator = null"
        :confirmLoading="publishing"
        width="500px"
        :okText="publishIndicator && publishIndicator.publish_to_community ? $t('dashboard.indicator.publish.update') : $t('dashboard.indicator.publish.confirm')"
        :cancelText="$t('common.cancel')"
      >
        <a-form-model ref="publishForm" :model="publishForm" :rules="publishRules" layout="vertical">
          <a-alert
            type="info"
            show-icon
            :message="$t('dashboard.indicator.publish.hint')"
            style="margin-bottom: 16px;"
          />
          <a-form-model-item :label="$t('dashboard.indicator.publish.pricingType')" prop="pricingType">
            <a-radio-group v-model="publishPricingType">
              <a-radio value="free">{{ $t('dashboard.indicator.publish.free') }}</a-radio>
              <a-radio value="paid">{{ $t('dashboard.indicator.publish.paid') }}</a-radio>
            </a-radio-group>
          </a-form-model-item>
          <a-form-model-item
            v-if="publishPricingType === 'paid'"
            :label="$t('dashboard.indicator.publish.price')"
            prop="price"
          >
            <a-input-number
              v-model="publishPrice"
              :min="1"
              :max="10000"
              :precision="0"
              style="width: 200px;"
            />
            <span style="margin-left: 8px;">{{ $t('community.credits') }}</span>
          </a-form-model-item>
          <a-form-model-item :label="$t('dashboard.indicator.publish.description')" prop="description">
            <a-textarea
              v-model="publishDescription"
              :placeholder="$t('dashboard.indicator.publish.descriptionPlaceholder')"
              :rows="4"
              :maxLength="500"
            />
          </a-form-model-item>
          <div v-if="publishIndicator && publishIndicator.publish_to_community" style="margin-top: 16px;">
            <a-button type="danger" ghost @click="handleUnpublish" :loading="unpublishing">
              <a-icon type="close-circle" />
              {{ $t('dashboard.indicator.publish.unpublish') }}
            </a-button>
          </div>
        </a-form-model>
      </a-modal>

      <!-- 添加股票弹窗 -->
      <a-modal
        :title="$t('dashboard.analysis.modal.addStock.title')"
        :visible="showAddStockModal"
        @ok="handleAddStock"
        @cancel="handleCloseAddStockModal"
        :confirmLoading="addingStock"
        width="600px"
        :okText="$t('dashboard.analysis.modal.addStock.confirm')"
        :cancelText="$t('dashboard.analysis.modal.addStock.cancel')"
      >
        <div class="add-stock-modal-content">
          <!-- Tab标签 -->
          <a-tabs v-model="selectedMarketTab" @change="handleMarketTabChange" class="market-tabs">
            <a-tab-pane
              v-for="marketType in marketTypes"
              :key="marketType.value"
              :tab="$t(marketType.i18nKey || `dashboard.analysis.market.${marketType.value}`)"
            >
            </a-tab-pane>
          </a-tabs>

          <!-- 搜索/输入框（整合搜索和手动输入） -->
          <div class="symbol-search-section">
            <a-input-search
              v-model="symbolSearchKeyword"
              :placeholder="$t('dashboard.analysis.modal.addStock.searchOrInputPlaceholder')"
              @search="handleSearchOrInput"
              @change="handleSymbolSearchInput"
              :loading="searchingSymbols"
              size="large"
              allow-clear
            >
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
              :loading="searchingSymbols"
              size="small"
              class="symbol-list"
            >
              <a-list-item slot="renderItem" slot-scope="item" class="symbol-list-item" @click="selectSymbol(item)">
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
                class="symbol-list"
              >
                <a-list-item slot="renderItem" slot-scope="item" class="symbol-list-item" @click="selectSymbol(item)">
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
          <div v-if="selectedSymbolForAdd" class="selected-symbol-section">
            <a-alert
              :message="$t('dashboard.analysis.modal.addStock.selectedSymbol')"
              type="info"
              show-icon
              closable
              @close="selectedSymbolForAdd = null"
            >
              <template slot="description">
                <div class="selected-symbol-info">
                  <a-tag :color="getMarketColor(selectedSymbolForAdd.market)" style="margin-right: 8px;">
                    {{ $t(`dashboard.analysis.market.${selectedSymbolForAdd.market}`) }}
                  </a-tag>
                  <strong>{{ selectedSymbolForAdd.symbol }}</strong>
                  <span v-if="selectedSymbolForAdd.name" style="color: #999; margin-left: 8px;">{{ selectedSymbolForAdd.name }}</span>
                  <span v-else style="color: #999; margin-left: 8px; font-style: italic;">{{ $t('dashboard.analysis.modal.addStock.nameWillBeFetched') }}</span>
                </div>
              </template>
            </a-alert>
          </div>
        </div>
      </a-modal>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted, onBeforeUnmount, getCurrentInstance, watch } from 'vue'
import { mapState } from 'vuex'
import { message, Modal } from 'ant-design-vue'
import request from '@/utils/request'
import { getWatchlist, addWatchlist, searchSymbols, getHotSymbols, getMarketTypes } from '@/api/market'
import { getUserInfo } from '@/api/login'
import IndicatorEditor from '@/views/indicator-analysis/components/IndicatorEditor.vue'
import KlineChart from '@/views/indicator-analysis/components/KlineChart.vue'
import BacktestModal from '@/views/indicator-analysis/components/BacktestModal.vue'
import BacktestHistoryDrawer from '@/views/indicator-analysis/components/BacktestHistoryDrawer.vue'
import BacktestRunViewer from '@/views/indicator-analysis/components/BacktestRunViewer.vue'

export default {
  name: 'DashboardIndicator',
  components: {
    IndicatorEditor,
    KlineChart,
    BacktestModal,
    BacktestHistoryDrawer,
    BacktestRunViewer
  },
  computed: {
    ...mapState({
      navTheme: state => state.app.theme
    }),
    // 图表主题 - 从 store 获取
    chartTheme () {
      // 将 'dark' 或 'realdark' 都映射为 'dark'，其他为 'light'
      return (this.navTheme === 'dark' || this.navTheme === 'realdark') ? 'dark' : 'light'
    },
    // 判断是否为暗黑主题（用于添加类名）
    isDarkTheme () {
      return this.navTheme === 'dark' || this.navTheme === 'realdark'
    }
  },
  setup () {
    // 获取当前组件实例代理，用于动态访问 $t
    const instance = getCurrentInstance()
    const { proxy } = instance || {}

    // 用户信息（本地化单用户模式：默认 userId=1，避免页面因未登录而无法加载自选/指标）
    const userId = ref(1)
    const loadingUserInfo = ref(false)

    // 搜索相关
    const searchSymbol = ref(undefined)
    const symbolSuggestions = ref([])
    const watchlist = ref([]) // 自选股列表
    const loadingWatchlist = ref(false)
    const symbolSearchValue = ref('') // 搜索输入值
    const symbolSearchOpen = ref(false) // 下拉框是否打开

    // 添加股票弹窗相关
    const showAddStockModal = ref(false)
    const addingStock = ref(false)
    const selectedMarketTab = ref('') // 当前选中的市场类型tab
    const symbolSearchKeyword = ref('') // 搜索关键词
    const symbolSearchResults = ref([]) // 搜索结果
    const searchingSymbols = ref(false) // 是否正在搜索
    const hotSymbols = ref([]) // 热门标的列表
    const loadingHotSymbols = ref(false) // 是否正在加载热门标的
    const selectedSymbolForAdd = ref(null) // 选中的标的（用于添加）
    const searchTimer = ref(null) // 搜索防抖定时器
    const marketTypes = ref([]) // 股票类型列表
    const hasSearched = ref(false) // 是否已经搜索过（用于显示无结果提示）

    const currentSymbol = ref('')
    const currentMarket = ref('')
    const currentPrice = ref('--')
    const priceChange = ref(0)

    const priceChangeClass = computed(() => {
      return priceChange.value > 0 ? 'color-up' : priceChange.value < 0 ? 'color-down' : ''
    })

    const timeframe = ref('1D')
    const activeIndicators = ref([])
    const isMobile = ref(false)

    // SMA和EMA的均线组合定义（已废弃，保留用于兼容性检查）
    const smaGroup = [
      { id: 'sma5', name: 'SMA5 (5日均线)', shortName: 'SMA5', type: 'line', defaultParams: { length: 5 } },
      { id: 'sma10', name: 'SMA10 (10日均线)', shortName: 'SMA10', type: 'line', defaultParams: { length: 10 } },
      { id: 'sma20', name: 'SMA20 (20日均线)', shortName: 'SMA20', type: 'line', defaultParams: { length: 20 } },
      { id: 'sma30', name: 'SMA30 (30日均线)', shortName: 'SMA30', type: 'line', defaultParams: { length: 30 } }
    ]

    const emaGroup = [
      { id: 'ema5', name: 'EMA5 (5日指数均线)', shortName: 'EMA5', type: 'line', defaultParams: { length: 5 } },
      { id: 'ema10', name: 'EMA10 (10日指数均线)', shortName: 'EMA10', type: 'line', defaultParams: { length: 10 } },
      { id: 'ema20', name: 'EMA20 (20日指数均线)', shortName: 'EMA20', type: 'line', defaultParams: { length: 20 } },
      { id: 'ema30', name: 'EMA30 (30日指数均线)', shortName: 'EMA30', type: 'line', defaultParams: { length: 30 } }
    ]

    // 从数据库获取的指标
    const customIndicators = ref([]) // 我创建的指标（is_buy=0）
    const purchasedIndicators = ref([]) // 我购买的指标（is_buy=1）
    const loadingIndicators = ref(false)

    // 指标参数配置弹窗
    const showParamsModal = ref(false)
    const pendingIndicator = ref(null) // 待运行的指标
    const pendingSource = ref('') // 待运行指标的来源 (custom/purchased)
    const indicatorParams = ref([]) // 指标参数声明
    const indicatorParamValues = ref({}) // 用户设置的参数值
    const loadingParams = ref(false)

    // 折叠状态
    const customSectionCollapsed = ref(false) // 我创建的指标区域是否折叠
    const purchasedSectionCollapsed = ref(false) // 我购买的指标区域是否折叠

    // 指标编辑器相关
    const showIndicatorEditor = ref(false)
    const editingIndicator = ref(null)

    // 回测相关
    const showBacktestModal = ref(false)
    const backtestIndicator = ref(null)

    // 回测记录相关
    const showBacktestHistoryDrawer = ref(false)
    const backtestHistoryIndicator = ref(null)
    const showBacktestRunViewer = ref(false)
    const selectedBacktestRun = ref(null)

    // 发布到社区相关
    const showPublishModal = ref(false)
    const publishIndicator = ref(null)
    const publishing = ref(false)
    const unpublishing = ref(false)
    // 使用独立的 ref 变量，确保 v-model 正常工作
    const publishPricingType = ref('free')
    const publishPrice = ref(10)
    const publishDescription = ref('')
    const publishRules = {
      price: [
        { required: true, message: '请输入价格', trigger: 'blur', type: 'number' }
      ]
    }

    // 实时更新设置
    const realtimeEnabled = ref(false) // 是否启用实时更新

    // 处理价格变化事件（从 KlineChart 组件接收）
    const handlePriceChange = ({ price, change }) => {
      currentPrice.value = price
      priceChange.value = change
    }

    // 处理图表重试事件
    const handleChartRetry = () => {
      // KlineChart 组件会自己处理重试，这里可以添加额外的逻辑
    }

    // --- 指标定义（已废弃，保留用于兼容） ---
    const trendIndicators = ref([])
    const oscillatorIndicators = ref([])

    // --- 交互逻辑 ---

    const setTimeframe = (tf) => {
      timeframe.value = tf
      // KlineChart 组件会通过 watch timeframe 自动加载数据
    }

    const formatParams = (params) => {
      if (!params) return ''
      return Object.values(params).join(', ')
    }

    // 加载用户信息
    const loadUserInfo = async () => {
      loadingUserInfo.value = true
      try {
        // 获取 store 实例
        const instance = getCurrentInstance()
        const store = instance?.proxy?.$store

        // 先从 store 获取
        const storeUserInfo = store?.getters?.userInfo || {}
        if (storeUserInfo && storeUserInfo.email) {
          userId.value = storeUserInfo.id
          loadingUserInfo.value = false
          // 加载数据
          loadWatchlist()
          // 加载指标列表
          loadIndicators()
          return
        }

        // 如果 store 中没有，从 API 获取
        const res = await getUserInfo()
        if (res && res.code === 1 && res.data) {
          userId.value = res.data.id
          // 更新 store
          if (store) {
            store.commit('SET_INFO', res.data)
          }
          // 加载数据
          loadWatchlist()
          // 加载指标列表
          loadIndicators()
        }
      } catch (error) {
      } finally {
        loadingUserInfo.value = false
      }
    }

    // 加载自选股
    const loadWatchlist = async () => {
      if (!userId.value) return
      loadingWatchlist.value = true
      try {
        const res = await getWatchlist({ userid: userId.value })
        if (res && res.code === 1 && res.data) {
          watchlist.value = res.data.map(item => ({
            ...item,
            label: item.symbol + (item.name ? ` (${item.name})` : ''),
            value: `${item.market}:${item.symbol}`
          }))
          // 更新 symbolSuggestions
          updateSymbolSuggestions()

          // 如果有自选股，自动选择最新添加的那个（数组第一个，因为后端按 createtime desc 排序）
          if (watchlist.value.length > 0 && !currentSymbol.value) {
            const latestSymbol = watchlist.value[0]
            currentMarket.value = latestSymbol.market
            currentSymbol.value = latestSymbol.symbol
            searchSymbol.value = latestSymbol.value
          }
        }
      } catch (error) {
        message.error(proxy.$t('dashboard.indicator.error.loadWatchlistFailed'))
      } finally {
        loadingWatchlist.value = false
      }
    }

    // 更新搜索建议（基于自选股）
    const updateSymbolSuggestions = () => {
      if (symbolSearchValue.value) {
        // 如果有搜索输入，过滤自选股
        symbolSuggestions.value = watchlist.value.filter(item =>
          item.symbol.toLowerCase().includes(symbolSearchValue.value.toLowerCase()) ||
          (item.name && item.name.toLowerCase().includes(symbolSearchValue.value.toLowerCase()))
        )
      } else {
        // 没有搜索输入时，显示所有自选股
        symbolSuggestions.value = watchlist.value
      }
    }

    const handleSymbolSearch = (value) => {
      symbolSearchValue.value = value
      // 如果没有自选股且用户输入了内容，打开下拉框
      if (watchlist.value.length === 0 && value) {
        symbolSearchOpen.value = true
      }
      updateSymbolSuggestions()
    }

    const handleDropdownVisibleChange = (open) => {
      symbolSearchOpen.value = open
      // 如果关闭下拉框，清空搜索值
      if (!open) {
        symbolSearchValue.value = ''
      }
    }

    const handleSymbolSelect = (value) => {
      // 如果是提示选项，不处理
      if (value === '__empty_watchlist_hint__') {
        return
      }
      // 如果是添加股票选项
      if (value === '__add_stock_option__') {
        showAddStockModal.value = true
        // 重置选中项，避免显示内部值
        setTimeout(() => {
          searchSymbol.value = undefined
        }, 0)
        return
      }

      // 从自选股列表中找到选中的项
      let selected = watchlist.value.find(s => s.value === value)

      // 如果没找到，尝试从建议列表中找到
      if (!selected) {
        selected = symbolSuggestions.value.find(s => s.value === value)
      }

      // 如果还是没找到，尝试解析格式 "market:symbol"
      if (!selected && value.includes(':')) {
        const [market, symbol] = value.split(':')
        selected = { market, symbol, value }
      }

      if (selected) {
        currentMarket.value = selected.market
        currentSymbol.value = selected.symbol
        searchSymbol.value = selected.value // 显示选中的值
        // KlineChart 组件会通过 watch symbol 和 market 自动加载数据
      }
    }

    // 过滤选项（用于搜索）
    const filterSymbolOption = (input, option) => {
      const value = option.componentOptions?.propsData?.value || ''
      // 如果是提示选项或添加按钮，始终显示
      if (value === '__empty_watchlist_hint__' || value === '__add_stock_option__') {
        return true
      }
      return value.toLowerCase().includes(input.toLowerCase())
    }

    // 加载股票类型列表
    const loadMarketTypes = async () => {
      try {
        const res = await getMarketTypes()
        if (res && res.code === 1 && res.data && Array.isArray(res.data)) {
          marketTypes.value = res.data.map(item => ({
            value: item.value,
            i18nKey: item.i18nKey || `dashboard.analysis.market.${item.value}`
          }))
        } else if (res && res.code === 1 && res.data && typeof res.data === 'object') {
          marketTypes.value = Object.keys(res.data).map(key => ({
            value: key,
            i18nKey: `dashboard.analysis.market.${key}`
          }))
        } else {
          // Order: USStock > Crypto > Forex > Futures > HShare > AShare
          marketTypes.value = [
            { value: 'USStock', i18nKey: 'dashboard.analysis.market.USStock' },
            { value: 'Crypto', i18nKey: 'dashboard.analysis.market.Crypto' },
            { value: 'Forex', i18nKey: 'dashboard.analysis.market.Forex' },
            { value: 'Futures', i18nKey: 'dashboard.analysis.market.Futures' },
            { value: 'HShare', i18nKey: 'dashboard.analysis.market.HShare' },
            { value: 'AShare', i18nKey: 'dashboard.analysis.market.AShare' }
          ]
        }

        // 初始化选中的市场类型tab
        if (marketTypes.value.length > 0 && !selectedMarketTab.value) {
          selectedMarketTab.value = marketTypes.value[0].value
        }
      } catch (error) {
        // Order: USStock > Crypto > Forex > Futures > HShare > AShare
        marketTypes.value = [
          { value: 'USStock', i18nKey: 'dashboard.analysis.market.USStock' },
          { value: 'Crypto', i18nKey: 'dashboard.analysis.market.Crypto' },
          { value: 'Forex', i18nKey: 'dashboard.analysis.market.Forex' },
          { value: 'Futures', i18nKey: 'dashboard.analysis.market.Futures' },
          { value: 'HShare', i18nKey: 'dashboard.analysis.market.HShare' },
          { value: 'AShare', i18nKey: 'dashboard.analysis.market.AShare' }
        ]
      }
    }

    // 关闭添加股票弹窗
    const handleCloseAddStockModal = () => {
      showAddStockModal.value = false
      selectedSymbolForAdd.value = null
      symbolSearchKeyword.value = ''
      symbolSearchResults.value = []
      hasSearched.value = false
      selectedMarketTab.value = marketTypes.value.length > 0 ? marketTypes.value[0].value : ''
    }

    // 市场类型Tab切换
    const handleMarketTabChange = (activeKey) => {
      selectedMarketTab.value = activeKey
      symbolSearchKeyword.value = ''
      symbolSearchResults.value = []
      selectedSymbolForAdd.value = null
      hasSearched.value = false
      // 加载该市场类型的热门标的
      loadHotSymbols(activeKey)
    }

    // 搜索标的输入变化（防抖）
    const handleSymbolSearchInput = (e) => {
      const keyword = e.target.value
      symbolSearchKeyword.value = keyword

      // 清除之前的定时器
      if (searchTimer.value) {
        clearTimeout(searchTimer.value)
      }

      // 如果关键词为空，清空搜索结果和状态
      if (!keyword || keyword.trim() === '') {
        symbolSearchResults.value = []
        hasSearched.value = false
        selectedSymbolForAdd.value = null
        return
      }

      // 防抖：500ms后执行搜索
      searchTimer.value = setTimeout(() => {
        searchSymbolsInModal(keyword)
      }, 500)
    }

    // 搜索或直接添加（整合逻辑）
    const handleSearchOrInput = (keyword) => {
      if (!keyword || !keyword.trim()) {
        return
      }

      if (!selectedMarketTab.value) {
        message.warning(proxy.$t('dashboard.analysis.modal.addStock.pleaseSelectMarket'))
        return
      }

      // 如果有搜索结果，不处理（让用户选择）
      if (symbolSearchResults.value.length > 0) {
        return
      }

      // 如果没有搜索结果，直接添加
      if (hasSearched.value && symbolSearchResults.value.length === 0) {
        handleDirectAdd()
      } else {
        // 执行搜索
        searchSymbolsInModal(keyword)
      }
    }

    // 搜索标的（在添加股票弹窗中）
    const searchSymbolsInModal = async (keyword) => {
      if (!keyword || keyword.trim() === '') {
        symbolSearchResults.value = []
        hasSearched.value = false
        return
      }

      if (!selectedMarketTab.value) {
        message.warning(proxy.$t('dashboard.analysis.modal.addStock.pleaseSelectMarket'))
        return
      }

      searchingSymbols.value = true
      hasSearched.value = true
      try {
        const res = await searchSymbols({
          market: selectedMarketTab.value,
          keyword: keyword.trim(),
          limit: 20
        })
        if (res && res.code === 1 && res.data && res.data.length > 0) {
          symbolSearchResults.value = res.data
        } else {
          // 搜索无结果，不报错，允许直接添加
          symbolSearchResults.value = []
          // 自动设置为手动输入模式
          selectedSymbolForAdd.value = {
            market: selectedMarketTab.value,
            symbol: keyword.trim().toUpperCase(),
            name: '' // 名称由后端通过API获取
          }
        }
      } catch (error) {
        // 搜索失败也不报错，允许直接添加
        symbolSearchResults.value = []
        selectedSymbolForAdd.value = {
          market: selectedMarketTab.value,
          symbol: keyword.trim().toUpperCase(),
          name: '' // 名称由后端通过API获取
        }
      } finally {
        searchingSymbols.value = false
      }
    }

    // 直接添加（搜索无结果时）
    const handleDirectAdd = () => {
      if (!symbolSearchKeyword.value || !symbolSearchKeyword.value.trim()) {
        message.warning(proxy.$t('dashboard.analysis.modal.addStock.pleaseEnterSymbol'))
        return
      }

      if (!selectedMarketTab.value) {
        message.warning(proxy.$t('dashboard.analysis.modal.addStock.pleaseSelectMarket'))
        return
      }

      // 设置选中的标的（手动输入，名称会在后端获取）
      selectedSymbolForAdd.value = {
        market: selectedMarketTab.value,
        symbol: symbolSearchKeyword.value.trim().toUpperCase(),
        name: '' // 名称由后端通过API获取
      }
    }

    // 选择标的
    const selectSymbol = (symbol) => {
      selectedSymbolForAdd.value = {
        market: symbol.market,
        symbol: symbol.symbol,
        name: symbol.name || symbol.symbol
      }
    }

    // 加载热门标的
    const loadHotSymbols = async (market) => {
      if (!market) {
        market = selectedMarketTab.value || (marketTypes.value.length > 0 ? marketTypes.value[0].value : '')
      }

      if (!market) {
        return
      }

      loadingHotSymbols.value = true
      try {
        const res = await getHotSymbols({
          market: market,
          limit: 10
        })
        if (res && res.code === 1 && res.data) {
          hotSymbols.value = res.data
        } else {
          hotSymbols.value = []
        }
      } catch (error) {
        hotSymbols.value = []
      } finally {
        loadingHotSymbols.value = false
      }
    }

    // 添加自选股
    const handleAddStock = async () => {
      let market = ''
      let symbol = ''

      // 检查是否选中了标的（从数据库选择或手动输入）
      if (selectedSymbolForAdd.value) {
        market = selectedSymbolForAdd.value.market
        symbol = selectedSymbolForAdd.value.symbol.toUpperCase()
      } else if (symbolSearchKeyword.value && symbolSearchKeyword.value.trim()) {
        // 如果没有选中，但搜索框有输入，使用搜索框的值
        if (!selectedMarketTab.value) {
          message.warning(proxy.$t('dashboard.analysis.modal.addStock.pleaseSelectMarket'))
          return
        }
        market = selectedMarketTab.value
        symbol = symbolSearchKeyword.value.trim().toUpperCase()
      } else {
        message.warning(proxy.$t('dashboard.analysis.modal.addStock.pleaseSelectOrEnterSymbol'))
        return
      }

      addingStock.value = true
      try {
        const res = await addWatchlist({
          userid: userId.value,
          market: market,
          symbol: symbol
        })
        if (res && res.code === 1) {
          message.success(proxy.$t('dashboard.analysis.message.addStockSuccess'))
          handleCloseAddStockModal()
          // 重新加载自选股
          await loadWatchlist()
        } else {
          message.error(res?.msg || proxy.$t('dashboard.analysis.message.addStockFailed'))
        }
      } catch (error) {
        const errorMsg = error?.response?.data?.msg || error?.message || proxy.$t('dashboard.analysis.message.addStockFailed')
        message.error(errorMsg)
      } finally {
        addingStock.value = false
      }
    }

    // --- 数据加载和图表初始化函数已迁移到 KlineChart 组件 ---

    const addIndicator = (ind) => {
      if (isIndicatorActive(ind.id)) return
      // 如果传入的指标已经有 params，使用传入的 params；否则使用 defaultParams
      const params = ind.params || ind.defaultParams || {}
      activeIndicators.value.push({
        ...ind,
        id: ind.id, // 简单处理，如果允许多个同类指标需用 uniqueId
        params: { ...params }
      })
      // KlineChart 组件会通过 watch activeIndicators 自动更新图表
    }

    const removeIndicator = (id) => {
      // const beforeCount = activeIndicators.value.length
      activeIndicators.value = activeIndicators.value.filter(i => i.id !== id)
      // const afterCount = activeIndicators.value.length
      // KlineChart 组件会通过 watch activeIndicators 自动更新图表
    }

    // 处理从 KlineChart 组件传来的指标切换事件
    const handleIndicatorToggle = ({ action, indicator }) => {
      if (action === 'add') {
        // 需要为指标添加 calculate 函数
        const indicatorWithCalculate = {
          ...indicator,
          calculate: getIndicatorCalculateFunction(indicator.id)
        }
        addIndicator(indicatorWithCalculate)
      } else if (action === 'remove') {
        removeIndicator(indicator.id)
      }
    }

    // 根据指标 ID 获取对应的 calculate 函数
    // 注意：计算函数已迁移到 KlineChart.vue，这里返回 null，让 KlineChart.vue 根据 id 处理
    const getIndicatorCalculateFunction = (indicatorId) => {
      // KlineChart.vue 的 updateIndicators 函数会根据 indicator.id 直接处理
      // 不再需要 Indicator.vue 中的计算函数
      return null
    }

    const isIndicatorActive = (id) => {
      // 特殊处理SMA和EMA组合
      if (id === 'sma') {
        return smaGroup.some(ind => activeIndicators.value.some(i => i.id === ind.id))
      }
      if (id === 'ema') {
        return emaGroup.some(ind => activeIndicators.value.some(i => i.id === ind.id))
      }
      return activeIndicators.value.some(i => i.id === id)
    }

    // 获取自定义激活的指标（排除默认指标）
    const getCustomActiveIndicators = () => {
      // 获取所有默认指标的id列表（包括smaGroup、emaGroup）
      const defaultIndicatorIds = new Set()
      smaGroup.forEach(ind => defaultIndicatorIds.add(ind.id))
      emaGroup.forEach(ind => defaultIndicatorIds.add(ind.id))

      // 过滤掉所有默认指标
      return activeIndicators.value.filter(i => !defaultIndicatorIds.has(i.id))
    }

    // 加载数据库中的指标
    const loadIndicators = async () => {
      if (!userId.value) return
      loadingIndicators.value = true
      try {
        const res = await request({
          url: '/api/indicator/getIndicators',
          method: 'get',
          params: {
            userid: userId.value
          }
        })

        if (res.code === 1 && res.data) {
          // 我创建的指标（is_buy=0 或未设置）
          const customItems = res.data.filter(item => !item.is_buy || item.is_buy === 0 || item.is_buy === '0')
          // 我购买的指标（is_buy=1）
          const purchasedItems = res.data.filter(item => item.is_buy === 1 || item.is_buy === '1')

          customIndicators.value = customItems.map(item => ({
            ...item,
            type: 'python',
            source: 'custom'
          }))

          purchasedIndicators.value = purchasedItems.map(item => ({
            ...item,
            type: 'python',
            source: 'purchased'
          }))
        }
      } catch (error) {
      } finally {
        loadingIndicators.value = false
      }
    }

    // --- Python 相关函数已迁移到 KlineChart 组件 ---

    // KlineChart 组件引用
    const klineChart = ref(null)

    // 添加Python代码指标
    const addPythonIndicator = async (indicator, source) => {
      const indicatorId = `${source}-${indicator.id}`
      if (isIndicatorActive(indicatorId)) {
        removeIndicator(indicatorId)
        return
      }

      try {
        const pythonCode = indicator.code || ''
        // 检查图表组件是否已初始化
        if (!klineChart.value) {
          message.error(proxy.$t('dashboard.indicator.error.chartNotReady'))
          return
        }

        // 检查必要的方法是否存在
        if (typeof klineChart.value.parsePythonStrategy !== 'function') {
          message.error(proxy.$t('dashboard.indicator.error.chartMethodNotReady'))
          return
        }

        if (typeof klineChart.value.executePythonStrategy !== 'function') {
          message.error(proxy.$t('dashboard.indicator.error.chartExecuteNotReady'))
          return
        }
        const parsed = klineChart.value.parsePythonStrategy(pythonCode)

        if (!parsed) {
          message.error(proxy.$t('dashboard.indicator.error.parseFailed'))
          return
        }

        // 用户传递的参数（来自参数配置弹窗）
        const userParams = indicator.userParams || {}

        // 创建一个Python指标对象
        // 保存代码到局部变量，避免闭包问题
        const savedCode = pythonCode
        const savedUserParams = { ...userParams } // 保存用户参数
        const pythonIndicator = {
          id: indicatorId, // 格式化后的ID（如 bought-1）
          name: indicator.name,
          type: 'python',
          code: savedCode,
          description: indicator.description,
          parsed: parsed, // 保存解析结果
          userParams: savedUserParams, // 保存用户参数
          // 保存原始数据库ID和用户ID，用于解密
          originalId: indicator.id, // 数据库中的真实ID
          user_id: indicator.user_id || indicator.userId, // 用户ID
          is_encrypted: indicator.is_encrypted || indicator.isEncrypted || 0, // 是否加密标记
          calculate: (data, params) => {
            // 通过 KlineChart 组件的 ref 访问 executePythonStrategy 函数
            // 使用savedCode确保每个指标使用自己的代码（避免闭包问题）
            // 传递完整的indicator信息用于解密
            // 将用户参数直接合并到 params 中，让指标代码可以通过 params.get('name', default) 访问
            return klineChart.value.executePythonStrategy(savedCode, data, { ...params, ...savedUserParams }, {
              id: indicator.id, // 使用原始数据库ID
              user_id: indicator.user_id || indicator.userId,
              is_encrypted: indicator.is_encrypted || indicator.isEncrypted || 0
            })
          }
        }

        const indicatorParamsFromParsed = { ...parsed.params, ...userParams }
        activeIndicators.value.push({
          ...pythonIndicator,
          params: indicatorParamsFromParsed
        })
        // KlineChart 组件会通过 watch activeIndicators 自动更新图表
      } catch (error) {
        message.error(proxy.$t('dashboard.indicator.error.addIndicatorFailed') + ': ' + (error.message || '未知错误'))
      }
    }

    // 切换指标开关
    const toggleIndicator = async (indicator, source) => {
      const indicatorId = `${source}-${indicator.id}`
      if (isIndicatorActive(indicatorId)) {
        removeIndicator(indicatorId)
      } else {
        // 检查指标是否有参数声明
        try {
          loadingParams.value = true
          const res = await proxy.$http.get('/api/indicator/getIndicatorParams', {
            params: { indicator_id: indicator.id }
          })
          if (res && res.code === 1 && Array.isArray(res.data) && res.data.length > 0) {
            // 有参数，显示配置弹窗
            indicatorParams.value = res.data
            indicatorParamValues.value = {}
            res.data.forEach(p => {
              indicatorParamValues.value[p.name] = p.default
            })
            pendingIndicator.value = indicator
            pendingSource.value = source
            showParamsModal.value = true
          } else {
            // 无参数，直接运行
            addPythonIndicator(indicator, source)
          }
        } catch (err) {
          console.warn('Failed to load indicator params:', err)
          // 出错时直接运行
          addPythonIndicator(indicator, source)
        } finally {
          loadingParams.value = false
        }
      }
    }

    // 确认参数配置并运行指标
    const confirmIndicatorParams = () => {
      if (pendingIndicator.value) {
        // 将参数传递给指标
        const indicatorWithParams = {
          ...pendingIndicator.value,
          userParams: { ...indicatorParamValues.value }
        }
        addPythonIndicator(indicatorWithParams, pendingSource.value)
      }
      showParamsModal.value = false
      pendingIndicator.value = null
      pendingSource.value = ''
    }

    // 取消参数配置
    const cancelIndicatorParams = () => {
      showParamsModal.value = false
      pendingIndicator.value = null
      pendingSource.value = ''
    }

    // 运行指标代码（从编辑器）
    const handleRunIndicator = (data) => {
      const { code, name } = data
      if (!code || !code.trim()) {
        message.warning(proxy.$t('dashboard.indicator.warning.enterCode'))
        return
      }

      // 创建一个临时指标对象用于运行
      try {
        // 检查图表组件是否已初始化
        if (!klineChart.value) {
          message.error(proxy.$t('dashboard.indicator.error.chartNotReady'))
          return
        }

        // 检查必要的方法是否存在
        if (typeof klineChart.value.parsePythonStrategy !== 'function') {
          message.error(proxy.$t('dashboard.indicator.error.chartMethodNotReady'))
          return
        }

        if (typeof klineChart.value.executePythonStrategy !== 'function') {
          message.error(proxy.$t('dashboard.indicator.error.chartExecuteNotReady'))
          return
        }
        const parsed = klineChart.value.parsePythonStrategy(code)
        if (!parsed) {
          message.error(proxy.$t('dashboard.indicator.error.parseFailedCheck'))
          return
        }

        // 创建Python指标对象
        const pythonIndicator = {
          id: 'temp-editor-indicator',
          name: name || '临时指标',
          type: 'python',
          code: code,
          description: '',
          parsed: parsed,
          calculate: (data, params) => {
            // 通过 KlineChart 组件的 ref 访问 executePythonStrategy 函数
            // 使用indicator.code确保每个指标使用自己的代码（避免闭包问题）
            // 注意：这里使用indicatorCode，因为这是临时指标，需要从外部作用域获取code
            const indicatorCode = code
            return klineChart.value.executePythonStrategy(indicatorCode, data, params)
          }
        }

        // 如果已存在临时指标，先移除
        const existingIndex = activeIndicators.value.findIndex(i => i.id === 'temp-editor-indicator')
        if (existingIndex >= 0) {
          activeIndicators.value.splice(existingIndex, 1)
        }

        // 添加到活动指标列表
        activeIndicators.value.push({
          ...pythonIndicator,
          params: { ...parsed.params }
        })

        // KlineChart 组件会通过 watch activeIndicators 自动更新图表
        message.success(proxy.$t('dashboard.indicator.success.runIndicator'))
      } catch (error) {
        message.error(proxy.$t('dashboard.indicator.error.runIndicatorFailed') + ': ' + (error.message || '未知错误'))
      }
    }

    // 创建指标
    const handleCreateIndicator = () => {
      editingIndicator.value = null
      showIndicatorEditor.value = true
    }

    // 编辑指标
    const handleEditIndicator = (indicator) => {
      editingIndicator.value = indicator
      showIndicatorEditor.value = true
    }

    // 切换我创建的指标区域折叠状态
    const toggleCustomSection = () => {
      customSectionCollapsed.value = !customSectionCollapsed.value
    }

    // 删除指标
    const handleDeleteIndicator = (indicator) => {
      Modal.confirm({
        title: proxy.$t('dashboard.indicator.delete.confirmTitle'),
        content: proxy.$t('dashboard.indicator.delete.confirmContent', { name: indicator.name }),
        okText: proxy.$t('dashboard.indicator.delete.confirmOk'),
        okType: 'danger',
        cancelText: proxy.$t('dashboard.indicator.delete.confirmCancel'),
        onOk: async () => {
          try {
            const res = await request({
              url: '/api/indicator/deleteIndicator',
              method: 'post',
              data: {
                id: indicator.id,
                userid: userId.value
              }
            })

            if (res.code === 1) {
              message.success(proxy.$t('dashboard.indicator.delete.success'))
              // 如果该指标正在使用，先移除
              const indicatorId = 'custom-' + indicator.id
              if (isIndicatorActive(indicatorId)) {
                removeIndicator(indicatorId)
              }
              // 重新加载指标列表
              await loadIndicators()
            } else {
              message.error(res.msg || proxy.$t('dashboard.indicator.delete.failed'))
            }
          } catch (error) {
            message.error(proxy.$t('dashboard.indicator.delete.failed') + ': ' + (error.message || '未知错误'))
          }
        }
      })
    }

    // 打开回测弹窗（策略 = 指标信号 + 回测参数配置）
    const handleOpenBacktest = (indicator) => {
      backtestIndicator.value = { ...indicator }
      showBacktestModal.value = true
    }

    const handleOpenBacktestHistory = (indicator) => {
      backtestHistoryIndicator.value = { ...indicator }
      showBacktestHistoryDrawer.value = true
    }

    const handleViewBacktestRun = (run) => {
      selectedBacktestRun.value = run
      showBacktestRunViewer.value = true
    }

    // 发布指标到社区
    const handlePublishIndicator = (indicator) => {
      publishIndicator.value = { ...indicator }
      // 设置表单初始值
      publishPricingType.value = indicator.pricing_type || 'free'
      publishPrice.value = indicator.price || 10
      publishDescription.value = indicator.description || ''
      showPublishModal.value = true
    }

    // 确认发布
    const handleConfirmPublish = async () => {
      if (!userId.value) {
        message.error(proxy.$t('dashboard.indicator.error.pleaseLogin'))
        return
      }

      publishing.value = true
      try {
        const res = await request({
          url: '/api/indicator/saveIndicator',
          method: 'post',
          data: {
            userid: userId.value,
            id: publishIndicator.value.id,
            code: publishIndicator.value.code,
            name: publishIndicator.value.name,
            description: publishDescription.value,
            publishToCommunity: true,
            pricingType: publishPricingType.value,
            price: publishPricingType.value === 'paid' ? publishPrice.value : 0
          }
        })

        if (res.code === 1) {
          message.success(proxy.$t('dashboard.indicator.publish.success'))
          showPublishModal.value = false
          publishIndicator.value = null
          await loadIndicators()
        } else {
          message.error(res.msg || proxy.$t('dashboard.indicator.publish.failed'))
        }
      } catch (error) {
        message.error(proxy.$t('dashboard.indicator.publish.failed') + ': ' + (error.message || ''))
      } finally {
        publishing.value = false
      }
    }

    // 取消发布
    const handleUnpublish = async () => {
      if (!userId.value || !publishIndicator.value) return

      unpublishing.value = true
      try {
        const res = await request({
          url: '/api/indicator/saveIndicator',
          method: 'post',
          data: {
            userid: userId.value,
            id: publishIndicator.value.id,
            code: publishIndicator.value.code,
            name: publishIndicator.value.name,
            description: publishIndicator.value.description,
            publishToCommunity: false,
            pricingType: 'free',
            price: 0
          }
        })

        if (res.code === 1) {
          message.success(proxy.$t('dashboard.indicator.publish.unpublishSuccess'))
          showPublishModal.value = false
          publishIndicator.value = null
          await loadIndicators()
        } else {
          message.error(res.msg || proxy.$t('dashboard.indicator.publish.unpublishFailed'))
        }
      } catch (error) {
        message.error(proxy.$t('dashboard.indicator.publish.unpublishFailed'))
      } finally {
        unpublishing.value = false
      }
    }

    // 保存指标到数据库
    const handleSaveIndicator = async (data) => {
      if (!userId.value) {
        message.error(proxy.$t('dashboard.indicator.error.pleaseLogin'))
        return
      }

      // 通过ref获取编辑器组件，设置saving状态
      const editorRef = proxy.$refs.indicatorEditor
      if (editorRef) {
        editorRef.saving = true
      }

      try {
        const res = await request({
          url: '/api/indicator/saveIndicator',
          method: 'post',
          data: {
            userid: userId.value,
            id: data.id || 0,
            code: data.code
          }
        })

        if (res.code === 1) {
          message.success(proxy.$t('dashboard.indicator.save.success'))
          // 关闭弹窗
          showIndicatorEditor.value = false
          editingIndicator.value = null
          // 重新加载指标列表
          await loadIndicators()
        } else {
          message.error(res.msg || proxy.$t('dashboard.indicator.save.failed'))
        }
      } catch (error) {
        message.error(proxy.$t('dashboard.indicator.save.failed') + ': ' + (error.message || '未知错误'))
      } finally {
        if (editorRef) {
          editorRef.saving = false
        }
      }
    }

    // 获取指标状态文本
    const getIndicatorStatus = (indicator) => {
      const endTime = indicator.end_time
      if (endTime === 1 || endTime === '1') {
        return proxy.$t('dashboard.indicator.status.normalPermanent')
      }
      if (!endTime || endTime === 0) {
        return proxy.$t('dashboard.indicator.status.normal')
      }
      const currentTime = Math.floor(Date.now() / 1000)
      if (endTime < currentTime) {
        return proxy.$t('dashboard.indicator.status.expired')
      }
      return proxy.$t('dashboard.indicator.status.normal')
    }

    // 获取指标状态图标
    const getIndicatorStatusIcon = (indicator) => {
      const endTime = indicator.end_time
      if (endTime === 1 || endTime === '1') {
        return 'check-circle'
      }
      if (!endTime || endTime === 0) {
        return 'check-circle'
      }
      const currentTime = Math.floor(Date.now() / 1000)
      if (endTime < currentTime) {
        return 'close-circle'
      }
      return 'check-circle'
    }

    // 获取指标状态样式类
    const getIndicatorStatusClass = (indicator) => {
      const endTime = indicator.end_time
      if (endTime === 1 || endTime === '1') {
        return 'status-normal'
      }
      if (!endTime || endTime === 0) {
        return 'status-normal'
      }
      const currentTime = Math.floor(Date.now() / 1000)
      if (endTime < currentTime) {
        return 'status-expired'
      }
      return 'status-normal'
    }

    // 获取到期时间文本
    const getExpiryTimeText = (indicator) => {
      const endTime = indicator.end_time
      if (endTime === 1 || endTime === '1') {
        return proxy.$t('dashboard.indicator.expiry.permanent')
      }
      if (!endTime || endTime === 0) {
        return proxy.$t('dashboard.indicator.expiry.noExpiry')
      }
      const currentTime = Math.floor(Date.now() / 1000)
      const date = new Date(endTime * 1000).toLocaleString(proxy.$i18n.locale === 'zh-CN' ? 'zh-CN' : proxy.$i18n.locale === 'zh-TW' ? 'zh-TW' : 'en-US')
      if (endTime < currentTime) {
        return proxy.$t('dashboard.indicator.expiry.expired', { date })
      }
      return proxy.$t('dashboard.indicator.expiry.expiresOn', { date })
    }

    // 获取市场名称（多语言）
    const getMarketName = (market) => {
      const marketMap = {
        'AShare': 'dashboard.indicator.market.AShare',
        'USStock': 'dashboard.indicator.market.USStock',
        'HShare': 'dashboard.indicator.market.HShare',
        'Crypto': 'dashboard.indicator.market.Crypto',
        'Forex': 'dashboard.indicator.market.Forex',
        'Futures': 'dashboard.indicator.market.Futures'
      }
      const key = marketMap[market]
      return key && proxy?.$t ? proxy.$t(key) : market
    }

    // 获取市场颜色
    const getMarketColor = (market) => {
      const colors = {
        'USStock': 'green',
        'Crypto': 'purple',
        'Forex': 'gold',
        'Futures': 'cyan',
        'AShare': 'blue',
        'HShare': 'orange'
      }
      return colors[market] || 'default'
    }

    // --- 实时更新函数已迁移到 KlineChart 组件 ---

    // 切换实时更新状态
    const toggleRealtime = () => {
      realtimeEnabled.value = !realtimeEnabled.value
      localStorage.setItem('realtimeEnabled', realtimeEnabled.value.toString())
      // KlineChart 组件会通过 watch realtimeEnabled 自动启动或停止实时更新
    }

    // 检测是否为手机端
    const checkMobile = () => {
      isMobile.value = window.innerWidth <= 768
    }

    onMounted(() => {
      // 从 localStorage 加载实时更新设置
      const savedRealtime = localStorage.getItem('realtimeEnabled')
      if (savedRealtime !== null) {
        realtimeEnabled.value = savedRealtime === 'true'
      }

      // 检测设备类型
      checkMobile()
      window.addEventListener('resize', checkMobile)

      // 加载市场类型和热门标的
      loadMarketTypes()

      // 加载用户信息（会尝试从 store/API 获取；本地单用户模式下 userId 默认=1）
      loadUserInfo()

      // 本地单用户模式：直接拉自选股，避免未登录导致左上角无标的可选
      loadWatchlist()

      // 加载指标列表（仅“我创建的指标”）
      loadIndicators()

      // KlineChart 组件会自动处理实时更新和图表初始化
    })

    onBeforeUnmount(() => {
      window.removeEventListener('resize', checkMobile)
      // 清理搜索定时器
      if (searchTimer.value) {
        clearTimeout(searchTimer.value)
      }
      // KlineChart 组件会自动清理资源
    })

    // 监听弹窗打开，初始化数据
    watch(showAddStockModal, (newVal) => {
      if (newVal) {
        // 初始化选中的市场类型
        if (marketTypes.value.length > 0 && !selectedMarketTab.value) {
          selectedMarketTab.value = marketTypes.value[0].value
        }
        // 加载热门标的
        if (selectedMarketTab.value) {
          loadHotSymbols(selectedMarketTab.value)
        }
      } else {
        // 关闭时清理数据
        selectedSymbolForAdd.value = null
        symbolSearchKeyword.value = ''
        symbolSearchResults.value = []
        hasSearched.value = false
        if (searchTimer.value) {
          clearTimeout(searchTimer.value)
          searchTimer.value = null
        }
      }
    })

    return {
      userId,
      klineChart,
      searchSymbol,
      symbolSuggestions,
watchlist,
symbolSearchValue,
symbolSearchOpen,
      currentSymbol,
currentMarket,
      currentPrice,
      priceChange,
      priceChangeClass,
      timeframe,
loadingWatchlist,
      activeIndicators,
      trendIndicators,
      oscillatorIndicators,
      customIndicators,
      purchasedIndicators,
      loadingIndicators,
      realtimeEnabled,
toggleRealtime,
      handleSymbolSearch,
      handleSymbolSelect,
handleDropdownVisibleChange,
      filterSymbolOption,
getMarketName,
getMarketColor,
      setTimeframe,
      addIndicator,
      removeIndicator,
      isIndicatorActive,
      loadIndicators,
      addPythonIndicator,
      toggleIndicator,
      getIndicatorStatus,
      getIndicatorStatusIcon,
      getIndicatorStatusClass,
      getExpiryTimeText,
      formatParams,
      loadWatchlist,
      getCustomActiveIndicators,
      showIndicatorEditor,
      editingIndicator,
      handleCreateIndicator,
      handleRunIndicator,
      handleSaveIndicator,
      handleEditIndicator,
      handleDeleteIndicator,
      toggleCustomSection,
      customSectionCollapsed,
      purchasedSectionCollapsed,
      handlePriceChange,
      handleChartRetry,
      handleIndicatorToggle,
      // 指标参数配置相关
      showParamsModal,
      pendingIndicator,
      indicatorParams,
      indicatorParamValues,
      loadingParams,
      confirmIndicatorParams,
      cancelIndicatorParams,
      // 回测相关
      showBacktestModal,
      backtestIndicator,
      handleOpenBacktest,
      // 回测记录相关
      showBacktestHistoryDrawer,
      backtestHistoryIndicator,
      handleOpenBacktestHistory,
      showBacktestRunViewer,
      selectedBacktestRun,
      handleViewBacktestRun,
      // 发布到社区相关
      showPublishModal,
      publishIndicator,
      publishing,
      unpublishing,
      publishPricingType,
      publishPrice,
      publishDescription,
      publishRules,
      handlePublishIndicator,
      handleConfirmPublish,
      handleUnpublish,
      // 暴露给回测弹窗使用的选中值
      selectedSymbol: currentSymbol,
      selectedMarket: currentMarket,
      selectedTimeframe: timeframe,
      // 手机端相关
      isMobile,
      // 添加股票弹窗相关
      showAddStockModal,
      addingStock,
      selectedMarketTab,
      symbolSearchKeyword,
      symbolSearchResults,
      searchingSymbols,
      hotSymbols,
      loadingHotSymbols,
      selectedSymbolForAdd,
      marketTypes,
      hasSearched,
      handleCloseAddStockModal,
      handleMarketTabChange,
      handleSymbolSearchInput,
      handleSearchOrInput,
      searchSymbolsInModal,
      selectSymbol,
      loadHotSymbols,
      handleAddStock,
      handleDirectAdd,
      loadMarketTypes
    }
  }
}
</script>

<style lang="less" scoped>
/* 整体容器：浅色主题背景 */
.chart-container {
  display: flex;
  flex-direction: column;
  width: 100%;
  // height: 100vh; /* 使用100vh，让chart-content的70vh生效 */
  min-width: 100%;
  // max-width: 100%;
  background: #f0f2f5;
  color: #333;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
  box-sizing: border-box;
}

/* 顶部 Header */
.chart-header {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 100%;
  max-width: 100%;
  background: #fff;
  border-bottom: 1px solid #e8e8e8;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.02);
  box-sizing: border-box;
}

.header-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 16px;
  height: 60px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 20px;
}

/* 搜索框美化 */
.symbol-select {
  width: 220px;

  :deep(.ant-select-selection) {
    background-color: #fff;
    border: 1px solid #e8e8e8;
    color: #333;
    border-radius: 4px;
    box-shadow: none;

    &:hover {
      border-color: #1890ff;
    }
  }

  :deep(.ant-select-focused .ant-select-selection) {
    border-color: #1890ff;
    box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.2);
  }

  :deep(.ant-select-arrow) {
    color: #999;
  }

  :deep(.ant-select-selection__placeholder) {
    color: #999;
  }
}

/* 时间周期按钮 */
.timeframe-group {
  display: flex;
  background: #f0f2f5;
  border-radius: 4px;
  padding: 2px;
}

.timeframe-item {
  padding: 4px 12px;
  font-size: 13px;
  font-weight: 600;
  color: #666;
  cursor: pointer;
  transition: all 0.2s;
  border-radius: 4px;

  &:hover {
    color: #1890ff;
    background: #fff;
  }

  &.active {
    color: #1890ff;
    background: #fff;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
  }
}

/* 当前标的信息 */
.current-symbol {
  display: flex;
  align-items: center;
  gap: 24px;
}

.symbol-info {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

  .symbol-label {
  font-size: 16px;
  font-weight: 700;
  color: #333;
  line-height: 1.2;
}

.market-tag {
  font-size: 10px;
  color: #666;
  background: #f0f2f5;
  padding: 1px 4px;
  border-radius: 2px;
  margin-top: 2px;
}

.price-info {
  display: flex;
  flex-direction: column;
  align-items: flex-end;

  &.color-up { color: #0ecb81; }
  &.color-down { color: #f6465d; }
  }

  .symbol-price {
  font-size: 18px;
    font-weight: 600;
  font-family: 'Roboto Mono', monospace;
  line-height: 1.2;
}

.symbol-change {
  font-size: 12px;
}

/* 手机端：币种和价格信息显示在K线图上方 */
.mobile-symbol-price {
  display: none; /* 默认隐藏，只在移动端显示 */
}

/* 主题切换按钮 */
/* 主题切换按钮 - 在 panel-header 中 */
.panel-header .theme-switcher {
  margin-left: auto;
  display: flex;
  align-items: center;
}

.panel-header .realtime-toggle-btn,
.panel-header .theme-toggle-btn {
  color: #666;
  border: none;
  padding: 4px 8px;
  transition: all 0.3s;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  min-width: 32px;
  height: 32px;

  &:hover {
    color: #1890ff;
    background: #f0f2f5;
  }

  &.active {
    color: #1890ff;
    background: #e6f7ff;
  }

  .anticon {
    font-size: 16px;
  }
}

/* 主内容区 */
.chart-content {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  width: 100%;
  min-width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}

.chart-main-row {
  display: flex;
  overflow: hidden;
  width: 100%;
  height: 80vh !important; /* K线图占屏幕高度70% */
  min-height: 500px !important; /* 最小高度保证 */
  max-height: 80vh !important; /* 限制最大高度 */
  flex-shrink: 0; /* 防止被压缩 */
}

/* 图表相关样式已迁移到 KlineChart 组件 */

/* 右侧指标侧边栏 */
.chart-right {
  width: 30% !important;
  flex: 0 0 30% !important;
  background: #fff;
  display: flex;
  flex-direction: column;
  border-left: 1px solid #e8e8e8;
}

.indicators-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fff;
}

.panel-header {
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  border-bottom: 1px solid #e8e8e8;
  font-weight: 600;
  color: #333;
  background: #fff;

  .mobile-header-create-btn {
    margin-right: 0;
  }
}

.panel-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
}

.indicator-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-bottom: 1px solid #e8e8e8;

  &:last-child {
    border-bottom: none;
  }

  &.section-empty {
    min-height: 200px;
  }
}

.section-label {
  flex-shrink: 0;
  padding: 12px 16px;
  background: #fafafa;
  border-bottom: 1px solid #e8e8e8;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;

  .section-label-left {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: 1;

    .collapse-icon {
      font-size: 12px;
      color: #999;
      transition: transform 0.2s;
    }

    span {
      font-weight: 500;
    }
  }

  .buy-indicator-btn {
    padding: 0;
    height: auto;
    margin-left: 8px;
  }
}

.create-indicator-btn {
  margin-left: auto;
  margin-right: 0px;
}

/* 手机端隐藏PC端的创建按钮 */
@media (max-width: 768px) {
  .create-indicator-btn {
    display: none !important;
  }
}

.section-content {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
  min-height: 0;
}

/* 指标卡片 */
.indicator-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #fff;
  padding: 10px 12px;
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid #e8e8e8;

  &:hover {
    background: #f0f2f5;
    border-color: #1890ff;
    transform: translateY(-1px);
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
  }

  &.active {
    background: #e6f7ff;
    border-color: #1890ff;

    .card-name { color: #1890ff; }
  }

  &.indicator-active {
    border-color: #52c41a;
    border-width: 2px;
    background: #f6ffed;

    &:hover {
      border-color: #73d13d;
      box-shadow: 0 2px 8px rgba(82, 196, 26, 0.2);
    }

    .card-name {
      color: #52c41a;
    }
  }

  &.disabled {
    opacity: 0.5;
    cursor: not-allowed;
    &:hover {
      transform: none;
      background: #fff;
      border-color: #e8e8e8;
      box-shadow: none;
    }
  }
}

.card-content {
  display: flex;
  flex-direction: column;
  width: 100%;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.card-name {
  font-size: 13px;
  color: #333;
  font-weight: 500;
  flex: 1;
  margin-right: 8px;
}

.card-params {
  font-size: 11px;
  color: #999;
  margin-top: 2px;
}

.card-desc {
  font-size: 11px;
  color: #999;
  margin-top: 0;
  display: -webkit-box;
  width: 100%;
  box-sizing: border-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: normal;
  line-height: 1.4;
  min-height: 1.4em;
  max-height: 2.8em;
}

.card-action {
  color: #999;
  font-size: 12px;
  &:hover { color: #1890ff; }
}

.card-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.action-icon {
  &.edit-icon {
    color: #1890ff;
    &:hover {
      color: #40a9ff;
    }
  }
  &.delete-icon {
    color: #ff4d4f;
    &:hover {
      color: #ff7875;
    }
  }
  font-size: 16px;
  cursor: pointer;
  transition: all 0.3s;
  color: #999;

  &:hover {
    color: #1890ff;
  }

  &.toggle-icon {
    &.active {
      color: #52c41a;
    }
  }

  &.backtest-icon {
    color: #722ed1;
    &:hover {
      color: #9254de;
    }
  }
  &.backtest-history-icon {
    color: #13c2c2;
    &:hover {
      color: #08979c;
    }
  }

  &.publish-icon {
    color: #1890ff;
    &:hover {
      color: #40a9ff;
    }
    &.published {
      color: #52c41a;
      &:hover {
        color: #73d13d;
      }
    }
  }

  &.status-icon {
    &.status-normal {
      color: #52c41a;
    }

    &.status-expired {
      color: #ff4d4f;
    }
  }

  &.expiry-icon {
    color: #1890ff;
  }
}

.empty-indicators {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  color: #999;
  font-size: 13px;
  gap: 8px;
  flex-direction: column;
}

.loading-indicators {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  color: #999;
  font-size: 13px;
}

/* 自定义滚动条 - 隐藏滚动条但保持滚动功能 */
.custom-scrollbar {
  scrollbar-width: none; /* Firefox */
  -ms-overflow-style: none; /* IE 10+ */
}

.custom-scrollbar::-webkit-scrollbar {
  display: none; /* Chrome Safari */
  width: 0;
  height: 0;
}

/* 覆盖 Ant Design 下拉框样式 */
:global(.dark-dropdown) {
  background-color: #fff;
  border: 1px solid #e8e8e8;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}
:global(.dark-dropdown .ant-select-dropdown-menu-item) {
  color: #333;
}
:global(.dark-dropdown .ant-select-dropdown-menu-item:hover) {
  background-color: #f0f2f5;
}
:global(.dark-dropdown .ant-select-dropdown-menu-item-active) {
  background-color: #e6f7ff;
  color: #1890ff;
}
:global(.dark-dropdown .ant-empty-description) {
  color: #999;
}

.symbol-option {
  display: flex;
  align-items: center;
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
}

.empty-watchlist-hint {
  display: flex;
  align-items: center;
  color: #666;
  font-size: 12px;
}

/* 响应式样式 - 手机端 */
@media (max-width: 768px) {
  .chart-container {
    padding: 0;
    width: calc(100% + 44px) !important;
    margin: -22px;
  }

  .chart-header {
    padding: 12px;
    gap: 12px;
    height: auto;
    flex-direction: column;

    .header-top {
      flex-direction: column;
      height: auto;
      padding: 0;
      gap: 12px;
    }

    .header-left {
      width: 100%;
      flex-direction: column;
      gap: 12px;
    }

    .search-section {
      width: 100%;

      .symbol-select {
        width: 100% !important;
      }
    }

    .timeframe-group {
      width: 100%;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 4px;

      .timeframe-item {
        flex: 1;
        min-width: calc(14.28% - 4px); /* 7个按钮，每个占约14.28% */
        text-align: center;
        padding: 6px 8px;
        font-size: 12px;
      }
    }

    .current-symbol {
      display: none; /* 在移动端隐藏header中的币种信息，改用K线图上方的显示 */
    }
  }

  .chart-content {
    flex-direction: column !important;
    height: auto !important;
    min-height: auto !important;
    max-height: none !important;
    overflow-y: auto;
  }

  .chart-main-row {
    flex-direction: column !important;
    height: auto !important;
    min-height: auto !important;
    max-height: none !important;
  }

  .mobile-symbol-price {
    order: 0 !important;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    background: #fff;
    // border-bottom: 1px solid #e8e8e8;
    width: 100%;

    .mobile-price-info {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-direction: row; /* 确保在一行显示 */

      &.color-up { color: #0ecb81; }
      &.color-down { color: #f6465d; }

      .mobile-symbol-price {
        font-size: 18px;
        font-weight: 600;
        font-family: 'Roboto Mono', monospace;
      }

      .mobile-symbol-change {
        font-size: 14px;
        font-weight: 500;
      }
    }
  }

  /* K线图在上方 */
  kline-chart {
    order: 1 !important;
    width: 100% !important;
    flex: 0 0 auto !important;
    display: block !important;
    margin-bottom: 0 !important;
  }

  kline-chart :deep(.chart-left) {
    width: 100% !important;
    height: 350px !important;
    min-height: 350px !important;
    max-height: 350px !important;
    border-right: none !important;
    border-bottom: 1px solid #e8e8e8 !important;
  }

  /* 指标列表在下方 */
  .chart-right {
    order: 2 !important;
    width: 100% !important;
    min-width: 100% !important;
    max-width: 100% !important;
    flex: 0 0 auto !important;
    height: auto !important;
    max-height: calc(100vh - 350px - 120px) !important; /* 减去K线图高度和header高度 */
    border-left: none !important;
    border-top: none !important;
    margin-top: 0 !important;
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;

    .indicators-panel {
      height: auto !important;
      min-height: 600px !important; /* 增加最小高度 */
      max-height: calc(100vh - 350px - 60px) !important; /* 增加高度，减去K线图高度和header高度 */
      overflow: hidden;
      display: flex;
      flex-direction: column;

      .panel-header {
        position: sticky;
        top: 0;
        background: #fff;
        z-index: 10;
        border-bottom: 1px solid #e8e8e8;
        padding: 12px;
        font-size: 14px;
        flex-shrink: 0;

        .mobile-header-create-btn {
          margin-right: 0;
          font-size: 12px;
          height: 28px;
          padding: 0 12px;
        }
      }

      .panel-body {
        padding: 0;
        flex: 1;
        overflow: visible;
        display: flex;
        flex-direction: column;
        min-height: 400px !important;
      }

      .mobile-indicator-tabs {
        flex: 1;
        display: flex;
        flex-direction: column;
        overflow: hidden; /* 防止整个tabs滚动 */
        min-height: 0;
        height: 100%;

        :deep(.ant-tabs-bar) {
          margin-bottom: 0;
          flex-shrink: 0;
          border-bottom: 1px solid #e8e8e8;
        }

        :deep(.ant-tabs-tab) {
          color: #666;
          font-size: 14px;
        }

        :deep(.ant-tabs-tab-active) {
          color: #1890ff;
        }

        :deep(.ant-tabs-ink-bar) {
          background-color: #1890ff;
        }

        :deep(.ant-tabs-content) {
          flex: 1;
          overflow: auto; /* 防止content区域滚动 */
          min-height: 0;
          display: flex;
          flex-direction: column;
          height: 100%;
        }

        :deep(.ant-tabs-tabpane) {
          height: 100%;
          overflow: hidden; /* 防止tabpane滚动 */
          display: none;
          flex-direction: column;
          min-height: 0;
        }

        :deep(.ant-tabs-tabpane-active) {
          display: flex !important;
          flex-direction: column;
          min-height: 0;
          height: 100%;
          overflow: hidden; /* 防止激活的tabpane滚动 */
        }

        :deep(.ant-tabs-content-holder) {
          flex: 1;
          overflow: hidden; /* 防止content-holder滚动 */
          min-height: 0;
          display: flex;
          flex-direction: column;
          height: 100%;
        }

        .mobile-tab-content {
          flex: 1;
          display: flex;
          flex-direction: column;
          overflow: hidden; /* 不在这里滚动，让section-content滚动 */
          min-height: 0;
          height: 100%;
          width: 100%;
        }

        .section-content {
          flex: 1;
          overflow-y: auto !important; /* 只有这里滚动 */
          overflow-x: hidden;
          padding: 12px;
          min-height: 0; /* 使用flex: 1来占据剩余空间 */
          height: 100%; /* 使用100%高度，让flex生效 */
          -webkit-overflow-scrolling: touch;
          position: relative;
        }

        .mobile-create-btn-wrapper {
          display: none !important; /* 手机端不再需要这个wrapper，按钮已移到header */
        }

        .mobile-create-btn {
          display: none !important; /* 手机端不再需要这个按钮，已移到header */
        }
      }

      .indicator-section {
        .section-label {
          padding: 10px 12px;
          font-size: 13px;
        }
      }

      .section-content {
        padding: 10px 12px;
      }

      .indicator-card {
        padding: 10px;

        .card-name {
          font-size: 13px;
        }

        .card-params,
        .card-desc {
          font-size: 11px;
        }
      }
    }
  }
}

/* ========== 暗黑主题样式 ========== */
/* 根据框架主题自动应用暗黑样式 */
/* 当主题为暗色时应用的样式 - 通过组件类名或全局类名 */
.chart-container.theme-dark,
:global(body.dark) .chart-container,
:global(body.realdark) .chart-container,
:global(.ant-layout.dark) .chart-container,
:global(.ant-layout.realdark) .chart-container,
:global(.ant-pro-layout.dark) .chart-container,
:global(.ant-pro-layout.realdark) .chart-container {
  background: #131722;
  color: #d1d4dc;

  .chart-header {
    background: #1e222d;
    border-bottom-color: #2a2e39;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);

    .header-top {
      .current-symbol {
        .symbol-label {
          color: #d1d4dc;
        }

        .market-tag {
          color: #868993;
          background: #2a2e39;
        }

        .price-info {
          &.color-up {
            color: #0ecb81;
          }

          &.color-down {
            color: #f6465d;
          }
        }
      }
    }
  }

  .symbol-select {
    :deep(.ant-select-selection) {
      background-color: #1e222d;
      border-color: #2a2e39;
      color: #d1d4dc;

      &:hover {
        border-color: #1890ff;
      }
    }

    :deep(.ant-select-focused .ant-select-selection) {
      border-color: #1890ff;
      box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.3);
    }

    :deep(.ant-select-arrow) {
      color: #868993;
    }

    :deep(.ant-select-selection__placeholder) {
      color: #868993;
    }
  }

  .timeframe-group {
    background: #2a2e39;

    .timeframe-item {
      color: #868993;

      &:hover {
        color: #1890ff;
        background: #1e222d;
      }

      &.active {
        color: #1890ff;
        background: #1e222d;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
      }
    }
  }

  .mobile-symbol-price {
    background: #1e222d;
    border-bottom-color: #2a2e39;

    .mobile-symbol-label {
      margin-left: 5px;
      color: #d1d4dc;
    }

    .mobile-market-tag {
      color: #868993;
      background: #21283c;
    }

    .mobile-price-info {
      &.color-up {
        color: #0ecb81;
      }

      &.color-down {
        color: #f6465d;
      }
    }
  }

  .chart-right {
    background: #1e222d;
    border-left-color: #2a2e39;

    .indicators-panel {
      background: #1e222d;

      .panel-header {
        background: #1e222d;
        border-bottom-color: #2a2e39;
        color: #d1d4dc;

        .realtime-toggle-btn {
          color: #868993;

          &:hover {
            color: #1890ff;
            background: #2a2e39;
          }

          &.active {
            color: #1890ff;
            background: #2a2e39;
          }
        }
      }

      .panel-body {
        background: #1e222d;
      }

      .indicator-section {
        border-bottom-color: #2a2e39;
      }

      .section-label {
        color: #868993;
        background: #2a2e39;
        border-bottom-color: #2a2e39;

        .section-label-left {
          .collapse-icon {
            color: #868993;
          }

          span {
            color: #d1d4dc;
          }
        }

        .buy-indicator-btn {
          color: #1890ff;

          &:hover {
            color: #40a9ff;
          }
        }
      }

      .indicator-card {
        background: #1e222d;
        border-color: #2a2e39;

        &:hover {
          background: #2a2e39;
          border-color: #1890ff;
        }

        &.active {
          background: #2a2e39;
          border-color: #1890ff;

          .card-name {
            color: #1890ff;
          }
        }

        &.indicator-active {
          border-color: #52c41a;
          background: #1e3a1e;

          &:hover {
            border-color: #73d13d;
            box-shadow: 0 2px 8px rgba(82, 196, 26, 0.3);
          }

          .card-name {
            color: #52c41a;
          }
        }

        .card-name {
          color: #d1d4dc;
        }

        .card-params,
        .card-desc {
          color: #868993;
        }

        .action-icon {
          color: #868993;

          &:hover {
            color: #1890ff;
          }

          &.edit-icon {
            color: #1890ff;

            &:hover {
              color: #40a9ff;
            }
          }

          &.delete-icon {
            color: #ff4d4f;

            &:hover {
              color: #ff7875;
            }
          }

          &.backtest-icon {
            color: #b37feb;

            &:hover {
              color: #d3adf7;
            }
          }
          &.backtest-history-icon {
            color: #5cdbd3;
            &:hover {
              color: #87e8de;
            }
          }

          &.publish-icon {
            color: #1890ff;
            &:hover {
              color: #40a9ff;
            }
            &.published {
              color: #52c41a;
              &:hover {
                color: #73d13d;
              }
            }
          }

          &.toggle-icon.active {
            color: #52c41a;
          }
        }
      }

      .empty-indicators {
        color: #868993;
      }
    }
  }

  /* 移动端适配 */
  @media (max-width: 768px) {
    .chart-header {
      background: #1e222d;
      border-bottom-color: #2a2e39;

      .current-symbol {
        border-top-color: #2a2e39;
      }
    }

    .chart-left {
      border-bottom-color: #2a2e39;
    }

    .chart-right {
      border-top-color: #2a2e39;
      max-height: 500px !important;
      .indicators-panel {
        .panel-header {
          background: #1e222d;
          border-bottom-color: #2a2e39;
        }

        .mobile-indicator-tabs {
          :deep(.ant-tabs-bar) {
            border-bottom-color: #2a2e39;
          }

          :deep(.ant-tabs-tab) {
            color: #868993;
          }

          :deep(.ant-tabs-tab-active) {
            color: #1890ff;
          }

          :deep(.ant-tabs-ink-bar) {
            background-color: #1890ff;
          }

          .mobile-create-btn-wrapper {
            background: #1e222d;
          }
        }
      }
    }

    .mobile-symbol-price {
      background: #1e222d;
      border-bottom-color: #2a2e39;

      .mobile-symbol-label {
        margin-left: 5px;
        color: #d1d4dc;
      }

      .mobile-market-tag {
        color: #868993;
        background: #2a3932;
      }

      .mobile-price-info {
        &.color-up {
          color: #0ecb81;
        }

        &.color-down {
          color: #f6465d;
        }
      }
    }
  }
}

/* 添加股票弹窗样式 */
.add-stock-modal-content {
  .market-tabs {
    margin-bottom: 16px;
  }

  .symbol-search-section {
    margin-bottom: 24px;
  }

  .search-results-section,
  .hot-symbols-section {
    margin-bottom: 24px;

    .section-title {
      font-size: 14px;
      font-weight: 600;
      color: #262626;
      margin-bottom: 12px;
      display: flex;
      align-items: center;
    }
  }

  .symbol-list {
    max-height: 200px;
    overflow-y: auto;
    border: 1px solid #e8e8e8;
    border-radius: 4px;

    .symbol-list-item {
      cursor: pointer;
      padding: 8px 12px;
      transition: background-color 0.3s;

      &:hover {
        background-color: #f5f5f5;
      }

      .symbol-item-content {
        display: flex;
        align-items: center;
        gap: 8px;

        .symbol-code {
          font-weight: 600;
          color: #262626;
          min-width: 80px;
        }

        .symbol-name {
          color: #595959;
          flex: 1;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
      }
    }
  }

  .selected-symbol-section {
    margin-top: 16px;

    .selected-symbol-info {
      display: flex;
      align-items: center;
    }
  }

}

/* 暗黑主题下的弹窗样式 */
.chart-container.theme-dark,
:global(body.dark) .chart-container,
:global(body.realdark) .chart-container {
  .add-stock-modal-content {
    .search-results-section,
    .hot-symbols-section {
      .section-title {
        color: #d1d4dc;
      }
    }

    .symbol-list {
      border-color: #363c4e;
      background-color: #2a2e39;

      .symbol-list-item {
        &:hover {
          background-color: #363c4e;
        }

        .symbol-item-content {
          .symbol-code {
            color: #d1d4dc;
          }

          .symbol-name {
            color: #868993;
          }
        }
      }
    }
  }
}

/* 指标参数配置弹窗 */
.params-config-modal {
  .indicator-info {
    text-align: center;
    margin-bottom: 8px;

    .indicator-name {
      font-size: 16px;
      font-weight: 600;
      color: #1f1f1f;
    }
  }

  .params-form {
    .param-item {
      margin-bottom: 16px;

      .param-header {
        display: flex;
        align-items: center;
        margin-bottom: 6px;

        .param-label {
          font-weight: 500;
          color: #333;
        }
      }
    }
  }
}

.theme-dark .params-config-modal {
  .indicator-info .indicator-name {
    color: #e0e0e0;
  }

  .params-form .param-item .param-header .param-label {
    color: #d0d0d0;
  }
}
</style>
