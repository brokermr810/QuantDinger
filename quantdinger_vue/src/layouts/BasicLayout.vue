<template>
  <div :class="['basic-layout-wrapper', settings.theme]">
    <pro-layout
      :menus="menus"
      :collapsed="collapsed"
      :mediaQuery="query"
      :isMobile="isMobile"
      :handleMediaQuery="handleMediaQuery"
      :handleCollapse="handleCollapse"
      :i18nRender="i18nRender"
      v-bind="settings"
    >

      <template #menuHeaderRender>
        <div>
          <img src="~@/assets/slogo.png" />
          <h1>{{ title }}</h1>
        </div>
      </template>
      <!-- 1.0.0+ 版本 pro-layout 提供 API,
          增加 Header 左侧内容区自定义
    -->
      <template #headerContentRender>
        <div>
          <a-tooltip :title="$t('menu.header.refreshPage')">
            <a-icon type="reload" style="font-size: 18px;cursor: pointer;" @click="handleRefresh" />
          </a-tooltip>
        </div>
      </template>

      <!-- 用户协议弹窗 -->
      <a-modal :visible="showLegalModal" :footer="null" :title="$t('menu.footer.userAgreement')" @cancel="showLegalModal = false" :width="800">
        <div style="max-height: 60vh; overflow: auto; white-space: pre-wrap; line-height: 1.8; padding: 16px;">
          {{ menuFooterConfig.legal.user_agreement || $t('user.login.legal.content') }}
        </div>
        <div style="margin-top: 12px; text-align: right;">
          <a-button type="primary" @click="showLegalModal = false">OK</a-button>
        </div>
      </a-modal>

      <!-- 隐私条例弹窗 -->
      <a-modal :visible="showPrivacyModal" :footer="null" :title="$t('menu.footer.privacyPolicy')" @cancel="showPrivacyModal = false" :width="800">
        <div style="max-height: 60vh; overflow: auto; white-space: pre-wrap; line-height: 1.8; padding: 16px;">
          {{ menuFooterConfig.legal.privacy_policy || $t('user.login.privacy.content') }}
        </div>
        <div style="margin-top: 12px; text-align: right;">
          <a-button type="primary" @click="showPrivacyModal = false">OK</a-button>
        </div>
      </a-modal>

      <setting-drawer ref="settingDrawer" :settings="settings" @change="handleSettingChange">
        <div style="margin: 12px 0;">
          This is SettingDrawer custom footer content.
        </div>
      </setting-drawer>
      <template #rightContentRender>
        <right-content :top-menu="settings.layout === 'topmenu'" :is-mobile="isMobile" :theme="settings.theme" />
      </template>
      <!-- custom footer removed -->
      <template #footerRender>
        <div style="display: none;"></div>
      </template>
      <router-view :key="refreshKey" />
    </pro-layout>

    <!-- 菜单底部 footer - 直接写，不依赖插槽 -->
    <div class="custom-menu-footer" :class="{ 'collapsed': collapsed, 'drawer-open': isMobile && isDrawerOpen, 'drawer-animating': isMobile && isDrawerAnimating }">
      <div v-if="!collapsed" class="menu-footer-content">
        <!-- 联系我们 -->
        <div class="footer-section">
          <div class="section-title">{{ $t('menu.footer.contactUs') }}</div>
          <div class="section-links">
            <a :href="menuFooterConfig.contact.support_url" target="_blank">{{ $t('menu.footer.support') }}</a>
            <span class="separator">|</span>
            <a :href="menuFooterConfig.contact.feature_request_url" target="_blank">{{ $t('menu.footer.featureRequest') }}</a>
          </div>
        </div>

        <!-- 获取支持 -->
        <div class="footer-section">
          <div class="section-title">{{ $t('menu.footer.getSupport') }}</div>
          <div class="section-links">
            <a :href="'mailto:' + menuFooterConfig.contact.email">{{ $t('menu.footer.email') }}</a>
            <span class="separator">|</span>
            <a :href="menuFooterConfig.contact.live_chat_url" target="_blank">{{ $t('menu.footer.liveChat') }}</a>
          </div>
        </div>

        <!-- 社交账户 -->
        <div class="footer-section" v-if="menuFooterConfig.social_accounts && menuFooterConfig.social_accounts.length > 0">
          <div class="section-title">{{ $t('menu.footer.socialAccounts') }}</div>
          <div class="social-icons">
            <a
              v-for="(account, index) in menuFooterConfig.social_accounts"
              :key="index"
              :href="account.url"
              target="_blank"
              rel="noopener noreferrer"
              :title="account.name"
              class="social-icon"
            >
              <Icon :icon="`simple-icons:${account.icon}`" class="social-icon-svg" />
            </a>
          </div>
        </div>

        <!-- 用户协议和隐私条例 -->
        <div class="footer-section">
          <div class="section-links">
            <a @click="showLegalModal = true">{{ $t('menu.footer.userAgreement') }}</a>
            <span class="separator">&</span>
            <a @click="showPrivacyModal = true">{{ $t('menu.footer.privacyPolicy') }}</a>
          </div>
        </div>

        <!-- 版权信息 -->
        <div class="footer-section copyright">
          {{ menuFooterConfig.copyright }}
        </div>
        <!-- 版本号 -->
        <div class="footer-section version">
          V2.1.2
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { updateTheme } from '@/components/SettingDrawer/settingConfig'
import { i18nRender } from '@/locales'
import { mapState } from 'vuex'
import {
  CONTENT_WIDTH_TYPE,
  SIDEBAR_TYPE,
  TOGGLE_MOBILE_TYPE,
  TOGGLE_NAV_THEME,
  TOGGLE_LAYOUT,
  TOGGLE_FIXED_HEADER,
  TOGGLE_FIXED_SIDEBAR,
  TOGGLE_CONTENT_WIDTH,
  TOGGLE_HIDE_HEADER,
  TOGGLE_COLOR,
  TOGGLE_WEAK,
  TOGGLE_MULTI_TAB
} from '@/store/mutation-types'

import defaultSettings from '@/config/defaultSettings'
import RightContent from '@/components/GlobalHeader/RightContent'
import SettingDrawer from '@/components/SettingDrawer/SettingDrawer'
import { Icon } from '@iconify/vue2'

export default {
  name: 'BasicLayout',
  components: {
    SettingDrawer,
    RightContent,
    Icon
    // GlobalFooter,
    // Ads
  },
  data () {
    return {
      // preview.pro.antdv.com only use.
      isProPreviewSite: process.env.VUE_APP_PREVIEW === 'true' && process.env.NODE_ENV !== 'development',
      // end
      isDev: process.env.NODE_ENV === 'development' || process.env.VUE_APP_PREVIEW === 'true',

      // base - menus moved to computed property
      // 侧栏收起状态
      collapsed: false,
      title: defaultSettings.title,
      settings: {
        // 布局类型
        layout: defaultSettings.layout, // 'sidemenu', 'topmenu'
        // CONTENT_WIDTH_TYPE
        contentWidth: defaultSettings.layout === 'sidemenu' ? CONTENT_WIDTH_TYPE.Fluid : defaultSettings.contentWidth,
        // 主题 'dark' | 'light'
        theme: defaultSettings.navTheme,
        // 主色调
        primaryColor: defaultSettings.primaryColor,
        fixedHeader: defaultSettings.fixedHeader,
        fixSiderbar: defaultSettings.fixSiderbar,
        colorWeak: defaultSettings.colorWeak,

        hideHintAlert: false,
        hideCopyButton: false
      },
      // 媒体查询
      query: {},

      // 是否手机模式
      isMobile: false,
      // 法律免责声明弹窗显示状态
      showLegalModal: false,
      showPrivacyModal: false,
      // 用于刷新内容区域的 key
      refreshKey: 0,
      // drawer 是否打开（手机端）
      isDrawerOpen: false,
      // drawer 是否正在动画中（手机端）
      isDrawerAnimating: false,
      // Static footer config (local OSS build)
      menuFooterConfig: {
        contact: {
          support_url: 'https://t.me/quantdinger',
          feature_request_url: 'https://github.com/brokermr810/QuantDinger/issues',
          email: 'brokermr810@gmail.com',
          live_chat_url: 'https://t.me/quantdinger'
        },
        social_accounts: [
          { name: 'GitHub', icon: 'github', url: 'https://github.com/brokermr810/QuantDinger' },
          { name: 'X', icon: 'x', url: 'https://x.com/HenryCryption' },
          { name: 'Discord', icon: 'discord', url: 'https://discord.gg/cn6HVE2KC' },
          { name: 'Telegram', icon: 'telegram', url: 'https://t.me/quantdinger' },
          { name: 'YouTube', icon: 'youtube', url: 'https://youtube.com/@quantdinger' }
        ],
        legal: {
          user_agreement: '',
          privacy_policy: ''
        },
        copyright: '© 2025-2026 QuantDinger. All rights reserved.'
      },
      // 是否是首次初始化主题色（用于决定是否显示"正在切换主题"提示）
      isInitialThemeColorLoad: true
    }
  },
  computed: {
    ...mapState({
      // 动态主路由
      mainMenu: state => state.permission.addRouters
    }),
    // 响应式菜单 - 根据 addRouters 动态更新
    menus () {
      const routes = this.mainMenu.find(item => item.path === '/')
      return (routes && routes.children) || []
    }
  },
  created () {
    // menus is now a computed property - no need to set here
    // 从 store 同步主题设置（从 localStorage 恢复）
    this.settings.theme = this.$store.state.app.theme
    this.settings.primaryColor = this.$store.state.app.color || defaultSettings.primaryColor
    // 处理侧栏收起状态
    this.$watch('collapsed', () => {
      this.$store.commit(SIDEBAR_TYPE, this.collapsed)
    })
    this.$watch('isMobile', () => {
      this.$store.commit(TOGGLE_MOBILE_TYPE, this.isMobile)
    })
    // 监听 store 中的主题变化，同步到 settings 和 body 类名
    this.$watch('$store.state.app.theme', (val) => {
      this.settings.theme = val
      if (val === 'dark' || val === 'realdark') {
        document.body.classList.add('dark')
        document.body.classList.remove('light')
      } else {
        document.body.classList.remove('dark')
        document.body.classList.add('light')
      }
    }, { immediate: true })
    // 监听 store 中的主题色变化，同步到 settings
    this.$watch('$store.state.app.color', (val) => {
      if (val) {
        this.settings.primaryColor = val
        // 应用主题色
        if (process.env.NODE_ENV !== 'production' || process.env.VUE_APP_PREVIEW === 'true') {
          // 首次加载时静默更新，不显示"正在切换主题"提示
          updateTheme(val, this.isInitialThemeColorLoad)
          // 首次调用后，将标志设为 false
          if (this.isInitialThemeColorLoad) {
            this.isInitialThemeColorLoad = false
          }
        }
      }
    }, { immediate: true })
    // 监听 settings.theme 变化，同步 body 类名（作为额外保障）
    this.$watch('settings.theme', (val) => {
      if (val === 'dark' || val === 'realdark') {
        document.body.classList.add('dark')
        document.body.classList.remove('light')
      } else {
        document.body.classList.remove('dark')
        document.body.classList.add('light')
      }
    }, { immediate: true })
  },
  mounted () {
    const userAgent = navigator.userAgent
    if (userAgent.indexOf('Edge') > -1) {
      this.$nextTick(() => {
        this.collapsed = !this.collapsed
        setTimeout(() => {
          this.collapsed = !this.collapsed
        }, 16)
      })
    }

    // first update color
    // TIPS: THEME COLOR HANDLER!! PLEASE CHECK THAT!!
    // 注意：主题色更新已在 created() 的 watch 中处理，这里不再重复调用
    // 避免显示两次"正在切换主题"提示

    // 监听显示设置抽屉事件
    this.$root.$on('show-setting-drawer', () => {
      if (this.$refs.settingDrawer) {
        this.$refs.settingDrawer.showDrawer()
      }
    })

    // Footer config is static for local OSS build

    // 更新菜单底部位置（延迟执行，确保 DOM 已渲染）
    this.$nextTick(() => {
      setTimeout(() => {
        this.updateMenuFooterPosition()
      }, 200)
    })

    // 监听窗口大小变化
    window.addEventListener('resize', this.updateMenuFooterPosition)

    // 桌面端：定期检查并更新 footer 位置（确保能显示）
    if (!this.isMobile) {
      this._desktopFooterInterval = setInterval(() => {
        this.updateMenuFooterPosition()
      }, 1000)
    }

    // 监听手机端菜单 drawer 的打开/关闭
    // 使用 MutationObserver 监听 drawer 的显示/隐藏
    const observer = new MutationObserver(() => {
      if (this.isMobile) {
        // 检查 drawer 是否打开
        const drawer = document.querySelector('.ant-drawer.ant-drawer-open')
        const wasOpen = this.isDrawerOpen
        const isOpen = !!drawer

        this.isDrawerOpen = isOpen

        // 如果状态改变，更新 footer 位置
        if (wasOpen !== this.isDrawerOpen) {
          if (this.isDrawerOpen) {
            // drawer 刚打开，标记为动画中，延迟显示 footer
            this.isDrawerAnimating = true
            // 等待 drawer 动画完成（Ant Design Drawer 动画时间是 0.3s）
            setTimeout(() => {
              this.isDrawerAnimating = false
              this.updateMenuFooterPosition()
            }, 300)
          } else {
            // drawer 关闭，立即隐藏 footer
            this.isDrawerAnimating = false
            this.updateMenuFooterPosition()
          }
        }
      }
    })

    // 观察 body 的变化，检测 drawer 的添加/移除和 class 变化
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['class']
    })

    // 保存 observer 以便清理
    this._menuFooterObserver = observer

    // 定期检查（作为备用方案，确保 footer 位置正确）
    this._menuFooterInterval = setInterval(() => {
      if (this.isMobile) {
        const drawer = document.querySelector('.ant-drawer.ant-drawer-open')
        const currentState = !!drawer
        if (this.isDrawerOpen !== currentState) {
          this.isDrawerOpen = currentState
          // 如果 drawer 刚打开，标记为动画中
          if (currentState) {
            this.isDrawerAnimating = true
            setTimeout(() => {
              this.isDrawerAnimating = false
              this.updateMenuFooterPosition()
            }, 300)
          } else {
            this.isDrawerAnimating = false
            this.updateMenuFooterPosition()
          }
        } else if (currentState && !this.isDrawerAnimating) {
          // drawer 已打开且不在动画中，更新位置（防止 drawer 位置变化）
          this.updateMenuFooterPosition()
        }
      }
    }, 200)
  },
  beforeDestroy () {
    // 移除事件监听
    this.$root.$off('show-setting-drawer')
    window.removeEventListener('resize', this.updateMenuFooterPosition)

    // 清理 MutationObserver
    if (this._menuFooterObserver) {
      this._menuFooterObserver.disconnect()
    }

    // 清理定时器
    if (this._menuFooterInterval) {
      clearInterval(this._menuFooterInterval)
    }

    // 清理桌面端定时器
    if (this._desktopFooterInterval) {
      clearInterval(this._desktopFooterInterval)
    }
  },
  methods: {
    i18nRender,
    updateMenuFooterPosition () {
      this.$nextTick(() => {
        // 使用 requestAnimationFrame 确保在浏览器下一次重绘前更新，避免打断 CSS 过渡
        requestAnimationFrame(() => {
          const menuFooter = this.$el?.querySelector('.custom-menu-footer')
          if (!menuFooter) return

          // 手机端：查找抽屉菜单容器
          if (this.isMobile) {
            const drawer = document.querySelector('.ant-drawer.ant-drawer-open')
            this.isDrawerOpen = !!drawer

            if (drawer && !this.isDrawerAnimating) {
              // const drawerRect = drawer.getBoundingClientRect()
              menuFooter.style.position = 'fixed'
              // menuFooter.style.left = `${drawerRect.left}px`
              // 宽度由 CSS 的 .collapsed 类控制，不在这里设置
              menuFooter.style.bottom = '0px'
              menuFooter.style.zIndex = '1001'
              menuFooter.style.display = 'block'
              menuFooter.style.opacity = '1'

              // 动态计算footer高度，并设置drawer body的padding
              const footerHeight = menuFooter.offsetHeight || 280
              const drawerBody = drawer.querySelector('.ant-drawer-body')
              if (drawerBody) {
                // 设置CSS变量，供CSS使用
                drawer.style.setProperty('--footer-height', `${footerHeight}px`)
                // 直接设置padding-bottom，确保菜单内容不被遮挡
                drawerBody.style.paddingBottom = `${footerHeight + 10}px`
                // 确保drawer body可以滚动
                drawerBody.style.overflowY = 'auto'
                drawerBody.style.overflowX = 'hidden'
                drawerBody.style.webkitOverflowScrolling = 'touch'
              }

              return
            } else if (drawer && this.isDrawerAnimating) {
              // drawer 正在动画中，footer 应该隐藏或透明
              menuFooter.style.opacity = '0'
              menuFooter.style.display = 'block'
              return
            } else {
              menuFooter.style.display = 'none'
              menuFooter.style.opacity = '0'
              // 清除drawer body的padding
              const drawer = document.querySelector('.ant-drawer')
              if (drawer) {
                const drawerBody = drawer.querySelector('.ant-drawer-body')
                if (drawerBody) {
                  drawerBody.style.paddingBottom = ''
                  drawerBody.style.overflowY = ''
                  drawerBody.style.overflowX = ''
                }
              }
              return
            }
          }

          // 桌面端：查找普通菜单容器
          const sider = this.$el?.querySelector('.ant-pro-sider') || document.querySelector('.ant-pro-sider')
          if (sider) {
            const siderRect = sider.getBoundingClientRect()
          const footerHeight = menuFooter.offsetHeight || 220
            menuFooter.style.position = 'fixed'
            menuFooter.style.left = `${siderRect.left}px`
            // 宽度由 CSS 的 .collapsed 类控制，不在这里设置
            menuFooter.style.bottom = '0px'
            menuFooter.style.zIndex = '100'
            menuFooter.style.display = 'block'
          // 将 footer 高度写入 CSS 变量，方便样式中使用
          sider.style.setProperty('--menu-footer-height', `${footerHeight}px`)
          // 给侧栏主体预留出 footer 的高度，并允许滚动
          const siderChildren = sider.querySelector('.ant-layout-sider-children')
          if (siderChildren) {
            siderChildren.style.paddingBottom = `${footerHeight + 12}px`
            siderChildren.style.overflowY = 'auto'
            siderChildren.style.overflowX = 'hidden'
            siderChildren.style.webkitOverflowScrolling = 'touch'
          }
          // 进一步限制菜单区域高度，避免 footer 遮挡
          const menuScroll = sider.querySelector('.ant-pro-sider-menu') ||
            sider.querySelector('.ant-menu-root') ||
            sider.querySelector('.ant-menu')
          if (menuScroll) {
            const availableHeight = Math.max(siderRect.height - footerHeight - 12, 120)
            menuScroll.style.maxHeight = `${availableHeight}px`
            menuScroll.style.overflowY = 'auto'
            menuScroll.style.overflowX = 'hidden'
            menuScroll.style.webkitOverflowScrolling = 'touch'
          }
          } else {
            // 如果找不到菜单，使用默认位置
            menuFooter.style.position = 'fixed'
            menuFooter.style.left = '0px'
            // 宽度由 CSS 的 .collapsed 类控制
            menuFooter.style.bottom = '0px'
            menuFooter.style.zIndex = '100'
            menuFooter.style.display = 'block'
          }
        })
      })
    },
    handleRefresh () {
      // 只刷新内容区域，通过改变 key 强制重新渲染 router-view
      this.refreshKey += 1
    },
    handleMediaQuery (val) {
      this.query = val
      if (this.isMobile && !val['screen-xs']) {
        this.isMobile = false
        this.$nextTick(() => {
          this.updateMenuFooterPosition()
        })
        return
      }
      if (!this.isMobile && val['screen-xs']) {
        this.isMobile = true
        this.collapsed = false
        this.settings.contentWidth = CONTENT_WIDTH_TYPE.Fluid
        // this.settings.fixSiderbar = false
        this.$nextTick(() => {
          this.updateMenuFooterPosition()
        })
      }
    },
    handleCollapse (val) {
      this.collapsed = val
      // 菜单折叠状态改变时，更新底部位置
      // CSS transition 会自动处理宽度和位置的平滑过渡
      this.$nextTick(() => {
        this.updateMenuFooterPosition()
      })
    },
    handleMobileMenuToggle () {
      // 监听手机端菜单打开/关闭
      this.$nextTick(() => {
        setTimeout(() => {
          this.updateMenuFooterPosition()
        }, 300) // 等待 drawer 动画完成
      })
    },
    handleSettingChange ({ type, value }) {
      type && (this.settings[type] = value)
      switch (type) {
        case 'theme':
          this.$store.commit(TOGGLE_NAV_THEME, value)
          break
        case 'primaryColor':
          this.$store.commit(TOGGLE_COLOR, value)
          break
        case 'layout':
          this.$store.commit(TOGGLE_LAYOUT, value)
          if (value === 'sidemenu') {
            this.settings.contentWidth = CONTENT_WIDTH_TYPE.Fluid
          } else {
            this.settings.fixSiderbar = false
            this.settings.contentWidth = CONTENT_WIDTH_TYPE.Fixed
          }
          break
        case 'contentWidth':
          this.settings[type] = value
          this.$store.commit(TOGGLE_CONTENT_WIDTH, value)
          break
        case 'fixedHeader':
          this.$store.commit(TOGGLE_FIXED_HEADER, value)
          break
        case 'autoHideHeader':
          this.$store.commit(TOGGLE_HIDE_HEADER, value)
          break
        case 'fixSiderbar':
          this.$store.commit(TOGGLE_FIXED_SIDEBAR, value)
          break
        case 'colorWeak':
          this.$store.commit(TOGGLE_WEAK, value)
          break
        case 'multiTab':
          this.$store.commit(TOGGLE_MULTI_TAB, value)
          break
      }
    }
  }
}
</script>

<style lang="less">
@import "./BasicLayout.less";
.ant-pro-sider-menu-sider.light .ant-menu-light {
  height: 60vh!important;
}
/* 完全隐藏所有 footer */
.basic-layout-wrapper {
  .ant-layout-footer {
    display: none !important;
    height: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
    border: none !important;
  }
}

/* 菜单底部 footer 样式 - 直接定位到菜单底部 */
.basic-layout-wrapper {
  position: relative;

  /* 自定义菜单底部 - 通过 CSS 选择器定位到菜单区域 */
  .custom-menu-footer {
    position: fixed;
    bottom: 0;
    left: 0;
    z-index: 100;
    width: 256px; /* 统一固定宽度 256px */
    background: #001529; /* 默认暗色背景 */
    border-top: 1px solid rgba(255, 255, 255, 0.1);
    /* 与菜单栏抽屉动画同步：使用相同的过渡时间和缓动函数 */
    /* Ant Design Vue Drawer 使用 0.3s 和 cubic-bezier(0.78, 0.14, 0.15, 0.86) */
    transition: left 0.3s cubic-bezier(0.78, 0.14, 0.15, 0.86),
                width 0.3s cubic-bezier(0.78, 0.14, 0.15, 0.86),
                max-width 0.3s cubic-bezier(0.78, 0.14, 0.15, 0.86),
                opacity 0.3s cubic-bezier(0.78, 0.14, 0.15, 0.86);
    max-width: 256px;
    display: block; /* 默认显示 */
    opacity: 1;

    &.collapsed {
      width: 80px; /* 折叠时菜单宽度 */
      max-width: 80px;
    }

    /* 手机端：当菜单在 drawer 中时，需要更高的 z-index */
    @media (max-width: 768px) {
      z-index: 1001; /* drawer 的 z-index 通常是 1000 */

      /* 当 drawer 未打开时，隐藏 footer */
      &:not(.drawer-open) {
        display: none !important;
        opacity: 0;
      }

      /* 当 drawer 正在动画中时，footer 应该透明，等待动画完成 */
      &.drawer-animating {
        opacity: 0;
        transition: opacity 0.1s ease-out;
      }

      /* 当 drawer 完全打开且不在动画中时，footer 才显示 */
      &.drawer-open:not(.drawer-animating) {
        opacity: 1;
        transition: left 0.3s cubic-bezier(0.78, 0.14, 0.15, 0.86),
                    width 0.3s cubic-bezier(0.78, 0.14, 0.15, 0.86),
                    max-width 0.3s cubic-bezier(0.78, 0.14, 0.15, 0.86),
                    opacity 0.3s cubic-bezier(0.78, 0.14, 0.15, 0.86) 0.1s; /* 延迟 0.1s 显示，确保 drawer 先出现 */
      }
    }

    /* 浅色主题 */
    body.light &,
    .ant-pro-layout.light & {
      background: #fff;
      border-top-color: #e8e8e8;
      color: rgba(0, 0, 0, 0.85);

      .menu-footer-content {
        .footer-section {
          .section-links a {
            color: rgba(0, 0, 0, 0.65);
          }
        }
        .social-icon {
          background: rgba(0, 0, 0, 0.05);
          color: rgba(0, 0, 0, 0.65);
          &:hover {
            background: rgba(0, 0, 0, 0.1);
            color: rgba(0, 0, 0, 0.85);
          }
          .social-icon-svg {
            color: currentColor;
          }
        }
      }
    }

    /* 暗黑主题 */
    body.dark &,
    body.realdark &,
    .ant-pro-layout.dark &,
    .ant-pro-layout.realdark & {
      background: #001529;
      border-top-color: rgba(255, 255, 255, 0.1);
      color: rgba(255, 255, 255, 0.65);

      .menu-footer-content {
        .footer-section {
          .section-links a {
            color: rgba(255, 255, 255, 0.65);
          }
        }
        .social-icon {
          background: rgba(255, 255, 255, 0.05);
          color: rgba(255, 255, 255, 0.65);
          &:hover {
            background: rgba(255, 255, 255, 0.1);
            color: rgba(255, 255, 255, 0.85);
          }
          .social-icon-svg {
            color: currentColor;
          }
        }
      }
    }

    .menu-footer-content {
      padding: 12px 16px;
      font-size: 11px;
      color: inherit;
      max-height: 30vh;
      overflow-y: auto;
      overflow-x: hidden;

      /* 隐藏滚动条但保持滚动功能 */
      scrollbar-width: thin;
      scrollbar-color: rgba(255, 255, 255, 0.2) transparent;
      &::-webkit-scrollbar {
        width: 4px;
      }
      &::-webkit-scrollbar-track {
        background: transparent;
      }
      &::-webkit-scrollbar-thumb {
        background: rgba(255, 255, 255, 0.2);
        border-radius: 2px;
      }

      .footer-section {
        margin-bottom: 12px;
        text-align: center;

        &:last-child {
          margin-bottom: 0;
        }

        .section-title {
          font-size: 11px;
          font-weight: 500;
          margin-bottom: 6px;
          opacity: 0.8;
          color: inherit;
        }

        .section-links {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 4px;
          flex-wrap: wrap;
          font-size: 10px;
          opacity: 0.7;

          a {
            cursor: pointer;
            color: inherit;
            text-decoration: underline;
            transition: opacity 0.2s;

            &:hover {
              opacity: 1;
            }
          }

          .separator {
            opacity: 0.5;
            margin: 0 2px;
          }
        }

        .social-icons {
          display: flex;
          flex-wrap: wrap;
          justify-content: center;
          gap: 8px;
          margin-top: 6px;

          .social-icon {
            width: 15px;
            height: 15px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 4px;
            cursor: pointer;
            opacity: 0.7;
            transition: all 0.2s;
            background: rgba(255, 255, 255, 0.05);
            text-decoration: none;
            overflow: hidden;

            &:hover {
              opacity: 1;
              background: rgba(255, 255, 255, 0.1);
              transform: translateY(-2px);
            }

            .social-icon-svg {
              width: 15x;
              height: 15px;
              color: currentColor;
            }

            .anticon {
              font-size: 16px;
            }

            .social-logo {
              width: 15px;
              height: 15px;
              object-fit: contain;
            }

            .social-icon-text {
              font-size: 10px;
              font-weight: bold;
            }
          }
        }

        &.copyright {
          margin-top: 12px;
          padding-top: 12px;
          border-top: 1px solid rgba(255, 255, 255, 0.1);
          opacity: 0.6;
          font-size: 10px;
        }

        &.version {
          margin-top: 4px;
          font-size: 9px;
          opacity: 0.4;
          text-align: center;
          letter-spacing: 1px;
        }
      }
    }

    .menu-footer-content-collapsed {
      text-align: center;
      padding: 16px;
      font-size: 12px;
      opacity: 0.6;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;

      .anticon {
        font-size: 16px;
      }

      &:hover {
        opacity: 1;
      }
    }
  }

  /* 监听菜单折叠状态，动态调整宽度 */
  ::v-deep .ant-pro-layout {
    &.ant-pro-sider-collapsed ~ .custom-menu-footer,
    .ant-pro-sider-collapsed ~ .custom-menu-footer {
      width: 80px;
    }
  }
}

/* 侧栏菜单滚动 & 为自定义 footer 预留空间 */
.basic-layout-wrapper {
  .ant-layout-sider-children {
    padding-bottom: calc(var(--menu-footer-height, 220px) + 12px);
    overflow-y: auto;
    overflow-x: hidden;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: thin;
    scrollbar-color: rgba(0, 0, 0, 0.15) transparent;

    &::-webkit-scrollbar {
      width: 6px;
    }

    &::-webkit-scrollbar-track {
      background: transparent;
    }

    &::-webkit-scrollbar-thumb {
      background: rgba(0, 0, 0, 0.15);
      border-radius: 3px;
    }

    body.dark &,
    body.realdark &,
    .ant-pro-layout.dark &,
    .ant-pro-layout.realdark & {
      scrollbar-color: rgba(255, 255, 255, 0.25) transparent;

      &::-webkit-scrollbar-thumb {
        background: rgba(255, 255, 255, 0.25);
      }
    }
  }

  /* 强制侧栏和菜单区域可滚动，避免被 footer 遮挡 */
  .ant-pro-sider {
    height: 100vh;
    display: flex;
    flex-direction: column;

    .ant-layout-sider-children {
      flex: 1 1 auto;
      min-height: 0;
      display: flex;
      flex-direction: column;
    }

    .ant-pro-sider-menu,
    .ant-menu-root,
    .ant-menu {
      flex: 1 1 auto;
      min-height: 0;
      max-height: calc(100vh - var(--menu-footer-height, 220px) - 24px);
      overflow-y: auto !important;
      overflow-x: hidden;
      -webkit-overflow-scrolling: touch;
    }
  }
}

/* 暗黑主题样式 */
.basic-layout-wrapper.dark,
.basic-layout-wrapper.realdark {
  /* Header 适配 */
  .ant-pro-global-header {
    background: #001529 !important;
    color: rgba(255, 255, 255, 0.85) !important;

    .ant-pro-global-header-trigger {
      color: rgba(255, 255, 255, 0.85) !important;
      &:hover {
        background: rgba(255, 255, 255, 0.03) !important;
      }
    }

    .action {
      color: rgba(255, 255, 255, 0.85) !important;
      &:hover {
        background: rgba(255, 255, 255, 0.03) !important;
      }
    }
  }

  /* Content 适配 */
  .ant-pro-basicLayout-content {
    background-color: #141414 !important;
  }

  /* 确保 Layout 本身也是深色 */
  .ant-layout {
    background-color: #141414 !important;
  }
}

/* 手机端：修复footer遮挡菜单的问题 */
@media (max-width: 768px) {
  /* 让drawer body可以滚动，并添加底部padding避免被footer遮挡 */
  .ant-drawer.ant-drawer-open {
    /* 确保drawer容器可以正常显示 */
    .ant-drawer-content-wrapper {
      overflow: visible;
    }

    .ant-drawer-content {
      display: flex;
      flex-direction: column;
      height: 100%;
      overflow: visible;
    }

    .ant-drawer-wrapper-body {
      display: flex;
      flex-direction: column;
      height: 100%;
      overflow: visible;
    }

    .ant-drawer-body {
      /* 让菜单内容可以滚动 */
      overflow-y: auto !important;
      overflow-x: hidden !important;
      /* 添加底部padding，高度等于footer的高度（由JS动态设置） */
      /* 默认值280px作为fallback */
      padding-bottom: var(--footer-height, 280px) !important;
      /* 确保滚动流畅 */
      -webkit-overflow-scrolling: touch;
      /* 隐藏滚动条但保持滚动功能 */
      scrollbar-width: thin;
      scrollbar-color: rgba(255, 255, 255, 0.2) transparent;
      &::-webkit-scrollbar {
        width: 4px;
      }
      &::-webkit-scrollbar-track {
        background: transparent;
      }
      &::-webkit-scrollbar-thumb {
        background: rgba(255, 255, 255, 0.2);
        border-radius: 2px;
        &:hover {
          background: rgba(255, 255, 255, 0.3);
        }
      }
      /* 确保菜单内容区域有足够的高度 */
      min-height: 0;
      flex: 1;
    }
  }
}

</style>
