"""
Dashboard Preview Server (v1)
───────────────────────────────────────────────────────────────────────────
Khởi chạy một local web server tại http://localhost:8000 phục vụ Dashboard
để xem kết quả crawl và preview trực quan các file HTML đã lưu.

Yêu cầu: Chỉ sử dụng thư viện tiêu chuẩn của Python (không cần cài thêm).
Cách chạy:
    python dashboard.py
"""

import http.server
import socketserver
import json
import urllib.parse
import webbrowser
import threading
import time
import sys
from pathlib import Path
from datetime import datetime

# Ghi đè hàm print để tránh lỗi Unicode trên Windows console (CP1258...)
def safe_print(*args, **kwargs):
    msg = " ".join(str(arg) for arg in args)
    enc = sys.stdout.encoding or "utf-8"
    end = kwargs.get("end", "\n")
    try:
        sys.stdout.write(msg.encode(enc, errors="replace").decode(enc) + end)
        sys.stdout.flush()
    except Exception:
        try:
            sys.stdout.write(msg.encode("ascii", errors="replace").decode("ascii") + end)
            sys.stdout.flush()
        except Exception:
            pass

print = safe_print

# Cấu hình đường dẫn
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
DEFAULT_PORT = 8000

# HTML, CSS và JS được nhúng làm Single Page Application (SPA) cao cấp
HTML_UI = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ekaigo Crawler Dashboard</title>
    
    <!-- Google Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    
    <style>
        :root {
            --bg-base: #0b0f19;
            --bg-sidebar: #111827;
            --bg-panel: #1e293b;
            --bg-card: rgba(30, 41, 59, 0.6);
            --bg-card-hover: rgba(30, 41, 59, 0.9);
            --bg-card-selected: rgba(99, 102, 241, 0.15);
            
            --border-color: rgba(255, 255, 255, 0.08);
            --border-selected: rgba(99, 102, 241, 0.5);
            
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
            --text-accent: #818cf8;
            
            --accent: #6366f1;
            --accent-hover: #4f46e5;
            --accent-light: rgba(99, 102, 241, 0.1);
            
            --success: #10b981;
            --warning: #f59e0b;
            
            --font-main: 'Inter', sans-serif;
            --font-header: 'Outfit', sans-serif;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: var(--font-main);
            background-color: var(--bg-base);
            color: var(--text-main);
            height: 100vh;
            display: flex;
            overflow: hidden;
        }

        /* Layout */
        .app-container {
            display: flex;
            width: 100vw;
            height: 100vh;
            overflow: hidden;
        }

        /* Sidebar: Session selector & Stats */
        .sidebar {
            width: 320px;
            background-color: var(--bg-sidebar);
            border-right: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            flex-shrink: 0;
            padding: 20px;
            z-index: 10;
        }

        .logo-container {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 24px;
        }

        .logo-icon {
            width: 36px;
            height: 36px;
            background: linear-gradient(135deg, var(--accent), #ec4899);
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: var(--font-header);
            font-weight: 800;
            font-size: 1.2rem;
            color: #fff;
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
        }

        .logo-text h1 {
            font-family: var(--font-header);
            font-size: 1.25rem;
            font-weight: 700;
            background: linear-gradient(to right, #ffffff, #d1d5db);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .logo-text p {
            font-size: 0.75rem;
            color: var(--text-muted);
            letter-spacing: 0.05em;
        }

        .section-title {
            font-family: var(--font-header);
            font-size: 0.85rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .form-group {
            margin-bottom: 24px;
        }

        select {
            width: 100%;
            background-color: var(--bg-panel);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 12px;
            border-radius: 8px;
            font-size: 0.9rem;
            font-family: var(--font-main);
            outline: none;
            cursor: pointer;
            transition: border-color 0.2s, box-shadow 0.2s;
        }

        select:focus {
            border-color: var(--accent);
            box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
        }

        /* Stats Panel */
        .stats-container {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-bottom: 24px;
        }

        .stat-card {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            padding: 12px;
            border-radius: 8px;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .stat-val {
            font-family: var(--font-header);
            font-size: 1.4rem;
            font-weight: 700;
            color: var(--text-main);
        }

        .stat-label {
            font-size: 0.75rem;
            color: var(--text-muted);
        }

        .metadata-panel {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            padding: 14px;
            border-radius: 8px;
            font-size: 0.8rem;
            line-height: 1.5;
            flex-grow: 1;
            overflow-y: auto;
        }

        .metadata-item {
            margin-bottom: 10px;
        }

        .metadata-label {
            color: var(--text-muted);
            font-weight: 500;
            margin-bottom: 2px;
        }

        .metadata-val {
            color: var(--text-main);
            word-break: break-all;
            font-family: monospace;
            background-color: rgba(0, 0, 0, 0.2);
            padding: 2px 6px;
            border-radius: 4px;
            display: inline-block;
        }

        /* Jobs Panel (Middle List) */
        .jobs-panel {
            width: 420px;
            border-right: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            flex-shrink: 0;
            background-color: rgba(15, 23, 42, 0.3);
        }

        .search-container {
            padding: 20px;
            border-bottom: 1px solid var(--border-color);
        }

        .search-box-wrapper {
            position: relative;
        }

        .search-box {
            width: 100%;
            background-color: var(--bg-panel);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 12px 12px 12px 40px;
            border-radius: 8px;
            font-size: 0.9rem;
            outline: none;
            transition: border-color 0.2s;
        }

        .search-box:focus {
            border-color: var(--accent);
        }

        .search-icon {
            position: absolute;
            left: 14px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-muted);
            pointer-events: none;
        }

        .jobs-list-header {
            padding: 10px 20px;
            font-size: 0.8rem;
            color: var(--text-muted);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
            background-color: rgba(0, 0, 0, 0.1);
        }

        .jobs-list {
            flex-grow: 1;
            overflow-y: auto;
            padding: 12px 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        /* Job Card */
        .job-card {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 14px;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            overflow: hidden;
        }

        .job-card::before {
            content: '';
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            width: 4px;
            background-color: transparent;
            transition: background-color 0.2s;
        }

        .job-card:hover {
            background-color: var(--bg-card-hover);
            transform: translateY(-2px);
            border-color: rgba(255, 255, 255, 0.15);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
        }

        .job-card.selected {
            background-color: var(--bg-card-selected);
            border-color: var(--border-selected);
        }

        .job-card.selected::before {
            background-color: var(--accent);
        }

        .job-title {
            font-size: 0.95rem;
            font-weight: 600;
            line-height: 1.4;
            margin-bottom: 8px;
            color: var(--text-main);
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }

        .job-meta-row {
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-top: 6px;
        }

        .job-company {
            font-weight: 500;
            color: var(--text-accent);
            display: -webkit-box;
            -webkit-line-clamp: 1;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }

        .badge {
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.7rem;
            font-weight: 500;
            background-color: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.05);
            color: var(--text-muted);
            white-space: nowrap;
        }

        .badge-accent {
            background-color: var(--accent-light);
            border-color: rgba(99, 102, 241, 0.2);
            color: var(--text-accent);
        }

        /* Preview Panel (Right Side) */
        .preview-panel {
            flex-grow: 1;
            display: flex;
            flex-direction: column;
            height: 100%;
            overflow: hidden;
            background-color: #0b0f19;
            position: relative;
        }

        .preview-header {
            height: 64px;
            border-bottom: 1px solid var(--border-color);
            background-color: var(--bg-sidebar);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 24px;
            flex-shrink: 0;
        }

        .preview-header-left {
            display: flex;
            flex-direction: column;
            max-width: 60%;
        }

        .preview-header-title {
            font-family: var(--font-header);
            font-size: 0.95rem;
            font-weight: 600;
            color: var(--text-main);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .preview-header-subtitle {
            font-size: 0.75rem;
            color: var(--text-muted);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin-top: 2px;
        }

        .preview-actions {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .btn {
            background-color: var(--bg-panel);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 8px 14px;
            border-radius: 6px;
            font-size: 0.85rem;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            font-family: var(--font-main);
            font-weight: 500;
            transition: all 0.2s;
            text-decoration: none;
        }

        .btn:hover {
            background-color: rgba(255, 255, 255, 0.05);
            border-color: rgba(255, 255, 255, 0.2);
        }

        .btn-primary {
            background-color: var(--accent);
            border-color: transparent;
        }

        .btn-primary:hover {
            background-color: var(--accent-hover);
        }

        .layout-toggle {
            display: flex;
            background-color: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 2px;
        }

        .layout-btn {
            background: none;
            border: none;
            color: var(--text-muted);
            padding: 6px 10px;
            font-size: 0.8rem;
            cursor: pointer;
            border-radius: 4px;
            transition: all 0.2s;
        }

        .layout-btn.active {
            background-color: rgba(255, 255, 255, 0.08);
            color: var(--text-main);
        }

        /* Iframe Preview Container */
        .iframe-container {
            flex-grow: 1;
            position: relative;
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 16px;
            background-color: #0d1220;
        }

        iframe {
            width: 100%;
            height: 100%;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            background-color: #ffffff;
            transition: max-width 0.3s ease;
        }

        iframe.mobile-view {
            max-width: 410px;
            box-shadow: 0 12px 36px rgba(0, 0, 0, 0.6);
            border: 8px solid #1e293b;
            border-radius: 24px;
            height: 85%;
        }

        /* Detail Modal / Panel */
        .detail-panel {
            background-color: var(--bg-sidebar);
            border-bottom: 1px solid var(--border-color);
            padding: 18px 24px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            flex-shrink: 0;
        }

        .detail-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
        }

        .detail-item {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .detail-label {
            font-size: 0.75rem;
            color: var(--text-muted);
            font-weight: 500;
        }

        .detail-val {
            font-size: 0.85rem;
            color: var(--text-main);
            font-weight: 600;
        }

        .detail-longtext {
            font-size: 0.85rem;
            background-color: rgba(0, 0, 0, 0.2);
            padding: 10px;
            border-radius: 6px;
            max-height: 80px;
            overflow-y: auto;
            white-space: pre-wrap;
            border: 1px solid var(--border-color);
        }

        /* Statuses */
        .no-data {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            gap: 16px;
            color: var(--text-muted);
            text-align: center;
            padding: 40px;
        }

        .no-data-icon {
            font-size: 3rem;
        }

        /* Styled scrollbars */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }

        ::-webkit-scrollbar-track {
            background: transparent;
        }

        ::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 4px;
        }

        ::-webkit-scrollbar-thumb:hover {
            background: rgba(255, 255, 255, 0.2);
        }
    </style>
</head>
<body>
    <div class="app-container">
        
        <!-- Sidebar -->
        <div class="sidebar">
            <div class="logo-container">
                <div class="logo-icon">J</div>
                <div class="logo-text">
                    <h1>Ekaigo Scraper</h1>
                    <p>VERSION 1.0 (PREVIEW)</p>
                </div>
            </div>
            
            <div class="form-group">
                <div class="section-title">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
                    Phiên Crawl (Runs)
                </div>
                <select id="session-select">
                    <option value="">Đang tải các phiên...</option>
                </select>
            </div>
            
            <div class="section-title">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>
                Thống kê phiên
            </div>
            <div class="stats-container">
                <div class="stat-card">
                    <span class="stat-val" id="stat-jobs">-</span>
                    <span class="stat-label">Tổng số Job</span>
                </div>
                <div class="stat-card">
                    <span class="stat-val" id="stat-pages">-</span>
                    <span class="stat-label">Số trang</span>
                </div>
            </div>
            
            <div class="section-title" style="margin-top: 10px;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
                Thông tin bổ sung
            </div>
            <div class="metadata-panel" id="metadata-details">
                Chọn một phiên để xem thông tin chi tiết.
            </div>
        </div>
        
        <!-- Jobs List Panel -->
        <div class="jobs-panel">
            <div class="search-container">
                <div class="search-box-wrapper">
                    <svg class="search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                    <input type="text" class="search-box" id="search-input" placeholder="Tìm kiếm jobs, công ty, lương...">
                </div>
            </div>
            
            <div class="jobs-list-header">
                <span id="jobs-count">Hiển thị 0 jobs</span>
                <span class="badge" id="current-filter-badge">Tất cả</span>
            </div>
            
            <div class="jobs-list" id="jobs-list">
                <div class="no-data">
                    <span class="no-data-icon">📁</span>
                    <p>Không tìm thấy job nào. Hãy chọn một phiên crawl.</p>
                </div>
            </div>
        </div>
        
        <!-- Preview Panel -->
        <div class="preview-panel">
            <div id="active-job-details" class="detail-panel" style="display: none;">
                <div class="detail-grid">
                    <div class="detail-item">
                        <span class="detail-label">Công ty / Cơ sở</span>
                        <span class="detail-val" id="det-company">-</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">Mức lương</span>
                        <span class="detail-val" id="det-salary">-</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">Địa điểm làm việc</span>
                        <span class="detail-val" id="det-location">-</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">Hình thức / Vị trí</span>
                        <span class="detail-val" id="det-jobtype">-</span>
                    </div>
                </div>
                <div class="detail-item" style="margin-top: 4px;">
                    <span class="detail-label">Mô tả Job / Thông tin gốc</span>
                    <div class="detail-longtext" id="det-rawtype">-</div>
                </div>
            </div>
            
            <div class="preview-header">
                <div class="preview-header-left">
                    <span class="preview-header-title" id="preview-title">Xem trước HTML đã lưu</span>
                    <span class="preview-header-subtitle" id="preview-subtitle">Chọn một công việc để xem tài liệu HTML tương ứng</span>
                </div>
                <div class="preview-actions">
                    <div class="layout-toggle">
                        <button class="layout-btn active" id="layout-desktop-btn" title="Chế độ Desktop">Desktop</button>
                        <button class="layout-btn" id="layout-mobile-btn" title="Chế độ Mobile">Mobile</button>
                    </div>
                    <a href="#" target="_blank" class="btn" id="open-tab-btn" style="display: none;">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg>
                        Mở tab mới
                    </a>
                </div>
            </div>
            
            <div class="iframe-container" id="iframe-container">
                <div class="no-data" id="iframe-placeholder">
                    <span class="no-data-icon">🌐</span>
                    <h3>HTML Preview Area</h3>
                    <p>Chọn một công việc từ danh sách để tải trang HTML gốc tại thời điểm crawl.</p>
                </div>
                <iframe id="preview-iframe" style="display: none;"></iframe>
            </div>
        </div>
        
    </div>

    <script>
        // State variables
        let sessions = [];
        let currentJobs = [];
        let filteredJobs = [];
        let selectedJob = null;
        let selectedSessionId = '';

        // DOM elements
        const sessionSelect = document.getElementById('session-select');
        const searchInput = document.getElementById('search-input');
        const jobsList = document.getElementById('jobs-list');
        const jobsCount = document.getElementById('jobs-count');
        const statJobs = document.getElementById('stat-jobs');
        const statPages = document.getElementById('stat-pages');
        const metadataDetails = document.getElementById('metadata-details');
        
        // Detail panel elements
        const activeJobDetails = document.getElementById('active-job-details');
        const detCompany = document.getElementById('det-company');
        const detSalary = document.getElementById('det-salary');
        const detLocation = document.getElementById('det-location');
        const detJobtype = document.getElementById('det-jobtype');
        const detRawtype = document.getElementById('det-rawtype');
        
        // Iframe preview elements
        const previewTitle = document.getElementById('preview-title');
        const previewSubtitle = document.getElementById('preview-subtitle');
        const previewIframe = document.getElementById('preview-iframe');
        const iframePlaceholder = document.getElementById('iframe-placeholder');
        const openTabBtn = document.getElementById('open-tab-btn');
        
        // Layout buttons
        const layoutDesktopBtn = document.getElementById('layout-desktop-btn');
        const layoutMobileBtn = document.getElementById('layout-mobile-btn');

        // Initialise Dashboard
        async function init() {
            setupEventListeners();
            await loadSessions();
        }

        // Setup Event Listeners
        function setupEventListeners() {
            sessionSelect.addEventListener('change', (e) => {
                if (e.target.value) {
                    loadSession(e.target.value);
                }
            });

            searchInput.addEventListener('input', () => {
                filterJobs();
            });

            layoutDesktopBtn.addEventListener('click', () => {
                layoutDesktopBtn.classList.add('active');
                layoutMobileBtn.classList.remove('active');
                previewIframe.classList.remove('mobile-view');
            });

            layoutMobileBtn.addEventListener('click', () => {
                layoutMobileBtn.classList.add('active');
                layoutDesktopBtn.classList.remove('active');
                previewIframe.classList.add('mobile-view');
            });
        }

        // Fetch all sessions from local API
        async function loadSessions() {
            try {
                const response = await fetch('/api/sessions');
                sessions = await response.json();
                
                if (sessions.length === 0) {
                    sessionSelect.innerHTML = '<option value="">(Không tìm thấy phiên crawl nào)</option>';
                    return;
                }

                sessionSelect.innerHTML = sessions.map(s => {
                    const date = new Date(s.crawled_at);
                    const formattedDate = date.toLocaleString('vi-VN');
                    return `<option value="${s.id}">${formattedDate} — ${s.total_jobs} Jobs</option>`;
                }).join('');

                // Load first session by default
                loadSession(sessions[0].id);
            } catch (err) {
                console.error("Lỗi khi tải danh sách phiên:", err);
                sessionSelect.innerHTML = '<option value="">Lỗi kết nối server</option>';
            }
        }

        // Load specific session
        async function loadSession(sessionId) {
            selectedSessionId = sessionId;
            const session = sessions.find(s => s.id === sessionId);
            
            // Set statistics
            statJobs.innerText = session.total_jobs;
            statPages.innerText = session.pages_crawled;
            
            // Render Metadata Panel
            const proxiesHtml = session.proxies_used && session.proxies_used.length > 0 
                ? session.proxies_used.map(p => `<span class="metadata-val" style="margin-top:4px;">${p}</span>`).join('') 
                : '<span class="metadata-val">Local / Fallback</span>';
                
            metadataDetails.innerHTML = `
                <div class="metadata-item">
                    <div class="metadata-label">Mã phiên:</div>
                    <div class="metadata-val">${session.id}</div>
                </div>
                <div class="metadata-item">
                    <div class="metadata-label">Mục tiêu gốc:</div>
                    <div class="metadata-val">${session.target_url}</div>
                </div>
                <div class="metadata-item">
                    <div class="metadata-label">Thời gian crawl:</div>
                    <div class="metadata-val">${new Date(session.crawled_at).toLocaleString('vi-VN')}</div>
                </div>
                <div class="metadata-item">
                    <div class="metadata-label">Proxy đã sử dụng:</div>
                    <div style="display:flex; flex-direction:column; gap:4px;">${proxiesHtml}</div>
                </div>
            `;

            // Reset Search Box
            searchInput.value = '';
            
            // Fetch Jobs in this run
            try {
                jobsList.innerHTML = '<div class="no-data"><p>Đang tải danh sách jobs...</p></div>';
                const response = await fetch(`/api/jobs/${sessionId}`);
                currentJobs = await response.json();
                filteredJobs = [...currentJobs];
                
                // Clear active preview
                clearActivePreview();
                renderJobsList();
            } catch (err) {
                console.error("Lỗi khi tải jobs:", err);
                jobsList.innerHTML = '<div class="no-data"><p>Lỗi khi lấy dữ liệu jobs của phiên này.</p></div>';
            }
        }

        // Render Jobs to list
        function renderJobsList() {
            if (filteredJobs.length === 0) {
                jobsList.innerHTML = `
                    <div class="no-data">
                        <span class="no-data-icon">🔍</span>
                        <p>Không tìm thấy công việc nào khớp với bộ lọc.</p>
                    </div>`;
                jobsCount.innerText = "Hiển thị 0 jobs";
                return;
            }

            jobsCount.innerText = `Hiển thị ${filteredJobs.length} / ${currentJobs.length} jobs`;
            
            jobsList.innerHTML = filteredJobs.map((job, idx) => {
                const isSelected = selectedJob && selectedJob.title === job.title && selectedJob.company === job.company;
                const companyText = job.company || '(Không có thông tin cty)';
                const salaryText = job.salary || 'Lương thỏa thuận / Không công khai';
                const pageBadge = job.page ? `<span class="badge">Page ${job.page}</span>` : '';
                
                return `
                    <div class="job-card ${isSelected ? 'selected' : ''}" data-idx="${idx}">
                        <div class="job-title" title="${job.title}">${job.title}</div>
                        <div class="job-company">${companyText}</div>
                        <div class="job-meta-row">
                            <span style="color: var(--warning); font-weight: 500;">💴 ${salaryText.substring(0, 45)}${salaryText.length > 45 ? '...' : ''}</span>
                        </div>
                        <div class="job-meta-row" style="margin-top: 8px; justify-content: space-between;">
                            <span style="max-width: 60%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">📍 ${job.location || 'Nhật Bản'}</span>
                            ${pageBadge}
                        </div>
                    </div>
                `;
            }).join('');

            // Add click events to cards
            document.querySelectorAll('.job-card').forEach(card => {
                card.addEventListener('click', () => {
                    const idx = parseInt(card.getAttribute('data-idx'));
                    selectJob(filteredJobs[idx], card);
                });
            });
        }

        // Filter jobs based on search query
        function filterJobs() {
            const query = searchInput.value.toLowerCase().trim();
            if (!query) {
                filteredJobs = [...currentJobs];
            } else {
                filteredJobs = currentJobs.filter(job => {
                    return (
                        (job.title && job.title.toLowerCase().includes(query)) ||
                        (job.company && job.company.toLowerCase().includes(query)) ||
                        (job.location && job.location.toLowerCase().includes(query)) ||
                        (job.salary && job.salary.toLowerCase().includes(query)) ||
                        (job.jobType && job.jobType.toLowerCase().includes(query))
                    );
                });
            }
            renderJobsList();
        }

        // Select a job to display and preview HTML
        function selectJob(job, cardEl) {
            selectedJob = job;
            
            // Highlight selected card
            document.querySelectorAll('.job-card').forEach(c => c.classList.remove('selected'));
            cardEl.classList.add('selected');
            
            // Display Job detail grid
            activeJobDetails.style.display = 'flex';
            detCompany.innerText = job.company || 'N/A';
            detSalary.innerText = job.salary || 'Không rõ mức lương';
            detLocation.innerText = job.location || 'N/A';
            detJobtype.innerText = job.jobType ? job.jobType.split('\\n')[0] : 'N/A';
            detRawtype.innerText = job.jobType || 'N/A';
            
            // Setup HTML Iframe Preview
            if (job.page_html_path) {
                // Build server-served URL
                const fileUrl = `/output/${selectedSessionId}/${job.page_html_path}`;
                
                previewTitle.innerText = `Nguồn: ${job.title}`;
                previewSubtitle.innerText = `Crawl từ URL: ${job.page_url || '—'}`;
                
                // Show iframe, hide placeholder
                iframePlaceholder.style.display = 'none';
                previewIframe.style.display = 'block';
                previewIframe.src = fileUrl;
                
                // Enable new tab button
                openTabBtn.style.display = 'flex';
                openTabBtn.href = fileUrl;

                // Highlight content inside iframe (runs after load on same domain)
                previewIframe.onload = () => {
                    try {
                        const doc = previewIframe.contentDocument || previewIframe.contentWindow.document;
                        // Add custom CSS to iframe to highlight
                        const style = doc.createElement('style');
                        style.innerHTML = `
                            ::-webkit-scrollbar { width: 8px; height: 8px; }
                            ::-webkit-scrollbar-thumb { background: rgba(99, 102, 241, 0.4); border-radius: 4px; }
                            ::-webkit-scrollbar-thumb:hover { background: rgba(99, 102, 241, 0.8); }
                        `;
                        doc.head.appendChild(style);
                    } catch(e) {
                        console.warn("Không thể tuỳ biến CSS iframe (CORS hoặc tài liệu chưa sẵn sàng):", e);
                    }
                };
            } else {
                // No html file saved
                previewTitle.innerText = `Nguồn: ${job.title}`;
                previewSubtitle.innerText = `Crawl từ URL: ${job.page_url || '—'}`;
                
                previewIframe.style.display = 'none';
                iframePlaceholder.style.display = 'flex';
                iframePlaceholder.innerHTML = `
                    <span class="no-data-icon">⚠️</span>
                    <h3>Không tìm thấy file HTML xem trước</h3>
                    <p>Phiên crawl này được thực hiện trước khi tính năng lưu HTML được kích hoạt.</p>
                    ${job.link ? `<a href="${job.link}" target="_blank" class="btn btn-primary" style="margin-top:14px;">Truy cập Link gốc</a>` : ''}
                `;
                openTabBtn.style.display = 'none';
            }
        }

        // Clear active preview layout
        function clearActivePreview() {
            selectedJob = null;
            activeJobDetails.style.display = 'none';
            previewTitle.innerText = 'Xem trước HTML đã lưu';
            previewSubtitle.innerText = 'Chọn một công việc để xem tài liệu HTML tương ứng';
            previewIframe.style.display = 'none';
            previewIframe.src = '';
            iframePlaceholder.style.display = 'flex';
            iframePlaceholder.innerHTML = `
                <span class="no-data-icon">🌐</span>
                <h3>HTML Preview Area</h3>
                <p>Chọn một công việc từ danh sách để tải trang HTML gốc tại thời điểm crawl.</p>
            `;
            openTabBtn.style.display = 'none';
        }

        // Start SPA on load
        window.addEventListener('DOMContentLoaded', init);
    </script>
</body>
</html>
"""

# Custom HTTP Server Handler to serve APIs and output folder files
class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        parsed = urllib.parse.urlparse(path)
        path_str = parsed.path
        
        # Mapping /output/ to output directory (prevent directory traversal)
        if path_str.startswith("/output/"):
            rel = path_str[len("/output/"):]
            resolved = (OUTPUT_DIR / rel).resolve()
            if OUTPUT_DIR in resolved.parents or resolved == OUTPUT_DIR:
                return str(resolved)
                
        return super().translate_path(path)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        
        # Serve SPA Index Page
        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_UI.encode("utf-8"))
            return
            
        # API: List all crawl runs (sessions)
        if path == "/api/sessions":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            
            sessions = []
            if OUTPUT_DIR.exists():
                for item in OUTPUT_DIR.iterdir():
                    if item.is_dir() and item.name.startswith("run_"):
                        meta_file = item / "metadata.json"
                        meta = {}
                        if meta_file.exists():
                            try:
                                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                            except Exception:
                                pass
                        
                        # Fallback info if metadata doesn't exist
                        if not meta:
                            jobs_file = item / "jobs.json"
                            total_jobs = 0
                            if jobs_file.exists():
                                try:
                                    jobs = json.loads(jobs_file.read_text(encoding="utf-8"))
                                    total_jobs = len(jobs)
                                except Exception:
                                    pass
                            
                            html_dir = item / "html"
                            pages_crawled = len(list(html_dir.glob("*.html"))) if html_dir.exists() else 0
                            
                            meta = {
                                "timestamp": item.name.replace("run_", ""),
                                "crawled_at": datetime.fromtimestamp(item.stat().st_mtime).isoformat(),
                                "total_jobs": total_jobs,
                                "pages_crawled": pages_crawled,
                                "proxies_used": [],
                                "target_url": "https://www.ekaigotenshoku.com/kyujin/list?z01=1"
                            }
                        
                        meta["id"] = item.name
                        sessions.append(meta)
            
            # Sort runs by date/time desc (newest first)
            sessions.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            self.wfile.write(json.dumps(sessions, ensure_ascii=False, indent=2).encode("utf-8"))
            return
            
        # API: Get job list of a session
        if path.startswith("/api/jobs/"):
            session_id = path[len("/api/jobs/"):]
            session_dir = OUTPUT_DIR / session_id
            jobs_file = session_dir / "jobs.json"
            
            if jobs_file.exists():
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(jobs_file.read_bytes())
            else:
                self.send_response(404)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Không tìm thấy session: {session_id}"}).encode("utf-8"))
            return
            
        # Serve static assets in /output/ folder (HTML pages, JSON files, etc.)
        if path.startswith("/output/"):
            super().do_GET()
            return
            
        # 404 handler fallback
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not Found")

def open_browser(port):
    time.sleep(1.2)
    url = f"http://localhost:{port}"
    print(f"\n👉 Tự động mở trình duyệt xem Dashboard: {url}")
    webbrowser.open(url)

def main():
    # Allow custom port from CLI args
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"⚠ Cảnh báo: Cổng truyền vào không hợp lệ. Sử dụng cổng mặc định {DEFAULT_PORT}.")
            
    server_address = ('', port)
    
    # Enable socket reuse
    socketserver.TCPServer.allow_reuse_address = True
    
    try:
        with socketserver.TCPServer(server_address, DashboardHandler) as httpd:
            print(f"\n{'═'*60}")
            print(f"🚀 Ekaigo Scraper Dashboard Server đang chạy tại:")
            print(f"   http://localhost:{port}")
            print(f"   (Bấm Ctrl+C để dừng server)")
            print(f"{'═'*60}")
            
            # Start background thread to launch browser
            threading.Thread(target=open_browser, args=(port,), daemon=True).start()
            
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Đã tắt dashboard server.")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Lỗi khi khởi động server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
