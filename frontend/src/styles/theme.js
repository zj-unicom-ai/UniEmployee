// Naive UI 主题覆盖：品牌色、圆角、阴影等样式变量
/**
 * UniEmployee Naive UI 主题覆盖
 * 与 global.css 的 CSS 变量完全对齐
 */
export const themeOverrides = {
  common: {
    primaryColor: '#3b82f6',
    primaryColorHover: '#2563eb',
    primaryColorPressed: '#1d4ed8',
    primaryColorSuppl: '#3b82f6',

    infoColor: '#06b6d4',
    infoColorHover: '#0891b2',
    infoColorPressed: '#0e7490',

    successColor: '#10b981',
    successColorHover: '#059669',
    successColorPressed: '#047857',

    warningColor: '#f59e0b',
    warningColorHover: '#d97706',
    warningColorPressed: '#b45309',

    errorColor: '#ef4444',
    errorColorHover: '#dc2626',
    errorColorPressed: '#b91c1c',

    bodyColor: '#f1f5f9',
    popoverColor: '#ffffff',
    cardColor: '#ffffff',
    modalColor: '#ffffff',
    tableColor: '#ffffff',
    actionColor: '#f8fafc',

    borderColor: '#e2e8f0',
    dividerColor: '#e2e8f0',

    textColor1: '#0f172a',
    textColor2: '#334155',
    textColor3: '#64748b',
    textColorDisabled: '#94a3b8',

    borderRadius: '8px',
    borderRadiusSmall: '6px',

    fontFamily: '"Inter", -apple-system, "PingFang SC", "Segoe UI", "Noto Sans SC", system-ui, sans-serif',
    fontSize: '14px',
    fontSizeSmall: '13px',
    fontSizeMedium: '14px',
    fontSizeLarge: '16px',
  },
  Layout: {
    color: '#f1f5f9',
    headerColor: '#ffffff',
    siderColor: '#0f172a',
    headerBorderColor: '#e2e8f0',
    siderBorderColor: '#1e293b',
  },
  Card: {
    color: '#ffffff',
    colorModal: '#ffffff',
    borderColor: '#e2e8f0',
    paddingMedium: '20px 24px',
    borderRadius: '12px',
  },
  Button: {
    textColorPrimary: '#ffffff',
    textColorPrimaryHover: '#ffffff',
    borderRound: '20px',
    paddingMedium: '0 20px',
  },
  Menu: {
    itemColorActive: 'rgba(59,130,246,0.12)',
    itemColorActiveHover: 'rgba(59,130,246,0.18)',
    itemTextColorActive: '#93c5fd',
    itemTextColorActiveHover: '#bfdbfe',
    itemIconColorActive: '#93c5fd',
    itemIconColorActiveHover: '#bfdbfe',
    itemTextColor: '#ffffff',
    itemTextColorHover: '#ffffff',
    itemIconColor: '#64748b',
    itemIconColorHover: '#94a3b8',
    itemColorHover: 'rgba(255,255,255,0.04)',
    fontSize: '13px',
  },
  Input: {
    color: '#ffffff',
    colorFocus: '#ffffff',
    border: '1px solid #cbd5e1',
    borderHover: '1px solid #3b82f6',
    borderFocus: '1px solid #3b82f6',
  },
  Select: {
    menuColor: '#ffffff',
    menuBorderColor: '#e2e8f0',
    menuBorderRadius: '8px',
  },
  Tag: {
    borderRadius: '6px',
  },
  DataTable: {
    thColor: '#f8fafc',
    thTextColor: '#475569',
    tdColor: '#ffffff',
    borderColor: '#e2e8f0',
    borderRadius: '8px',
    tdColorHover: '#f8fafc',
  },
  Modal: {
    borderRadius: '16px',
  },
  Popover: {
    borderRadius: '12px',
    padding: '16px',
  },
  Tooltip: {
    borderRadius: '8px',
  },
}
