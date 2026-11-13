"""Built-in local Web Console, Seat Monitor, Quick Health Check & Usage Ledger served at http://127.0.0.1:8000/."""

from __future__ import annotations

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Gemini Enterprise · 本地控制台</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f7fc;
      --surface: #ffffff;
      --surface-soft: #f8fafd;
      --surface-muted: #f1f5fb;
      --border: #e3e9f4;
      --border-strong: #cbd6ea;
      --text: #0f172a;
      --text-sub: #334155;
      --muted: #64748b;
      --primary: #2563eb;
      --primary-hover: #1d4ed8;
      --primary-soft: #eff6ff;
      --indigo: #4f46e5;
      --ok: #059669;
      --ok-soft: #ecfdf5;
      --ok-border: #a7f3d0;
      --warn: #d97706;
      --warn-soft: #fffbeb;
      --warn-border: #fde68a;
      --err: #e11d48;
      --err-soft: #fff1f2;
      --err-border: #fecdd3;
      --shadow-card: 0 12px 32px -14px rgba(15, 23, 42, 0.07), 0 2px 6px rgba(15, 23, 42, 0.025);
      --shadow-hover: 0 16px 36px -14px rgba(37, 99, 235, 0.12), 0 4px 10px rgba(15, 23, 42, 0.04);
      --radius-xl: 20px;
      --radius-lg: 14px;
      --radius-md: 10px;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "SF Pro Display", "SF Pro Text", "Segoe UI", system-ui, sans-serif;
      background:
        radial-gradient(900px 420px at 8% -6%, rgba(37, 99, 235, 0.075), transparent 60%),
        radial-gradient(820px 380px at 92% -4%, rgba(16, 185, 129, 0.065), transparent 58%),
        var(--bg);
      color: var(--text);
      line-height: 1.55;
      -webkit-font-smoothing: antialiased;
      font-variant-numeric: tabular-nums;
    }

    .wrap {
      max-width: 1120px;
      margin: 0 auto;
      padding: 28px 22px 56px;
    }

    /* Top Header */
    .topbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 14px;
    }

    .brand-logo {
      width: 42px;
      height: 42px;
      border-radius: 13px;
      background: linear-gradient(135deg, #2563eb 0%, #4f46e5 100%);
      color: #ffffff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 10px 22px -6px rgba(37, 99, 235, 0.45);
      flex-shrink: 0;
    }

    .brand h1 {
      margin: 0;
      font-size: 1.35rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: var(--text);
    }

    .brand-sub {
      margin-top: 2px;
      font-size: 0.84rem;
      color: var(--muted);
    }

    .topbar-actions {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }

    .live-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 7px 14px;
      border-radius: 999px;
      font-size: 0.84rem;
      font-weight: 600;
      background: var(--surface);
      border: 1px solid var(--border);
      box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
    }

    .dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--warn);
      box-shadow: 0 0 0 4px rgba(217, 119, 6, 0.15);
    }
    .dot.ok { background: var(--ok); box-shadow: 0 0 0 4px rgba(5, 150, 105, 0.16); }
    .dot.err { background: var(--err); box-shadow: 0 0 0 4px rgba(225, 29, 72, 0.16); }

    /* Buttons */
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 8px 15px;
      border-radius: 11px;
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text-sub);
      font: inherit;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.16s ease;
      text-decoration: none;
    }
    .btn:hover:not(:disabled) {
      border-color: var(--border-strong);
      background: var(--surface-soft);
      color: var(--text);
    }
    .btn:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
    .btn.primary {
      background: linear-gradient(135deg, #2563eb, #1d4ed8);
      border-color: transparent;
      color: #ffffff;
      box-shadow: 0 8px 20px -6px rgba(37, 99, 235, 0.42);
    }
    .btn.primary:hover:not(:disabled) {
      background: linear-gradient(135deg, #1d4ed8, #1e40af);
      transform: translateY(-1px);
    }
    .btn.soft {
      background: var(--primary-soft);
      border-color: rgba(37, 99, 235, 0.2);
      color: var(--primary);
    }
    .btn.soft:hover:not(:disabled) {
      background: #dbeafe;
    }
    .btn.sm {
      padding: 5px 11px;
      font-size: 0.78rem;
      border-radius: 8px;
    }

    /* 3-Step Self-Check Strip */
    .check-strip {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 20px;
    }
    @media (max-width: 820px) {
      .check-strip { grid-template-columns: 1fr; }
    }
    .step-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 13px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      box-shadow: var(--shadow-card);
      transition: border-color 0.2s ease;
    }
    .step-card.ok { border-color: rgba(5, 150, 105, 0.26); }
    .step-card.warn { border-color: var(--warn-border); background: #fffdf7; }
    .step-card.err { border-color: var(--err-border); background: #fffafa; }
    .step-left {
      display: flex;
      align-items: center;
      gap: 11px;
      min-width: 0;
    }
    .step-badge {
      width: 28px;
      height: 28px;
      border-radius: 9px;
      font-size: 0.8rem;
      font-weight: 700;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      background: var(--surface-muted);
      color: var(--muted);
    }
    .step-card.ok .step-badge { background: var(--ok-soft); color: var(--ok); }
    .step-card.warn .step-badge { background: var(--warn-soft); color: var(--warn); }
    .step-card.err .step-badge { background: var(--err-soft); color: var(--err); }
    .step-title {
      font-size: 0.87rem;
      font-weight: 700;
      color: var(--text);
    }
    .step-desc {
      font-size: 0.78rem;
      color: var(--muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    /* Collapsible Sections */
    .fold-section {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-xl);
      box-shadow: var(--shadow-card);
      margin-bottom: 18px;
      overflow: hidden;
    }
    .fold-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 17px 22px;
      cursor: pointer;
      user-select: none;
      transition: background 0.15s ease;
    }
    .fold-head:hover {
      background: rgba(241, 245, 251, 0.55);
    }
    .fold-title-wrap {
      display: flex;
      align-items: center;
      gap: 11px;
      min-width: 0;
    }
    .sec-icon {
      width: 32px;
      height: 32px;
      border-radius: 10px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 0.95rem;
      flex-shrink: 0;
      background: var(--primary-soft);
      color: var(--primary);
    }
    .sec-icon.green { background: var(--ok-soft); color: var(--ok); }
    .sec-icon.indigo { background: #eef2ff; color: var(--indigo); }
    .sec-icon.slate { background: var(--surface-muted); color: var(--muted); }
    .fold-title {
      margin: 0;
      font-size: 1.03rem;
      font-weight: 750;
      color: var(--text);
    }
    .fold-subtitle {
      font-size: 0.8rem;
      color: var(--muted);
      margin-top: 1px;
    }
    .fold-right {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-shrink: 0;
    }
    .chevron {
      width: 26px;
      height: 26px;
      border-radius: 8px;
      background: var(--surface-muted);
      color: var(--muted);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 0.82rem;
      transition: transform 0.2s ease, background 0.15s ease;
    }
    .fold-section.collapsed .chevron {
      transform: rotate(-90deg);
    }
    .fold-body {
      padding: 0 22px 22px;
      border-top: 1px solid #eef2f9;
    }
    .fold-section.collapsed .fold-body {
      display: none;
    }

    /* Tags & Chips */
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 3px 10px;
      border-radius: 999px;
      font-size: 0.76rem;
      font-weight: 600;
      background: var(--surface-muted);
      color: var(--text-sub);
    }
    .chip.ok { background: var(--ok-soft); color: var(--ok); }
    .chip.busy { background: var(--primary-soft); color: var(--primary); }
    .chip.warn { background: var(--warn-soft); color: var(--warn); }
    .chip.purple { background: #eef2ff; color: var(--indigo); }

    /* Context Pool Banner & Seat Grid */
    .ctx-banner {
      margin-top: 16px;
      padding: 14px 16px;
      border-radius: var(--radius-lg);
      background: linear-gradient(180deg, #f8faff 0%, #f3f7fe 100%);
      border: 1px solid #e1eaf8;
    }
    .ctx-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      font-size: 0.85rem;
    }
    .ctx-track {
      width: 100%;
      height: 9px;
      border-radius: 999px;
      background: #e5ecf6;
      overflow: hidden;
      margin-top: 9px;
    }
    .ctx-fill {
      height: 100%;
      width: 0%;
      border-radius: 999px;
      background: linear-gradient(90deg, #10b981, #2563eb);
      transition: width 0.3s ease;
    }
    .ctx-fill.warn { background: linear-gradient(90deg, #f59e0b, #ea580c); }
    .ctx-fill.danger { background: linear-gradient(90deg, #ef4444, #e11d48); }

    .seats-grid {
      margin-top: 14px;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(188px, 1fr));
      gap: 11px;
    }
    .seat-card {
      background: var(--surface-soft);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px 13px;
      display: flex;
      flex-direction: column;
      gap: 9px;
      transition: all 0.16s ease;
    }
    .seat-card:hover {
      background: #ffffff;
      box-shadow: var(--shadow-hover);
      border-color: #d0dcf0;
    }
    .seat-card.busy {
      background: linear-gradient(165deg, #eff6ff 0%, #f8fbff 100%);
      border-color: rgba(37, 99, 235, 0.48);
      box-shadow: 0 10px 26px -12px rgba(37, 99, 235, 0.28);
    }
    .seat-card.active-idle {
      background: #ffffff;
      border-color: #d5e0f2;
    }
    @keyframes seatPulse {
      0%, 100% { transform: scale(1); opacity: 1; }
      50% { transform: scale(1.32); opacity: 0.55; }
    }
    .live-work-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--primary);
      display: inline-block;
      animation: seatPulse 1.35s ease-in-out infinite;
    }
    .seat-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
    }
    .seat-name {
      font-weight: 700;
      font-size: 0.9rem;
      color: var(--text);
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .seat-id {
      font-size: 0.72rem;
      font-weight: 500;
      color: var(--muted);
    }
    .seat-topic {
      min-height: 2.55em;
      padding: 6px 8px;
      border-radius: 9px;
      background: rgba(241, 245, 251, 0.72);
      border: 1px solid #e9eef8;
      font-size: 0.79rem;
      font-weight: 650;
      line-height: 1.36;
      color: var(--text);
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      word-break: break-word;
    }
    .seat-card.busy .seat-topic {
      background: rgba(255, 255, 255, 0.88);
      border-color: rgba(37, 99, 235, 0.22);
      color: #1e3a8a;
    }
    .seat-topic.empty {
      color: var(--muted);
      font-weight: 500;
      background: transparent;
      border-style: dashed;
    }
    .seat-meta {
      display: flex;
      justify-content: space-between;
      font-size: 0.78rem;
      color: var(--muted);
    }
    .seat-mini-track {
      width: 100%;
      height: 5px;
      border-radius: 999px;
      background: #e6edf7;
      overflow: hidden;
    }
    .seat-mini-fill {
      height: 100%;
      width: 0%;
      border-radius: 999px;
      background: linear-gradient(90deg, #10b981, #3b82f6);
    }
    .seat-foot {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      padding-top: 4px;
    }
    .seat-rem {
      font-size: 0.72rem;
      color: var(--muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .empty-seats {
      grid-column: 1 / -1;
      text-align: center;
      padding: 24px 16px;
      border-radius: 14px;
      background: var(--surface-soft);
      border: 1px dashed var(--border-strong);
      color: var(--muted);
      font-size: 0.88rem;
    }

    /* One-Click Health Test */
    .probe-bar {
      margin-top: 16px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 16px;
      border-radius: var(--radius-lg);
      background: var(--surface-soft);
      border: 1px solid var(--border);
    }
    .probe-controls {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
    }
    select.clean-select,
    input.clean-input,
    textarea.clean-textarea {
      padding: 8px 12px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: #ffffff;
      color: var(--text);
      font: inherit;
      font-size: 0.86rem;
      outline: none;
      transition: border-color 0.15s ease;
    }
    select.clean-select:focus,
    input.clean-input:focus,
    textarea.clean-textarea:focus {
      border-color: var(--primary);
    }
    .probe-result {
      margin-top: 12px;
      padding: 13px 16px;
      border-radius: 13px;
      border: 1px solid var(--border);
      background: #ffffff;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .probe-result.ok {
      background: var(--ok-soft);
      border-color: var(--ok-border);
    }
    .probe-result.err {
      background: var(--err-soft);
      border-color: var(--err-border);
    }
    .probe-res-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
      font-size: 0.88rem;
      font-weight: 700;
    }
    .probe-res-body {
      margin: 0;
      font-size: 0.86rem;
      color: var(--text-sub);
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 260px;
      overflow: auto;
    }
    .custom-test-drawer {
      margin-top: 12px;
      border: 1px dashed var(--border-strong);
      border-radius: 13px;
      padding: 10px 14px;
      background: #fafcff;
    }
    .custom-test-drawer summary {
      cursor: pointer;
      font-size: 0.83rem;
      font-weight: 600;
      color: var(--muted);
      user-select: none;
    }
    .custom-test-body {
      margin-top: 12px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    /* Ledger Controls & Hero */
    .currency-switch {
      display: inline-flex;
      background: var(--surface-muted);
      padding: 3px;
      border-radius: 999px;
      border: 1px solid var(--border);
    }
    .cur-btn {
      border: none;
      background: transparent;
      color: var(--muted);
      font: inherit;
      font-size: 0.76rem;
      font-weight: 700;
      padding: 3px 10px;
      border-radius: 999px;
      cursor: pointer;
      transition: all 0.14s ease;
    }
    .cur-btn.active {
      background: #ffffff;
      color: var(--primary);
      box-shadow: 0 1px 4px rgba(15, 23, 42, 0.08);
    }

    .period-bar {
      margin-top: 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
      padding: 8px 10px;
      border-radius: 12px;
      background: var(--surface-soft);
      border: 1px solid var(--border);
    }
    .period-tabs {
      display: flex;
      gap: 5px;
      flex-wrap: wrap;
    }
    .period-tab {
      background: transparent;
      color: var(--muted);
      border: none;
      border-radius: 8px;
      padding: 5px 12px;
      font: inherit;
      font-size: 0.82rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.14s ease;
    }
    .period-tab:hover {
      color: var(--text);
      background: #eaf0fa;
    }
    .period-tab.active {
      background: var(--primary);
      color: #ffffff;
      box-shadow: 0 4px 10px -3px rgba(37, 99, 235, 0.35);
    }
    .date-picker-wrap {
      display: flex;
      align-items: center;
      gap: 7px;
      font-size: 0.8rem;
      color: var(--muted);
    }
    input[type="date"].date-input {
      padding: 4px 9px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: #ffffff;
      color: var(--text);
      font: inherit;
      font-size: 0.8rem;
    }

    .ledger-hero {
      margin-top: 14px;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }
    @media (max-width: 920px) {
      .ledger-hero { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 540px) {
      .ledger-hero { grid-template-columns: 1fr; }
    }
    .stat-tile {
      padding: 15px 16px;
      border-radius: 15px;
      background: var(--surface-soft);
      border: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .stat-tile.highlight {
      background: linear-gradient(155deg, #ecfdf5 0%, #f4fdf9 100%);
      border-color: var(--ok-border);
    }
    .stat-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      font-size: 0.79rem;
      font-weight: 600;
      color: var(--muted);
    }
    .stat-tile.highlight .stat-head { color: #047857; }
    .stat-big {
      font-size: 1.52rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: var(--text);
      margin: 2px 0;
    }
    .stat-tile.highlight .stat-big { color: var(--ok); }
    .stat-sub {
      font-size: 0.77rem;
      color: var(--muted);
      line-height: 1.45;
    }

    /* Visual Charts Grid */
    .charts-grid {
      margin-top: 14px;
      display: grid;
      grid-template-columns: 1.35fr 1fr;
      gap: 14px;
    }
    @media (max-width: 860px) {
      .charts-grid { grid-template-columns: 1fr; }
    }
    .chart-box {
      padding: 15px 16px;
      border-radius: 15px;
      background: var(--surface-soft);
      border: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .chart-title-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      font-size: 0.85rem;
      font-weight: 700;
      color: var(--text);
    }
    .chart-legend {
      display: flex;
      gap: 10px;
      font-size: 0.74rem;
      font-weight: 500;
      color: var(--muted);
    }
    .leg-dot {
      display: inline-block;
      width: 8px;
      height: 8px;
      border-radius: 3px;
      margin-right: 4px;
      vertical-align: middle;
    }
    .bars-stage {
      height: 142px;
      display: flex;
      align-items: flex-end;
      gap: 8px;
      padding: 12px 4px 0;
      border-bottom: 1px solid var(--border);
    }
    .bar-col {
      flex: 1;
      min-width: 0;
      height: 100%;
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      align-items: center;
      gap: 6px;
      cursor: pointer;
    }
    .bar-stack {
      width: 100%;
      max-width: 34px;
      height: 96px;
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      border-radius: 7px 7px 3px 3px;
      overflow: hidden;
      background: #eaf0f9;
      transition: transform 0.15s ease;
    }
    .bar-val {
      font-size: 0.69rem;
      font-weight: 600;
      color: var(--text-sub);
      white-space: nowrap;
      min-height: 15px;
    }
    .bar-col:hover .bar-stack {
      transform: translateY(-2px);
    }
    .bar-col.selected .bar-lbl {
      color: var(--primary);
      font-weight: 700;
    }
    .bar-seg-saved {
      background: #34d399;
      width: 100%;
      transition: height 0.25s ease;
    }
    .bar-seg-actual {
      background: #2563eb;
      width: 100%;
      transition: height 0.25s ease;
    }
    .bar-lbl {
      font-size: 0.71rem;
      color: var(--muted);
      white-space: nowrap;
    }

    .task-ratio-bar {
      width: 100%;
      height: 12px;
      border-radius: 999px;
      background: #e6edf7;
      overflow: hidden;
      display: flex;
      gap: 2px;
    }
    .task-list {
      display: flex;
      flex-direction: column;
      gap: 7px;
    }
    .task-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 0.8rem;
    }
    .task-row-left {
      display: flex;
      align-items: center;
      gap: 7px;
      color: var(--text-sub);
      font-weight: 600;
    }
    .task-row-right {
      color: var(--muted);
      font-size: 0.77rem;
    }

    /* Tables */
    details.sub-panel {
      margin-top: 14px;
      border-top: 1px dashed var(--border);
      padding-top: 12px;
    }
    details.sub-panel summary {
      cursor: pointer;
      font-size: 0.85rem;
      font-weight: 650;
      color: var(--text-sub);
      user-select: none;
    }
    .table-scroll { overflow-x: auto; margin-top: 10px; }
    table.clean-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.81rem;
    }
    table.clean-table th,
    table.clean-table td {
      padding: 9px 10px;
      text-align: left;
      border-bottom: 1px solid #edf2f9;
      white-space: nowrap;
    }
    table.clean-table th {
      color: var(--muted);
      font-weight: 600;
      background: var(--surface-soft);
    }
    table.clean-table tbody tr:hover {
      background: #f9fbff;
    }

    /* Diagnostics & Logs */
    .diag-kv-grid {
      margin-top: 14px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
    }
    .diag-kv {
      padding: 10px 12px;
      border-radius: 11px;
      background: var(--surface-soft);
      border: 1px solid var(--border);
      font-size: 0.8rem;
    }
    .diag-kv .k { color: var(--muted); font-size: 0.74rem; }
    .diag-kv .v { font-weight: 600; color: var(--text); margin-top: 2px; word-break: break-all; }
    .logs-box {
      margin-top: 12px;
      max-height: 180px;
      overflow: auto;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.77rem;
      background: var(--surface-soft);
      border-radius: 11px;
      padding: 10px 12px;
      border: 1px solid var(--border);
      color: var(--text-sub);
    }
    .log-item { padding: 3px 0; border-bottom: 1px solid #eef2f9; }
    .log-item:last-child { border-bottom: none; }

    /* Modal */
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.36);
      backdrop-filter: blur(4px);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
      z-index: 100;
    }
    .modal-backdrop[hidden] { display: none; }
    .modal-card {
      width: 100%;
      max-width: 540px;
      background: #ffffff;
      border-radius: 20px;
      border: 1px solid var(--border);
      box-shadow: 0 24px 60px -12px rgba(15, 23, 42, 0.22);
      padding: 22px 24px;
    }
    .modal-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 14px;
    }
    .modal-head h3 { margin: 0; font-size: 1.08rem; }
    .copy-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 12px;
      border-radius: 12px;
      background: var(--surface-soft);
      border: 1px solid var(--border);
      margin-bottom: 9px;
    }
    .copy-meta { min-width: 0; }
    .copy-label { font-size: 0.75rem; color: var(--muted); }
    .copy-val {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.84rem;
      font-weight: 600;
      color: var(--text);
      word-break: break-all;
    }

    .muted { color: var(--muted); }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  </style>
</head>
<body>
  <div class="wrap">
    <!-- Top Header -->
    <header class="topbar">
      <div class="brand">
        <div class="brand-logo" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none">
            <path d="M12 2C12.9 7.8 16.2 11.1 22 12C16.2 12.9 12.9 16.2 12 22C11.1 16.2 7.8 12.9 2 12C7.8 11.1 11.1 7.8 12 2Z" fill="currentColor"/>
          </svg>
        </div>
        <div>
          <h1>Gemini Enterprise</h1>
          <div class="brand-sub">本地智能网关控制台 · 默认模型 Carbon · 免密直连</div>
        </div>
      </div>
      <div class="topbar-actions">
        <div class="live-pill" id="connBadge">
          <span class="dot" id="connDot"></span>
          <span id="connText">正在同步状态...</span>
        </div>
        <button type="button" class="btn soft" id="openGuideBtn">接入指南 · 一键复制</button>
        <button type="button" class="btn" id="refreshBtn">刷新</button>
      </div>
    </header>

    <!-- 3-Step Self-Check Strip -->
    <section class="check-strip" aria-label="连接三步自检">
      <div class="step-card ok" id="stepServiceCard">
        <div class="step-left">
          <span class="step-badge" id="stepServiceIcon">✓</span>
          <div>
            <div class="step-title">1. 本地服务在线</div>
            <div class="step-desc" id="stepServiceDesc">127.0.0.1:8000 · 默认 Carbon</div>
          </div>
        </div>
        <span class="chip ok" id="stepServiceTag">正常</span>
      </div>

      <div class="step-card" id="stepExtCard">
        <div class="step-left">
          <span class="step-badge" id="stepExtIcon">2</span>
          <div>
            <div class="step-title">2. 浏览器插件桥接</div>
            <div class="step-desc" id="stepExtDesc">正在检测浏览器扩展连接...</div>
          </div>
        </div>
        <span class="chip" id="stepExtTag">检测中</span>
      </div>

      <div class="step-card" id="stepAuthCard">
        <div class="step-left">
          <span class="step-badge" id="stepAuthIcon">3</span>
          <div>
            <div class="step-title">3. Google 登录工作页</div>
            <div class="step-desc" id="stepAuthDesc">正在检查可用工作网页...</div>
          </div>
        </div>
        <a href="https://vertexaisearch.cloud.google.com/" target="_blank" rel="noopener" class="btn sm soft" id="stepAuthBtn" hidden>去打开 ↗</a>
        <span class="chip" id="stepAuthTag">检测中</span>
      </div>
    </section>

    <!-- Section 1: Parallel Seats & Memory Capacity -->
    <section class="fold-section" data-sec="seats" id="secSeats">
      <div class="fold-head" data-fold-toggle="seats">
        <div class="fold-title-wrap">
          <span class="sec-icon">✦</span>
          <div>
            <h2 class="fold-title">并行工作席位 &amp; 记忆容量</h2>
            <div class="fold-subtitle">工作中席位自动置顶 · 实时展示当前会话标题、状态与记忆余量</div>
          </div>
        </div>
        <div class="fold-right">
          <span class="chip" id="seatsSummaryChip">0 个席位待命</span>
          <span class="chevron" aria-hidden="true">▾</span>
        </div>
      </div>
      <div class="fold-body">
        <div class="ctx-banner">
          <div class="ctx-row">
            <strong id="ledgerCtxTitle">主活跃对话记忆池 · 空闲待命 (自动整理线 300.0K)</strong>
            <span class="muted" id="ledgerCtxPct">已用 0 / 自动整理线 300.0K (0.0%) · 总容量上限 1.05M</span>
          </div>
          <div class="ctx-track" title="进度条满格为本地自动整理记忆线 (300.0K)，总上下文容量 1,048,576">
            <div id="ledgerCtxFill" class="ctx-fill"></div>
          </div>
        </div>

        <div class="seats-grid" id="seatsGrid">
          <div class="empty-seats">正在读取工作席位状态...</div>
        </div>
      </div>
    </section>

    <!-- Section 2: One-Click Model Health Check -->
    <section class="fold-section" data-sec="probe" id="secProbe">
      <div class="fold-head" data-fold-toggle="probe">
        <div class="fold-title-wrap">
          <span class="sec-icon green">⚡</span>
          <div>
            <h2 class="fold-title">一键模型连通体检</h2>
            <div class="fold-subtitle">无需手动想问题打字，点一下自动验证模型真实回复与响应速度</div>
          </div>
        </div>
        <div class="fold-right">
          <span class="chip" id="probeHeaderChip">默认测 Carbon</span>
          <span class="chevron" aria-hidden="true">▾</span>
        </div>
      </div>
      <div class="fold-body">
        <div class="probe-bar">
          <div class="probe-controls">
            <select id="modelSelect" class="clean-select" aria-label="选择测试模型">
              <option value="gemini-4-carbon" selected>Carbon（默认主力）</option>
              <option value="gemini-4-argon">Argon（高速轻量）</option>
              <option value="gemini-3.1-pro">Gemini 3.1 Pro</option>
              <option value="gemini-3.8-flash">Gemini 3.8 Flash</option>
              <option value="gemini-enterprise-web">保持网页当前模型</option>
              <optgroup label="其他兼容模型">
                <option value="gemini-2.5-pro">Gemini 2.5 Pro</option>
                <option value="gemini-2.5-flash">Gemini 2.5 Flash</option>
              </optgroup>
            </select>
            <button type="button" class="btn primary" id="quickProbeBtn">⚡ 一键快速体检</button>
          </div>
          <span class="muted" style="font-size:0.8rem;" id="probeHint">自动发送简短口令并核验真实网页回复</span>
        </div>

        <div class="probe-result" id="probeResultBox" hidden>
          <div class="probe-res-head">
            <span id="probeResTitle">测试结果</span>
            <span class="chip" id="probeResMeta">-</span>
          </div>
          <pre class="probe-res-body" id="replyOut">等待测试输出...</pre>
        </div>

        <details class="custom-test-drawer" id="customTestDrawer">
          <summary>需要自己提问或测试图片 / 文档附件？点此展开自定义测试</summary>
          <div class="custom-test-body">
            <textarea id="promptInput" class="clean-textarea" rows="3" placeholder="输入你想测试的问题，也可在下方选择图片、PDF、Word、表格或音视频一起发送..."></textarea>
            <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;">
              <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
                <input id="fileInput" type="file" multiple style="font-size:0.82rem;color:var(--muted);" />
                <details style="font-size:0.78rem;color:var(--muted);">
                  <summary style="cursor:pointer;">高级：填写访问密钥（本机默认留空）</summary>
                  <input id="apiKeyInput" class="clean-input" type="password" autocomplete="off" spellcheck="false" placeholder="默认留空免密" style="margin-top:6px;width:240px;" />
                </details>
              </div>
              <button type="button" class="btn soft" id="sendBtn">发送自定义提问</button>
            </div>
          </div>
        </details>
      </div>
    </section>

    <!-- Section 3: Usage & Cost Savings Ledger -->
    <section class="fold-section" data-sec="ledger" id="secLedger">
      <div class="fold-head" data-fold-toggle="ledger">
        <div class="fold-title-wrap">
          <span class="sec-icon indigo">¥</span>
          <div>
            <h2 class="fold-title">用量与省钱账本</h2>
            <div class="fold-subtitle">本地字数折算参考账单（非 Google 实际扣费）· 直观对比多轮续聊省下的花费</div>
          </div>
        </div>
        <div class="fold-right">
          <div class="currency-switch" id="currencySwitch" title="切换显示币种">
            <button type="button" class="cur-btn active" data-cur="CNY">¥ 人民币</button>
            <button type="button" class="cur-btn" data-cur="USD">$ 美元</button>
          </div>
          <span class="chevron" aria-hidden="true">▾</span>
        </div>
      </div>
      <div class="fold-body">
        <div class="period-bar">
          <div class="period-tabs" id="periodTabs">
            <button type="button" class="period-tab" data-period="today">今日</button>
            <button type="button" class="period-tab" data-period="yesterday">昨日</button>
            <button type="button" class="period-tab" data-period="7d">近 7 天</button>
            <button type="button" class="period-tab" data-period="30d">近 30 天</button>
            <button type="button" class="period-tab" data-period="session">本次启动</button>
            <button type="button" class="period-tab active" data-period="all">全部累计</button>
          </div>
          <div class="date-picker-wrap">
            <span>按日历查某天:</span>
            <input type="date" id="datePickerInput" class="date-input" aria-label="按日期查看统计" />
            <select id="dayFilterSelect" hidden></select>
            <span class="chip" id="activePeriodTag">全部累计</span>
          </div>
        </div>

        <div class="ledger-hero">
          <div class="stat-tile highlight">
            <div class="stat-head">
              <span id="cardSavedLabel">多轮续聊累计省下</span>
              <span class="chip ok" id="reuseRateChip">省流 0%</span>
            </div>
            <div class="stat-big" id="ledgerSavedMain">¥0.00</div>
            <div class="stat-sub" id="ledgerSavedSub">若每次重发原价约 ¥0.00</div>
          </div>

          <div class="stat-tile">
            <div class="stat-head">
              <span id="cardActualLabel">实际续聊折算消耗</span>
            </div>
            <div class="stat-big" id="ledgerActualMain">¥0.00</div>
            <div class="stat-sub" id="ledgerActualSub">仅按每轮新增内容与缓存价折算</div>
          </div>

          <div class="stat-tile">
            <div class="stat-head">
              <span id="cardCallsLabel">期间调用总次数</span>
            </div>
            <div class="stat-big" id="ledgerCallsMain">0 次</div>
            <div class="stat-sub" id="ledgerCallsSub">Codex 0 · 对话 0 · 记忆整理 0</div>
          </div>

          <div class="stat-tile">
            <div class="stat-head">
              <span id="cardWordsLabel">累计处理内容规模</span>
            </div>
            <div class="stat-big" id="ledgerWordsMain">约 0 字</div>
            <div class="stat-sub" id="ledgerWordsSub">输入 0 · 记忆复用 0 · 输出 0</div>
          </div>
        </div>

        <div class="charts-grid">
          <div class="chart-box">
            <div class="chart-title-row">
              <span>每日折算趋势（点击柱子可看当天明细）</span>
              <div class="chart-legend">
                <span><i class="leg-dot" style="background:#34d399;"></i>续聊省下</span>
                <span><i class="leg-dot" style="background:#2563eb;"></i>实际折算</span>
              </div>
            </div>
            <div class="bars-stage" id="dailyBarsStage"></div>
          </div>

          <div class="chart-box">
            <div class="chart-title-row">
              <span>用途分布占比</span>
              <span class="muted" style="font-size:0.74rem;" id="ledgerRateBadge">Carbon 参考价</span>
            </div>
            <div class="task-ratio-bar" id="taskRatioBar"></div>
            <div class="task-list" id="taskBreakdownList"></div>
          </div>
        </div>

        <details class="sub-panel">
          <summary>查看分模型统计、按日汇总与最近调用流水</summary>
          <div class="table-scroll">
            <table class="clean-table">
              <thead>
                <tr>
                  <th>模型名称</th>
                  <th>调用次数</th>
                  <th>处理量（总输入 / 记忆复用 / 输出）</th>
                  <th>专项生成</th>
                  <th>全量重发原价</th>
                  <th>续聊折算（已省下）</th>
                </tr>
              </thead>
              <tbody id="ledgerModelBody">
                <tr><td colspan="6" class="muted">暂无记录</td></tr>
              </tbody>
            </table>
          </div>

          <div class="table-scroll">
            <table class="clean-table">
              <thead>
                <tr>
                  <th>日期</th>
                  <th>调用次数</th>
                  <th>专项统计</th>
                  <th>全量重发原价</th>
                  <th>实际续聊折算</th>
                  <th>省下金额（复用率）</th>
                </tr>
              </thead>
              <tbody id="ledgerDailyBody">
                <tr><td colspan="6" class="muted">暂无按日记录</td></tr>
              </tbody>
            </table>
          </div>

          <div class="table-scroll">
            <table class="clean-table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>用途</th>
                  <th>模型 · 工作席位</th>
                  <th>对话方式</th>
                  <th>本轮新增 / 记忆复用 / 回复</th>
                  <th>折算花费（已省）</th>
                  <th>耗时</th>
                </tr>
              </thead>
              <tbody id="ledgerRecentBody">
                <tr><td colspan="7" class="muted">暂无最近流水</td></tr>
              </tbody>
            </table>
          </div>
        </details>
      </div>
    </section>

    <!-- Section 4: Diagnostics & Logs (Collapsed by default) -->
    <section class="fold-section collapsed" data-sec="diag" id="secDiag">
      <div class="fold-head" data-fold-toggle="diag">
        <div class="fold-title-wrap">
          <span class="sec-icon slate">⚙</span>
          <div>
            <h2 class="fold-title">系统诊断与底层运行记录</h2>
            <div class="fold-subtitle">平时无需关注；遇到连接异常时可展开查看底层通道与网关日志</div>
          </div>
        </div>
        <div class="fold-right">
          <span class="chip" id="diagStatsChip">累计 0 次请求</span>
          <span class="chevron" aria-hidden="true">▾</span>
        </div>
      </div>
      <div class="fold-body">
        <div class="diag-kv-grid">
          <div class="diag-kv"><div class="k">运行与记忆模式</div><div class="v" id="modeVal">-</div></div>
          <div class="diag-kv"><div class="k">浏览器连接通道</div><div class="v" id="transportVal">-</div></div>
          <div class="diag-kv"><div class="k">网页流监听状态</div><div class="v" id="rpcVal">-</div></div>
          <div class="diag-kv"><div class="k">并发 / 排队 / 历史总请求</div><div class="v" id="statsVal">0 / 0 / 0</div></div>
        </div>
        <div class="logs-box" id="logsBox">暂无运行记录</div>
      </div>
    </section>
  </div>

  <!-- Integration Guide Modal -->
  <div class="modal-backdrop" id="guideModal" hidden>
    <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="guideModalTitle">
      <div class="modal-head">
        <h3 id="guideModalTitle">第三方软件接入指南（一键复制）</h3>
        <button type="button" class="btn sm" id="closeGuideBtn">关闭</button>
      </div>
      <p class="muted" style="margin:0 0 14px;font-size:0.83rem;">
        支持 Codex、Cursor、Cline、ChatBox 等所有兼容 OpenAI 接口的软件接入本机服务：
      </p>
      <div class="copy-row">
        <div class="copy-meta">
          <div class="copy-label">接口地址 (Base URL / API Host)</div>
          <div class="copy-val" id="baseUrlVal">http://127.0.0.1:8000/v1</div>
        </div>
        <button type="button" class="btn sm soft" data-copy-target="baseUrlVal">复制</button>
      </div>
      <div class="copy-row">
        <div class="copy-meta">
          <div class="copy-label">默认主力模型（推荐填写）</div>
          <div class="copy-val" id="copyCarbonVal">gemini-4-carbon</div>
        </div>
        <button type="button" class="btn sm soft" data-copy-target="copyCarbonVal">复制</button>
      </div>
      <div class="copy-row">
        <div class="copy-meta">
          <div class="copy-label">其他可选模型</div>
          <div class="copy-val" id="copyOtherModels">gemini-4-argon, gemini-3.1-pro, gemini-3.8-flash</div>
        </div>
        <button type="button" class="btn sm soft" data-copy-target="copyOtherModels">复制</button>
      </div>
      <div class="copy-row" style="margin-bottom:0;">
        <div class="copy-meta">
          <div class="copy-label">API Key（访问密钥）</div>
          <div class="copy-val">本机已设为免密，留空或任意填写均可</div>
        </div>
      </div>
    </div>
  </div>
  <script>
    (function () {
      const baseOrigin = window.location.origin;
      document.getElementById('baseUrlVal').textContent = baseOrigin + '/v1';

      let selectedPeriod = 'all';
      let selectedCurrency = 'CNY';
      try {
        const savedCur = localStorage.getItem('geb_currency');
        if (savedCur === 'USD' || savedCur === 'CNY') selectedCurrency = savedCur;
      } catch (_) {}

      let lastUsageSnapshot = null;
      let lastCtxSnapshot = null;
      let seatIndexByTabId = {};
      let seatIndexBySlotKey = {};

      const PERIOD_LABELS = {
        today: '今日',
        yesterday: '昨日',
        '7d': '近 7 天',
        '30d': '近 30 天',
        session: '本次启动',
        all: '全部累计'
      };

      const TASK_META = {
        responses: { label: 'Codex 编程', color: '#2563eb' },
        chat: { label: '日常对话', color: '#10b981' },
        compaction: { label: '自动整理记忆', color: '#f59e0b' },
        image_gen: { label: '生成图片', color: '#8b5cf6' },
        image_edit: { label: '修改图片', color: '#ec4899' },
        video_gen: { label: '生成视频', color: '#06b6d4' },
        audio: { label: '语音处理', color: '#64748b' }
      };

      function syncCurrencyButtons() {
        document.querySelectorAll('#currencySwitch .cur-btn').forEach(function (btn) {
          btn.classList.toggle('active', btn.getAttribute('data-cur') === selectedCurrency);
        });
      }
      syncCurrencyButtons();

      // Restore collapsible section states
      document.querySelectorAll('.fold-section').forEach(function (sec) {
        const key = sec.getAttribute('data-sec');
        if (!key) return;
        try {
          const saved = localStorage.getItem('geb_fold_' + key);
          if (saved === '1') sec.classList.add('collapsed');
          else if (saved === '0') sec.classList.remove('collapsed');
        } catch (_) {}
      });

      document.querySelectorAll('[data-fold-toggle]').forEach(function (head) {
        head.addEventListener('click', function (ev) {
          if (ev.target && ev.target.closest('#currencySwitch')) return;
          const sec = head.closest('.fold-section');
          if (!sec) return;
          sec.classList.toggle('collapsed');
          const key = sec.getAttribute('data-sec');
          if (key) {
            try {
              localStorage.setItem('geb_fold_' + key, sec.classList.contains('collapsed') ? '1' : '0');
            } catch (_) {}
          }
        });
      });

      document.getElementById('currencySwitch').addEventListener('click', function (ev) {
        ev.stopPropagation();
        const btn = ev.target && ev.target.closest('.cur-btn');
        if (!btn) return;
        const cur = btn.getAttribute('data-cur');
        if (!cur) return;
        selectedCurrency = cur;
        try { localStorage.setItem('geb_currency', cur); } catch (_) {}
        syncCurrencyButtons();
        if (lastUsageSnapshot) renderLedger(lastUsageSnapshot, lastCtxSnapshot);
      });

      function fmtTok(n) {
        const v = Number(n || 0);
        if (v >= 1000000) return (v / 1000000).toFixed(2) + 'M';
        if (v >= 1000) return (v / 1000).toFixed(1) + 'K';
        return String(Math.round(v));
      }

      function fmtWordsScale(tokens) {
        const chars = Math.round(Number(tokens || 0) * 1.4);
        if (chars <= 0) return '约 0 字';
        if (chars >= 100000000) return '约 ' + (chars / 100000000).toFixed(2) + ' 亿字';
        if (chars >= 10000) return '约 ' + (chars / 10000).toFixed(1) + ' 万字';
        return '约 ' + chars.toLocaleString() + ' 字';
      }

      function fmtMoney(usdVal, cnyVal) {
        if (selectedCurrency === 'USD') {
          const u = Number(usdVal || 0);
          if (u <= 0) return '$0.00';
          return u < 0.01 ? ('$' + u.toFixed(4)) : ('$' + u.toFixed(2));
        }
        const c = Number(cnyVal || 0);
        if (c <= 0) return '¥0.00';
        return c < 0.01 ? ('¥' + c.toFixed(3)) : ('¥' + c.toFixed(2));
      }

      function friendlyModel(raw) {
        const s = String(raw || '').toLowerCase();
        if (!s) return 'Carbon';
        if (s.includes('carbon')) return 'Carbon';
        if (s.includes('argon')) return 'Argon';
        if (s.includes('3.1')) return '3.1 Pro';
        if (s.includes('3.8') || s.includes('flash')) return '3.8 Flash';
        if (s.includes('2.5-pro')) return '2.5 Pro';
        if (s.includes('2.5-flash')) return '2.5 Flash';
        if (s.includes('enterprise-web')) return '当前网页模型';
        return String(raw);
      }

      function friendlyStrategyBadge(strategy) {
        const s = String(strategy || '').toLowerCase();
        const span = document.createElement('span');
        if (s.includes('incremental') || s.includes('delta')) {
          span.className = 'chip ok';
          span.textContent = '智能续聊';
        } else if (s.includes('compact') || s.includes('checkpoint')) {
          span.className = 'chip warn';
          span.textContent = '记忆整理';
        } else if (s.includes('bootstrap') || s.includes('reset') || s.includes('new') || s.includes('full')) {
          span.className = 'chip busy';
          span.textContent = '新开对话';
        } else if (s.includes('recover')) {
          span.className = 'chip purple';
          span.textContent = '断点续接';
        } else if (!s || s === '-') {
          span.className = 'chip';
          span.textContent = '常规调用';
        } else {
          span.className = 'chip';
          span.textContent = '单次直发';
        }
        return span;
      }

      function friendlySeatLabel(slotKey, tabId) {
        if (slotKey && seatIndexBySlotKey[slotKey]) {
          return seatIndexBySlotKey[slotKey] + ' 号席位';
        }
        if (tabId && seatIndexByTabId[String(tabId)]) {
          return seatIndexByTabId[String(tabId)] + ' 号席位';
        }
        if (tabId) {
          return '席位 #' + String(tabId).slice(-4);
        }
        return '自动席位';
      }

      function makeCell(content, cls) {
        const td = document.createElement('td');
        if (cls) td.className = cls;
        if (content instanceof Node) td.appendChild(content);
        else td.textContent = String(content);
        return td;
      }

      function renderEmptyRow(tbody, cols, msg) {
        tbody.replaceChildren();
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = cols;
        td.className = 'muted';
        td.textContent = msg;
        tr.appendChild(td);
        tbody.appendChild(tr);
      }

      function setStepState(cardId, iconId, descId, tagId, state, iconText, descText, tagText) {
        const card = document.getElementById(cardId);
        const icon = document.getElementById(iconId);
        const desc = document.getElementById(descId);
        const tag = document.getElementById(tagId);
        card.className = 'step-card ' + state;
        icon.textContent = iconText;
        desc.textContent = descText;
        tag.textContent = tagText;
        tag.className = 'chip ' + (state === 'ok' ? 'ok' : (state === 'warn' ? 'warn' : ''));
      }

      async function resetSingleSeat(slotKey, seatNum, btn) {
        const origText = btn.textContent;
        btn.disabled = true;
        btn.textContent = '重置中...';
        try {
          const authVal = document.getElementById('apiKeyInput').value.trim();
          const headers = { 'Content-Type': 'application/json' };
          if (authVal) headers['Authorization'] = 'Bearer ' + authVal;
          const res = await fetch('/api/slots/reset', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({ slot_key: slotKey })
          });
          const data = await res.json().catch(function () { return {}; });
          if (!res.ok || !data.ok) {
            btn.textContent = (data && data.detail) ? '正忙稍后试' : '重置失败';
            setTimeout(function () {
              btn.textContent = origText;
              btn.disabled = false;
            }, 2000);
            return;
          }
          btn.textContent = seatNum + '号已换新 ✓';
          setTimeout(function () {
            refreshStatus();
          }, 600);
        } catch (_) {
          btn.textContent = '网络异常';
          setTimeout(function () {
            btn.textContent = origText;
            btn.disabled = false;
          }, 1800);
        }
      }

      function renderSeatsGrid(slots, ctxMon) {
        const grid = document.getElementById('seatsGrid');
        const chip = document.getElementById('seatsSummaryChip');
        seatIndexByTabId = {};
        seatIndexBySlotKey = {};

        const ctxSlotsMap = {};
        if (ctxMon && Array.isArray(ctxMon.slots)) {
          ctxMon.slots.forEach(function (cs) {
            if (cs && cs.slot_key) ctxSlotsMap[cs.slot_key] = cs;
          });
        }

        if (!Array.isArray(slots) || slots.length === 0) {
          chip.textContent = '0 个席位在线';
          chip.className = 'chip warn';
          grid.replaceChildren();
          const empty = document.createElement('div');
          empty.className = 'empty-seats';
          empty.textContent = '当前还没有挂载 Google 工作页。请在 Chrome 打开并登录 vertexaisearch.cloud.google.com，席位会自动出现。';
          grid.appendChild(empty);
          return;
        }

        let busyCount = 0;
        const enrichedSlots = slots.map(function (s, idx) {
          const num = idx + 1;
          if (s.slot_key) seatIndexBySlotKey[s.slot_key] = num;
          if (s.tab_id) seatIndexByTabId[String(s.tab_id)] = num;
          const cs = ctxSlotsMap[s.slot_key] || {};
          const waitingCnt = Number(s.waiting_count || cs.waiting_count || 0);
          const isWorking = Boolean(s.busy) || waitingCnt > 0;
          if (isWorking) busyCount += 1;
          const topic = String(cs.session_title || '').trim();
          const turns = Number(cs.user_turns || cs.turn_count || 0);
          const hasActiveConv = Boolean(topic) || turns > 0 || Boolean(s.pinned_session_id);
          const lastTs = Math.max(Number(cs.updated_at || 0), Number(s.last_used_at || 0));
          return {
            slot: s,
            cs: cs,
            seatNum: num,
            waitingCnt: waitingCnt,
            isWorking: isWorking,
            topic: topic,
            titleSource: String(cs.title_source || ''),
            turns: turns,
            hasActiveConv: hasActiveConv,
            lastTs: lastTs
          };
        });

        // Auto-sort: working seats at the very top, then active conversations by recency, then standby seats
        enrichedSlots.sort(function (a, b) {
          const rankA = a.isWorking ? 0 : (a.hasActiveConv ? 1 : 2);
          const rankB = b.isWorking ? 0 : (b.hasActiveConv ? 1 : 2);
          if (rankA !== rankB) return rankA - rankB;
          if (a.isWorking && b.isWorking) {
            if (Boolean(a.slot.busy) !== Boolean(b.slot.busy)) return a.slot.busy ? -1 : 1;
            if (b.lastTs !== a.lastTs) return b.lastTs - a.lastTs;
          }
          if (rankA === 1 && b.lastTs !== a.lastTs) {
            return b.lastTs - a.lastTs;
          }
          return a.seatNum - b.seatNum;
        });

        chip.textContent = busyCount > 0
          ? (slots.length + ' 个席位在线 · ' + busyCount + ' 个工作中')
          : (slots.length + ' 个席位空闲待命');
        chip.className = busyCount > 0 ? 'chip busy' : 'chip ok';

        grid.replaceChildren();
        enrichedSlots.forEach(function (item) {
          const s = item.slot;
          const cs = item.cs;
          const seatNum = item.seatNum;
          const turns = item.turns;
          const usedTok = Number(cs.total_context_tokens || 0);
          const cmpTok = Number(cs.compact_threshold_tokens || 300000);
          const remTok = cs.remaining_to_compact_tokens !== undefined
            ? Number(cs.remaining_to_compact_tokens)
            : Math.max(0, cmpTok - usedTok);
          const cmpPct = Math.min(100, Math.max(0, Number(cs.compact_pct || 0)));

          const card = document.createElement('div');
          card.className = 'seat-card' + (item.isWorking ? ' busy' : (item.hasActiveConv ? ' active-idle' : ''));

          const top = document.createElement('div');
          top.className = 'seat-top';
          const nameWrap = document.createElement('div');
          nameWrap.className = 'seat-name';
          nameWrap.textContent = seatNum + ' 号席位';
          if (s.tab_id) {
            const idSpan = document.createElement('span');
            idSpan.className = 'seat-id';
            idSpan.textContent = '#' + String(s.tab_id).slice(-4);
            nameWrap.appendChild(idSpan);
          }
          const stateChip = document.createElement('span');
          if (item.isWorking) {
            stateChip.className = 'chip busy';
            const pulse = document.createElement('i');
            pulse.className = 'live-work-dot';
            stateChip.appendChild(pulse);
            stateChip.appendChild(document.createTextNode(s.busy ? '工作中' : ('排队 ' + item.waitingCnt)));
          } else {
            stateChip.className = 'chip ok';
            stateChip.textContent = '空闲待命';
          }
          top.appendChild(nameWrap);
          top.appendChild(stateChip);

          const topicDiv = document.createElement('div');
          if (item.topic) {
            topicDiv.className = 'seat-topic';
            topicDiv.textContent = item.topic;
            const srcMap = {
              codex: 'Codex 会话标题',
              prompt: '首条提问摘要',
              web: 'Gemini 网页标题',
              task: '专项任务'
            };
            const srcLabel = srcMap[item.titleSource] || '当前会话';
            topicDiv.title = srcLabel + '：' + item.topic +
              (s.tab_id ? ('\n标签页 ID: #' + s.tab_id) : '');
          } else {
            topicDiv.className = 'seat-topic empty';
            topicDiv.textContent = '暂无活跃会话 · 随时待命';
            topicDiv.title = s.tab_id ? ('空闲工作页 #' + s.tab_id) : '空闲工作页';
          }

          const meta = document.createElement('div');
          meta.className = 'seat-meta';
          const modelSpan = document.createElement('span');
          modelSpan.textContent = '模型: ' + friendlyModel(s.active_model || cs.active_model);
          const turnSpan = document.createElement('span');
          turnSpan.textContent = turns > 0 ? ('已聊 ' + turns + ' 轮') : ('累计 ' + (s.completed_requests || 0) + ' 次');
          meta.appendChild(modelSpan);
          meta.appendChild(turnSpan);

          const track = document.createElement('div');
          track.className = 'seat-mini-track';
          const fill = document.createElement('div');
          fill.className = 'seat-mini-fill';
          fill.style.width = cmpPct.toFixed(1) + '%';
          if (cmpPct >= 85) fill.style.background = '#f59e0b';
          track.appendChild(fill);

          const foot = document.createElement('div');
          foot.className = 'seat-foot';
          const remSpan = document.createElement('span');
          remSpan.className = 'seat-rem';
          remSpan.textContent = usedTok > 0
            ? ('已用 ' + fmtTok(usedTok) + ' · 剩 ' + fmtTok(remTok))
            : '全新空白会话';

          const rstBtn = document.createElement('button');
          rstBtn.type = 'button';
          rstBtn.className = 'btn sm';
          rstBtn.textContent = item.isWorking ? '工作中' : '开启新对话';
          rstBtn.disabled = Boolean(item.isWorking);
          rstBtn.title = item.isWorking ? '当前席位正在执行任务，完成后可重置' : '清空该席位上下文并开启全新对话';
          rstBtn.addEventListener('click', function () {
            resetSingleSeat(s.slot_key, seatNum, rstBtn);
          });

          foot.appendChild(remSpan);
          foot.appendChild(rstBtn);

          card.appendChild(top);
          card.appendChild(topicDiv);
          card.appendChild(meta);
          card.appendChild(track);
          card.appendChild(foot);
          grid.appendChild(card);
        });
      }

      function syncPeriodControls(usage) {
        const dailyMap = (usage && usage.daily) || {};
        const dayKeys = Object.keys(dailyMap).sort();
        const picker = document.getElementById('datePickerInput');
        if (dayKeys.length > 0) {
          picker.min = dayKeys[0];
          picker.max = dayKeys[dayKeys.length - 1];
        }
        if (selectedPeriod.startsWith('day:')) {
          const dk = selectedPeriod.slice(4);
          if (!dailyMap[dk]) {
            selectedPeriod = 'all';
            picker.value = '';
          } else {
            picker.value = dk;
          }
        } else {
          picker.value = '';
        }
        document.querySelectorAll('#periodTabs .period-tab').forEach(function (btn) {
          btn.classList.toggle('active', btn.getAttribute('data-period') === selectedPeriod);
        });
      }

      function resolveSelectedGroup(usage) {
        const periods = (usage && usage.periods) || {};
        const daily = (usage && usage.daily) || {};
        if (selectedPeriod.startsWith('day:')) {
          const dk = selectedPeriod.slice(4);
          if (daily[dk]) {
            return { group: daily[dk], label: dk, filterDay: dk, mode: 'day' };
          }
        }
        if (periods[selectedPeriod]) {
          let lbl = PERIOD_LABELS[selectedPeriod] || selectedPeriod;
          if (selectedPeriod === 'today' && usage.today_date) lbl = '今日 (' + usage.today_date.slice(5) + ')';
          if (selectedPeriod === 'yesterday' && usage.yesterday_date) lbl = '昨日 (' + usage.yesterday_date.slice(5) + ')';
          return {
            group: periods[selectedPeriod],
            label: lbl,
            filterDay: selectedPeriod === 'today' ? usage.today_date : (selectedPeriod === 'yesterday' ? usage.yesterday_date : null),
            mode: selectedPeriod
          };
        }
        return {
          group: { summary: usage.all_time || {}, by_model: usage.by_model || {}, by_task: usage.by_task || {} },
          label: '全部累计',
          filterDay: null,
          mode: 'all'
        };
      }

      function renderDailyBars(usage, activeFilterDay) {
        const stage = document.getElementById('dailyBarsStage');
        const dailyMap = (usage && usage.daily) || {};
        const existingDays = Object.keys(dailyMap).sort();
        const anchorStr = (usage && usage.today_date) || existingDays[existingDays.length - 1] || '';
        const daySet = {};
        existingDays.forEach(function (d) { daySet[d] = true; });
        if (anchorStr) {
          const anchorMs = Date.parse(anchorStr + 'T00:00:00Z');
          if (!isNaN(anchorMs)) {
            for (let i = 6; i >= 0; i--) {
              const dt = new Date(anchorMs - i * 86400000);
              daySet[dt.toISOString().slice(0, 10)] = true;
            }
          }
        }
        const days = Object.keys(daySet).sort().slice(-10);
        stage.replaceChildren();
        if (days.length === 0) {
          const empty = document.createElement('div');
          empty.className = 'muted';
          empty.style.margin = 'auto';
          empty.style.fontSize = '0.82rem';
          empty.textContent = '暂无按日趋势数据';
          stage.appendChild(empty);
          return;
        }

        let maxTotal = 0.0001;
        days.forEach(function (dk) {
          const s = (dailyMap[dk] && dailyMap[dk].summary) || {};
          const tot = selectedCurrency === 'USD'
            ? Number(s.equivalent_cost_usd || 0)
            : Number(s.equivalent_cost_cny || 0);
          if (tot > maxTotal) maxTotal = tot;
        });

        days.forEach(function (dk) {
          const s = (dailyMap[dk] && dailyMap[dk].summary) || {};
          const actual = selectedCurrency === 'USD'
            ? Number(s.cached_equivalent_cost_usd || 0)
            : Number(s.cached_equivalent_cost_cny || 0);
          const saved = selectedCurrency === 'USD'
            ? Number(s.saved_cost_usd || 0)
            : Number(s.saved_cost_cny || 0);
          const total = Math.max(actual + saved, 0);
          const totalPct = total > 0 ? Math.max(8, (total / maxTotal) * 100) : 3;
          const savedH = total > 0 ? (saved / total) * totalPct : 0;
          const actualH = total > 0 ? (actual / total) * totalPct : 3;

          const col = document.createElement('div');
          col.className = 'bar-col' + (activeFilterDay === dk ? ' selected' : '');
          const reqCnt = Number(s.requests || 0);
          col.title = reqCnt > 0
            ? (dk + ' · ' + reqCnt + ' 次调用\n实际折算: ' +
              fmtMoney(s.cached_equivalent_cost_usd, s.cached_equivalent_cost_cny) +
              '\n续聊省下: ' + fmtMoney(s.saved_cost_usd, s.saved_cost_cny))
            : (dk + ' · 无调用记录');

          const valTop = document.createElement('span');
          valTop.className = 'bar-val';
          valTop.textContent = reqCnt > 0
            ? fmtMoney(s.cached_equivalent_cost_usd, s.cached_equivalent_cost_cny)
            : '';

          const stack = document.createElement('div');
          stack.className = 'bar-stack';
          const segSaved = document.createElement('div');
          segSaved.className = 'bar-seg-saved';
          segSaved.style.height = savedH.toFixed(1) + '%';
          const segActual = document.createElement('div');
          segActual.className = 'bar-seg-actual';
          segActual.style.height = actualH.toFixed(1) + '%';
          stack.appendChild(segSaved);
          stack.appendChild(segActual);

          const lbl = document.createElement('span');
          lbl.className = 'bar-lbl';
          lbl.textContent = dk.slice(5);

          col.appendChild(valTop);
          col.appendChild(stack);
          col.appendChild(lbl);
          if (reqCnt > 0) {
            col.addEventListener('click', function () {
              selectedPeriod = (selectedPeriod === 'day:' + dk) ? 'all' : ('day:' + dk);
              if (lastUsageSnapshot) renderLedger(lastUsageSnapshot, lastCtxSnapshot);
            });
          } else {
            col.style.cursor = 'default';
          }
          stage.appendChild(col);
        });
      }

      function renderTaskBreakdown(byTask, totalRequests) {
        const bar = document.getElementById('taskRatioBar');
        const list = document.getElementById('taskBreakdownList');
        bar.replaceChildren();
        list.replaceChildren();

        const entries = Object.keys(byTask || {})
          .map(function (k) {
            const item = byTask[k] || {};
            const meta = TASK_META[k] || { label: item.label || k, color: '#94a3b8' };
            return {
              key: k,
              label: meta.label,
              color: meta.color,
              requests: Number(item.requests || 0),
              usd: Number(item.cached_equivalent_cost_usd || 0),
              cny: Number(item.cached_equivalent_cost_cny || (Number(item.cached_equivalent_cost_usd || 0) * 6.8))
            };
          })
          .filter(function (x) { return x.requests > 0; })
          .sort(function (a, b) { return b.requests - a.requests; });

        if (entries.length === 0 || totalRequests <= 0) {
          const empty = document.createElement('div');
          empty.className = 'muted';
          empty.style.fontSize = '0.8rem';
          empty.textContent = '当前时间段暂无调用记录';
          list.appendChild(empty);
          return;
        }

        entries.forEach(function (e) {
          const pct = Math.max(2, (e.requests / totalRequests) * 100);
          const seg = document.createElement('div');
          seg.style.width = pct.toFixed(1) + '%';
          seg.style.background = e.color;
          seg.title = e.label + ': ' + e.requests + ' 次';
          bar.appendChild(seg);

          const row = document.createElement('div');
          row.className = 'task-row';
          const left = document.createElement('div');
          left.className = 'task-row-left';
          const dot = document.createElement('i');
          dot.className = 'leg-dot';
          dot.style.background = e.color;
          const name = document.createElement('span');
          name.textContent = e.label;
          left.appendChild(dot);
          left.appendChild(name);

          const right = document.createElement('div');
          right.className = 'task-row-right';
          right.textContent = e.requests + ' 次 (' + Math.round((e.requests / totalRequests) * 100) + '%) · ' + fmtMoney(e.usd, e.cny);

          row.appendChild(left);
          row.appendChild(right);
          list.appendChild(row);
        });
      }

      function renderLedger(usage, ctxMon) {
        if (!usage) return;
        lastUsageSnapshot = usage;
        lastCtxSnapshot = ctxMon;
        syncPeriodControls(usage);

        const resolved = resolveSelectedGroup(usage);
        const curSummary = (resolved.group && resolved.group.summary) || {};
        const byModel = (resolved.group && resolved.group.by_model) || {};
        const byTask = (resolved.group && resolved.group.by_task) || {};
        const pLabel = resolved.label;
        const ap = usage.active_pricing || {};
        const fx = Number(usage.usd_to_cny_rate || 6.8);

        if (ap.display_name) {
          document.getElementById('ledgerRateBadge').textContent =
            friendlyModel(ap.display_name) + ' · 汇率 ' + fx;
        }

        document.getElementById('activePeriodTag').textContent = pLabel;
        document.getElementById('reuseRateChip').textContent = '记忆复用 ' + (curSummary.cache_hit_pct || 0) + '%';

        document.getElementById('ledgerSavedMain').textContent =
          fmtMoney(curSummary.saved_cost_usd, curSummary.saved_cost_cny);
        document.getElementById('ledgerSavedSub').textContent =
          '若每次全量重发原价约 ' + fmtMoney(curSummary.equivalent_cost_usd, curSummary.equivalent_cost_cny);

        document.getElementById('ledgerActualMain').textContent =
          fmtMoney(curSummary.cached_equivalent_cost_usd, curSummary.cached_equivalent_cost_cny);
        document.getElementById('ledgerActualSub').textContent =
          '本地字数估算折算 · 并非 Google 真实扣费';

        const reqCount = Number(curSummary.requests || 0);
        const respCnt = (byTask.responses && byTask.responses.requests) || 0;
        const chatCnt = (byTask.chat && byTask.chat.requests) || 0;
        const cmpCnt = Number(curSummary.compactions || 0);
        const mediaCnt = Number(curSummary.images_generated || 0) + Number(curSummary.videos_generated || 0) + Number(curSummary.audio_requests || 0);
        document.getElementById('ledgerCallsMain').textContent = reqCount.toLocaleString() + ' 次';
        document.getElementById('ledgerCallsSub').textContent =
          'Codex ' + respCnt + ' · 对话 ' + chatCnt + ' · 记忆整理 ' + cmpCnt + (mediaCnt > 0 ? (' · 多媒体 ' + mediaCnt) : '');

        document.getElementById('ledgerWordsMain').textContent = fmtWordsScale(curSummary.total_tokens);
        document.getElementById('ledgerWordsSub').textContent =
          '新增 ' + fmtTok(curSummary.delta_prompt_tokens) + ' · 复用 ' + fmtTok(curSummary.cached_tokens) + ' · 回复 ' + fmtTok(curSummary.completion_tokens);

        // Primary Context Monitor Bar
        const cm = ctxMon || {};
        const prim = cm.primary || {};
        const cTok = Number(prim.total_context_tokens || 0);
        const cLim = Number(prim.context_limit_tokens || 1048576);
        const cCmp = Number(prim.compact_threshold_tokens || 300000);
        const remCmp = prim.remaining_to_compact_tokens !== undefined
          ? Number(prim.remaining_to_compact_tokens)
          : Math.max(0, cCmp - cTok);
        const cmpPct = Number(prim.compact_pct || 0);

        document.getElementById('ledgerCtxPct').textContent =
          '已用 ' + fmtTok(cTok) + ' / 自动整理线 ' + fmtTok(cCmp) + ' (' + cmpPct.toFixed(1) + '% · 还剩 ' + fmtTok(remCmp) + ') · 总容量 ' + fmtTok(cLim);
        const fill = document.getElementById('ledgerCtxFill');
        fill.style.width = Math.min(100, Math.max(0, cmpPct)).toFixed(1) + '%';
        fill.className = cmpPct >= 100 ? 'ctx-fill danger' : (cmpPct >= 80 ? 'ctx-fill warn' : 'ctx-fill');
        const primTopic = prim.session_title ? (' · 「' + prim.session_title.slice(0, 22) + (prim.session_title.length > 22 ? '…' : '') + '」') : '';
        document.getElementById('ledgerCtxTitle').textContent =
          ((prim.turn_count || 0) > 0 || prim.busy || prim.session_title)
            ? ('主活跃对话（' + friendlySeatLabel(prim.slot_key, prim.tab_id) + primTopic + ' · ' + friendlyModel(prim.active_model) + ((prim.user_turns || prim.turn_count) > 0 ? (' · 第 ' + (prim.user_turns || prim.turn_count) + ' 轮') : ' · 工作中') + '）')
            : ('主活跃对话记忆池 · 空闲待命 (自动整理线 ' + fmtTok(cCmp) + ')');

        renderDailyBars(usage, resolved.filterDay);
        renderTaskBreakdown(byTask, reqCount);

        // Model Table
        const modelBody = document.getElementById('ledgerModelBody');
        const modelKeys = Object.keys(byModel);
        if (modelKeys.length === 0) {
          renderEmptyRow(modelBody, 6, '当前时间范围暂无模型记录');
        } else {
          modelBody.replaceChildren();
          modelKeys.forEach(function (mk) {
            const m = byModel[mk] || {};
            const tr = document.createElement('tr');
            tr.appendChild(makeCell(m.display_name || friendlyModel(mk)));
            tr.appendChild(makeCell((m.requests || 0) + ' 次'));
            tr.appendChild(makeCell(fmtTok(m.prompt_tokens) + ' / ' + fmtTok(m.cached_tokens) + ' / ' + fmtTok(m.completion_tokens)));
            const mediaParts = [];
            if (m.images_generated) mediaParts.push(m.images_generated + ' 张图');
            if (m.videos_generated) mediaParts.push(m.videos_generated + ' 条视频');
            if (m.audio_requests) mediaParts.push(m.audio_requests + ' 次语音');
            if (m.compactions) mediaParts.push(m.compactions + ' 次整理');
            tr.appendChild(makeCell(mediaParts.length > 0 ? mediaParts.join(' · ') : '-'));
            tr.appendChild(makeCell(fmtMoney(m.equivalent_cost_usd, m.equivalent_cost_cny)));
            tr.appendChild(makeCell(
              fmtMoney(m.cached_equivalent_cost_usd, m.cached_equivalent_cost_cny) +
              '（省 ' + fmtMoney(m.saved_cost_usd, m.saved_cost_cny) + '）'
            ));
            modelBody.appendChild(tr);
          });
        }

        // Daily Table
        const dailyBody = document.getElementById('ledgerDailyBody');
        const dailyMap = usage.daily || {};
        const sortedDays = Object.keys(dailyMap).sort().reverse().slice(0, 30);
        if (sortedDays.length === 0) {
          renderEmptyRow(dailyBody, 6, '暂无按日统计记录');
        } else {
          dailyBody.replaceChildren();
          sortedDays.forEach(function (dk) {
            const ds = (dailyMap[dk] && dailyMap[dk].summary) || {};
            const tr = document.createElement('tr');
            if (resolved.filterDay === dk) tr.style.background = '#eff6ff';
            tr.appendChild(makeCell(dk));
            tr.appendChild(makeCell((ds.requests || 0) + ' 次'));
            const dParts = [];
            if (ds.compactions) dParts.push(ds.compactions + ' 次整理');
            if (ds.images_generated) dParts.push(ds.images_generated + ' 张图');
            if (ds.videos_generated) dParts.push(ds.videos_generated + ' 条视频');
            if (ds.audio_requests) dParts.push(ds.audio_requests + ' 次语音');
            tr.appendChild(makeCell(dParts.length > 0 ? dParts.join(' · ') : '常规对话与编程'));
            tr.appendChild(makeCell(fmtMoney(ds.equivalent_cost_usd, ds.equivalent_cost_cny)));
            tr.appendChild(makeCell(fmtMoney(ds.cached_equivalent_cost_usd, ds.cached_equivalent_cost_cny)));
            tr.appendChild(makeCell(
              fmtMoney(ds.saved_cost_usd, ds.saved_cost_cny) + '（' + (ds.cache_hit_pct || 0) + '%）'
            ));
            dailyBody.appendChild(tr);
          });
        }

        // Recent Requests Table (humanized labels)
        const recentBody = document.getElementById('ledgerRecentBody');
        const allRecents = Array.isArray(usage.recent_requests) ? usage.recent_requests : [];
        const startedAt = Number(usage.started_at || 0);
        const todayStr = usage.today_date || '';
        const filteredRecents = allRecents.filter(function (r) {
          if (resolved.filterDay) return r.day === resolved.filterDay;
          if (resolved.mode === 'session') return Number(r.ts || 0) >= startedAt;
          if (resolved.mode === '7d' && todayStr && r.day) {
            const diff = (Date.parse(todayStr) - Date.parse(r.day)) / 86400000;
            return diff >= 0 && diff <= 6;
          }
          if (resolved.mode === '30d' && todayStr && r.day) {
            const diff = (Date.parse(todayStr) - Date.parse(r.day)) / 86400000;
            return diff >= 0 && diff <= 29;
          }
          return true;
        }).slice(0, 15);

        if (filteredRecents.length === 0) {
          renderEmptyRow(recentBody, 7, '当前时间范围暂无调用流水');
        } else {
          recentBody.replaceChildren();
          filteredRecents.forEach(function (r) {
            const tr = document.createElement('tr');
            const tStr = r.ts ? ((r.day ? r.day.slice(5) + ' ' : '') + new Date(r.ts * 1000).toLocaleTimeString()) : '-';
            const tMeta = TASK_META[r.task_type] || { label: r.task_label || '常规调用' };
            tr.appendChild(makeCell(tStr));
            tr.appendChild(makeCell(tMeta.label));
            tr.appendChild(makeCell(friendlyModel(r.display_name || r.model) + ' · ' + friendlySeatLabel(r.slot_key, r.tab_id)));
            tr.appendChild(makeCell(friendlyStrategyBadge(r.strategy)));
            const newTok = r.delta_prompt_tokens !== undefined ? r.delta_prompt_tokens : r.prompt_tokens;
            tr.appendChild(makeCell(fmtTok(newTok) + ' / ' + fmtTok(r.cached_tokens) + ' / ' + fmtTok(r.completion_tokens)));
            tr.appendChild(makeCell(
              fmtMoney(r.cached_equivalent_cost_usd, r.cached_equivalent_cost_cny) +
              '（省 ' + fmtMoney(r.saved_cost_usd, r.saved_cost_cny) + '）'
            ));
            tr.appendChild(makeCell(((Number(r.duration_ms || 0)) / 1000).toFixed(1) + ' 秒'));
            recentBody.appendChild(tr);
          });
        }
      }

      async function refreshStatus() {
        try {
          const res = await fetch('/api/status');
          const data = await res.json();
          const dot = document.getElementById('connDot');
          const txt = document.getElementById('connText');
          const hub = data.hub || {};
          const clients = hub.clients || [];
          const slots = hub.worker_slots || [];
          const active = hub.active_client;
          const defModelName = friendlyModel(data.default_model || 'gemini-4-carbon');

          // Step 1: Local Service
          setStepState(
            'stepServiceCard', 'stepServiceIcon', 'stepServiceDesc', 'stepServiceTag',
            'ok', '✓', '127.0.0.1:8000 · 默认 ' + defModelName, '运行正常'
          );

          // Step 2 & 3: Extension & Google Tabs
          const extOnline = clients.length > 0 || slots.length > 0 || Boolean(active);
          const authBtn = document.getElementById('stepAuthBtn');

          if (!extOnline) {
            setStepState(
              'stepExtCard', 'stepExtIcon', 'stepExtDesc', 'stepExtTag',
              'warn', '!', '请检查 Chrome 右上角桥接插件是否开启', '待连接'
            );
            setStepState(
              'stepAuthCard', 'stepAuthIcon', 'stepAuthDesc', 'stepAuthTag',
              'warn', '3', '插件连接后自动识别 Google 页面', '等待中'
            );
            authBtn.hidden = false;
            dot.className = 'dot err';
            txt.textContent = '等待浏览器插件连接';
          } else if (slots.length === 0) {
            setStepState(
              'stepExtCard', 'stepExtIcon', 'stepExtDesc', 'stepExtTag',
              'ok', '✓', '浏览器插件已连接 · 支持自动扩容', '已连通'
            );
            setStepState(
              'stepAuthCard', 'stepAuthIcon', 'stepAuthDesc', 'stepAuthTag',
              'warn', '!', '尚未打开或登录 Google Enterprise 网页', '需打开页面'
            );
            authBtn.hidden = false;
            dot.className = 'dot';
            txt.textContent = '插件已连 · 请打开 Google 工作页';
          } else {
            setStepState(
              'stepExtCard', 'stepExtIcon', 'stepExtDesc', 'stepExtTag',
              'ok', '✓', '实时通道在线 · 上限 ' + (hub.max_parallel_tabs || 10) + ' 页并行', '已连通'
            );
            setStepState(
              'stepAuthCard', 'stepAuthIcon', 'stepAuthDesc', 'stepAuthTag',
              'ok', '✓', '已就绪 ' + slots.length + ' 个工作页 · 可随时对话', '登录有效'
            );
            authBtn.hidden = true;
            dot.className = 'dot ok';
            txt.textContent = '一切就绪 · ' + slots.length + ' 个工作页待命';
          }

          renderSeatsGrid(slots, data.context_monitor);

          if (data.usage) {
            renderLedger(data.usage, data.context_monitor);
          }

          // Diagnostics drawer
          document.getElementById('modeVal').textContent = '浏览器桥接 · 智能增量记忆';
          document.getElementById('transportVal').textContent =
            extOnline ? ('WebSocket 实时双工 · 上限 ' + (hub.max_parallel_tabs || 10) + ' 并发') : '未连接';
          document.getElementById('rpcVal').textContent =
            (active && active.captured_rpc) ? '已捕获流式通道' : '页面组件与流式双监听';
          document.getElementById('statsVal').textContent =
            (hub.active_slots_busy || 0) + ' 进行中 / ' + (hub.queued_requests || 0) + ' 排队 / ' + (hub.total_requests || 0) + ' 累计';
          document.getElementById('diagStatsChip').textContent = '累计 ' + (hub.total_requests || 0) + ' 次请求';

          const logs = hub.recent_logs || [];
          const logsBox = document.getElementById('logsBox');
          if (logs.length === 0) {
            logsBox.textContent = '暂无运行记录';
          } else {
            logsBox.replaceChildren();
            logs.slice().reverse().forEach(function (item) {
              const div = document.createElement('div');
              div.className = 'log-item';
              const t = new Date(item.ts * 1000).toLocaleTimeString();
              div.textContent = '[' + t + '] ' + item.message;
              logsBox.appendChild(div);
            });
          }
        } catch (_) {
          document.getElementById('connDot').className = 'dot err';
          document.getElementById('connText').textContent = '本地服务未响应';
          setStepState(
            'stepServiceCard', 'stepServiceIcon', 'stepServiceDesc', 'stepServiceTag',
            'err', '✕', '本地 8000 服务未启动或正在重启', '离线'
          );
        }
      }

      async function executeTestRequest(isQuickProbe) {
        const box = document.getElementById('probeResultBox');
        const resTitle = document.getElementById('probeResTitle');
        const resMeta = document.getElementById('probeResMeta');
        const out = document.getElementById('replyOut');
        const quickBtn = document.getElementById('quickProbeBtn');
        const customBtn = document.getElementById('sendBtn');
        const chosenModel = document.getElementById('modelSelect').value || 'gemini-4-carbon';
        const modelName = friendlyModel(chosenModel);

        const prompt = isQuickProbe
          ? '你好，这是一次连通性体检，请仅用简短中文回复“连接正常”即可。'
          : document.getElementById('promptInput').value.trim();

        if (!prompt) {
          box.hidden = false;
          box.className = 'probe-result err';
          resTitle.textContent = '请先输入测试内容';
          resMeta.textContent = '提示';
          out.textContent = '自定义测试需要填写问题；如果不想打字，直接点击上方的“一键快速体检”即可。';
          return;
        }

        quickBtn.disabled = true;
        customBtn.disabled = true;
        box.hidden = false;
        box.className = 'probe-result';
        resTitle.textContent = '正在测试 ' + modelName + ' ...';
        resMeta.textContent = '等待回复中';
        resMeta.className = 'chip busy';
        out.textContent = '';

        const t0 = performance.now();
        const authVal = document.getElementById('apiKeyInput').value.trim();
        const headers = {};
        if (authVal) headers['Authorization'] = 'Bearer ' + authVal;

        try {
          let messageContent = prompt;
          if (!isQuickProbe) {
            const fileEl = document.getElementById('fileInput');
            const picked = fileEl && fileEl.files ? Array.from(fileEl.files) : [];
            if (picked.length > 0) {
              const parts = [{ type: 'text', text: prompt }];
              for (const f of picked) {
                const fd = new FormData();
                fd.append('file', f, f.name);
                fd.append('purpose', 'user_data');
                const upRes = await fetch('/v1/files', { method: 'POST', headers: headers, body: fd });
                if (!upRes.ok) {
                  throw new Error('附件上传失败：' + (await upRes.text()));
                }
                const upMeta = await upRes.json();
                if (upMeta.category === 'image') {
                  parts.push({ type: 'image_url', image_url: { url: upMeta.id } });
                } else if (upMeta.category === 'audio') {
                  parts.push({ type: 'input_audio', file_id: upMeta.id, filename: upMeta.filename });
                } else if (upMeta.category === 'video') {
                  parts.push({ type: 'video_url', file_id: upMeta.id, filename: upMeta.filename });
                } else {
                  parts.push({ type: 'file', file: { file_id: upMeta.id, filename: upMeta.filename, mime_type: upMeta.mime_type } });
                }
              }
              messageContent = parts;
            }
          }

          const reqHeaders = Object.assign({ 'Content-Type': 'application/json' }, headers);
          const earlyPollTimer = setTimeout(refreshStatus, 280);
          const res = await fetch('/v1/chat/completions', {
            method: 'POST',
            headers: reqHeaders,
            body: JSON.stringify({
              model: chosenModel,
              stream: true,
              messages: [{ role: 'user', content: messageContent }]
            })
          });
          clearTimeout(earlyPollTimer);
          refreshStatus();
          if (!res.ok) {
            throw new Error('服务返回错误 (' + res.status + ')：' + (await res.text()));
          }
          const reader = res.body.getReader();
          const decoder = new TextDecoder('utf-8');
          let buffer = '';
          while (true) {
            const step = await reader.read();
            if (step.done) break;
            buffer += decoder.decode(step.value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';
            for (const line of lines) {
              const trimmed = line.trim();
              if (!trimmed.startsWith('data:')) continue;
              const payload = trimmed.slice(5).trim();
              if (payload === '[DONE]') continue;
              try {
                const parsed = JSON.parse(payload);
                const delta = parsed.choices && parsed.choices[0] && parsed.choices[0].delta;
                if (delta && delta.content) {
                  out.textContent += delta.content;
                }
              } catch (_) {}
            }
          }
          const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
          box.className = 'probe-result ok';
          resTitle.textContent = '✓ 测试通过 · ' + modelName + ' 回复正常';
          resMeta.textContent = '耗时 ' + elapsed + ' 秒';
          resMeta.className = 'chip ok';
          if (!out.textContent.trim()) {
            out.textContent = '（已收到正常完成信号）';
          }
        } catch (err) {
          box.className = 'probe-result err';
          resTitle.textContent = '✕ 测试未通过';
          resMeta.textContent = '请检查连接状态';
          resMeta.className = 'chip warn';
          out.textContent = String(err.message || err);
        } finally {
          quickBtn.disabled = false;
          customBtn.disabled = false;
          await refreshStatus();
        }
      }

      document.getElementById('modelSelect').addEventListener('change', function (ev) {
        document.getElementById('probeHeaderChip').textContent = '当前测 ' + friendlyModel(ev.target.value);
      });
      document.getElementById('quickProbeBtn').addEventListener('click', function () {
        executeTestRequest(true);
      });
      document.getElementById('sendBtn').addEventListener('click', function () {
        executeTestRequest(false);
      });
      document.getElementById('refreshBtn').addEventListener('click', refreshStatus);

      document.getElementById('periodTabs').addEventListener('click', function (ev) {
        const btn = ev.target && ev.target.closest('.period-tab');
        if (!btn) return;
        const p = btn.getAttribute('data-period');
        if (!p) return;
        selectedPeriod = p;
        document.getElementById('datePickerInput').value = '';
        if (lastUsageSnapshot) renderLedger(lastUsageSnapshot, lastCtxSnapshot);
      });

      document.getElementById('datePickerInput').addEventListener('change', function (ev) {
        const val = ev.target.value;
        selectedPeriod = val ? ('day:' + val) : 'all';
        if (lastUsageSnapshot) renderLedger(lastUsageSnapshot, lastCtxSnapshot);
      });

      // Guide Modal & One-Click Copy
      const modal = document.getElementById('guideModal');
      document.getElementById('openGuideBtn').addEventListener('click', function () {
        modal.hidden = false;
      });
      document.getElementById('closeGuideBtn').addEventListener('click', function () {
        modal.hidden = true;
      });
      modal.addEventListener('click', function (ev) {
        if (ev.target === modal) modal.hidden = true;
      });
      document.addEventListener('keydown', function (ev) {
        if (ev.key === 'Escape' && !modal.hidden) modal.hidden = true;
      });

      document.querySelectorAll('[data-copy-target]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
          const tid = btn.getAttribute('data-copy-target');
          const el = document.getElementById(tid);
          if (!el) return;
          const text = el.textContent.trim();
          const orig = btn.textContent;
          try {
            await navigator.clipboard.writeText(text);
            btn.textContent = '已复制 ✓';
          } catch (_) {
            btn.textContent = '请手动复制';
          }
          setTimeout(function () { btn.textContent = orig; }, 1400);
        });
      });

      refreshStatus();
      setInterval(function () {
        if (!document.hidden) refreshStatus();
      }, 1500);
      document.addEventListener('visibilitychange', function () {
        if (!document.hidden) refreshStatus();
      });
    })();
  </script>
</body>
</html>
"""
