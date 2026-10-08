// ==========================================================================
// FCC URL Shortener Frontend Application Logic
// ==========================================================================

let state = {
    currentDomain: 'all',
    searchQuery: '',
    sortOrder: 'latest',
    links: [],
    activeTab: 'links',
    activeAnalyticsLinkId: null,
    analyticsPeriod: '30d',
    chartInstance: null
};

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initDomainSwitcher();
    loadLinks();
    if (window.CURRENT_USER && window.CURRENT_USER.is_admin) {
        loadTeamUsers();
    }
});

// --------------------------------------------------------------------------
// Theme (Light / Dark)
// --------------------------------------------------------------------------
function initTheme() {
    const saved = localStorage.getItem('fcc_theme');
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = saved || (prefersDark ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);
    updateThemeIcon(theme);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'light';
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('fcc_theme', next);
    updateThemeIcon(next);
}

function updateThemeIcon(theme) {
    const icon = document.getElementById('themeIcon');
    if (!icon) return;
    if (theme === 'dark') {
        // Sun icon
        icon.innerHTML = `<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>`;
    } else {
        // Moon icon
        icon.innerHTML = `<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>`;
    }
}

// --------------------------------------------------------------------------
// Mobile Drawer
// --------------------------------------------------------------------------
function toggleMobileDrawer() {
    const drawer = document.getElementById('mobileDrawer');
    if (drawer) {
        drawer.classList.toggle('open');
    }
}

function closeMobileDrawerOnBackdrop(e) {
    if (e.target.id === 'mobileDrawer') {
        toggleMobileDrawer();
    }
}

// --------------------------------------------------------------------------
// Domain Switcher
// --------------------------------------------------------------------------
function initDomainSwitcher() {
    const allowed = (window.CURRENT_USER && window.CURRENT_USER.allowed_domains) || ['fcc.li', 'amp.ad'];
    const desktopEl = document.getElementById('domainSwitcherDesktop');
    const mobileEl = document.getElementById('domainSwitcherMobile');
    const formSelect = document.getElementById('linkFormDomain');

    // Build pill buttons
    let pillsHtml = '';
    if (allowed.length > 1 || window.CURRENT_USER.is_superadmin) {
        pillsHtml += `<button class="domain-pill active" data-domain="all" onclick="selectDomain('all')">All Domains</button>`;
    }

    allowed.forEach((dom, index) => {
        const isFirst = (allowed.length === 1 && index === 0);
        const activeClass = isFirst ? 'active' : '';
        pillsHtml += `<button class="domain-pill ${activeClass}" data-domain="${dom}" onclick="selectDomain('${dom}')">${dom}</button>`;
    });

    if (desktopEl) desktopEl.innerHTML = pillsHtml;
    if (mobileEl) mobileEl.innerHTML = pillsHtml;

    // Default selection
    if (allowed.length === 1) {
        state.currentDomain = allowed[0];
    } else {
        state.currentDomain = 'all';
    }

    // Populate create modal domain dropdown
    if (formSelect) {
        formSelect.innerHTML = allowed.map(d => `<option value="${d}">${d}</option>`).join('');
        formSelect.addEventListener('change', () => {
            const prefix = document.getElementById('slugPrefixDomain');
            if (prefix) prefix.textContent = `${formSelect.value}/`;
        });
    }
}

function selectDomain(dom) {
    state.currentDomain = dom;
    document.querySelectorAll('.domain-pill').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-domain') === dom);
    });
    loadLinks();
}

// --------------------------------------------------------------------------
// Navigation Tabs
// --------------------------------------------------------------------------
function switchMainTab(tab) {
    state.activeTab = tab;
    document.querySelectorAll('.nav-tab').forEach(el => {
        el.classList.toggle('active', el.getAttribute('data-tab') === tab);
    });

    const secLinks = document.getElementById('tabContentLinks');
    const secAnalytics = document.getElementById('tabContentAnalytics');
    const secTeam = document.getElementById('tabContentTeam');

    if (secLinks) secLinks.style.display = tab === 'links' ? 'block' : 'none';
    if (secAnalytics) {
        secAnalytics.style.display = tab === 'analytics' ? 'block' : 'none';
        if (tab === 'analytics') loadOverviewAnalytics();
    }
    if (secTeam) {
        secTeam.style.display = tab === 'team' ? 'block' : 'none';
        if (tab === 'team') loadTeamUsers();
    }
}

// --------------------------------------------------------------------------
// Links Management
// --------------------------------------------------------------------------
async function loadLinks() {
    const subtitle = document.getElementById('linksCountSubtitle');
    if (subtitle) subtitle.textContent = 'Loading links...';

    try {
        let url = `/api/links?domain=${encodeURIComponent(state.currentDomain)}`;
        if (state.searchQuery) {
            url += `&q=${encodeURIComponent(state.searchQuery)}`;
        }
        const res = await fetch(url);
        if (!res.ok) throw new Error('Failed to fetch links');
        state.links = await res.json();
        renderLinksList();
    } catch (err) {
        console.error(err);
        const tbody = document.getElementById('linksTableBody');
        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; padding: 30px; color: var(--color-text-muted);">Failed to load links. Please try again.</td></tr>`;
        }
    }
}

function handleSearchInput() {
    const input = document.getElementById('searchInput');
    state.searchQuery = input ? input.value.trim() : '';
    loadLinks();
}

function renderLinksList() {
    const tbody = document.getElementById('linksTableBody');
    const subtitle = document.getElementById('linksCountSubtitle');
    if (!tbody) return;

    let displayLinks = [...state.links];
    const sort = document.getElementById('sortSelect')?.value || 'latest';
    if (sort === 'clicks') {
        displayLinks.sort((a, b) => b.total_clicks - a.total_clicks);
    } else if (sort === 'slug') {
        displayLinks.sort((a, b) => a.slug.localeCompare(b.slug));
    } else {
        displayLinks.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    }

    if (subtitle) {
        const count = displayLinks.length;
        subtitle.textContent = `${count} branded link${count === 1 ? '' : 's'} active`;
    }

    if (displayLinks.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="4" style="text-align: center; padding: 48px 20px; color: var(--color-text-muted);">
                    <img src="/static/brand/fcc-dove-light.svg" style="width: 48px; height: 48px; opacity: 0.4; margin-bottom: 12px;" alt="">
                    <div style="font-weight: 700; font-size: 16px; margin-bottom: 4px;">No short links found</div>
                    <div style="font-size: 13px;">Create a new link or import existing links from Rebrandly</div>
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = displayLinks.map(link => {
        const createdDate = new Date(link.created_at).toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric'
        });
        const faviconUrl = `https://www.google.com/s2/favicons?domain=${new URL(link.destination_url).hostname}&sz=32`;

        return `
            <tr>
                <td>
                    <div class="link-title-cell">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <img src="${faviconUrl}" alt="" style="width: 16px; height: 16px; border-radius: 2px;" onerror="this.style.display='none'">
                            <span class="short-url-link">${link.domain}/${link.slug}</span>
                            <button class="btn btn-ghost btn-sm" style="padding: 2px 6px;" onclick="copyShortUrl('${link.short_url}')" title="Copy to clipboard">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                            </button>
                        </div>
                        <div style="font-size: 14px; font-weight: 600; color: var(--color-text-heading); margin-top: 2px;">
                            ${escapeHtml(link.title || link.slug)}
                        </div>
                        <div class="destination-preview" title="${escapeHtml(link.destination_url)}">
                            <a href="${escapeHtml(link.destination_url)}" target="_blank" rel="noopener" style="color: var(--color-text-muted);">
                                ${escapeHtml(link.destination_url)}
                            </a>
                        </div>
                        <div class="mobile-actions-row" style="margin-top: 8px;">
                            <button class="btn btn-secondary btn-sm" onclick="openQrModal(${link.id}, '${link.domain}', '${link.slug}')">QR Code</button>
                            <button class="btn btn-secondary btn-sm" onclick="openAnalyticsModal(${link.id})">Stats</button>
                            <button class="btn btn-ghost btn-sm" onclick="openEditModal(${link.id})">Edit</button>
                            <button class="btn btn-ghost btn-sm" style="color: #B42318;" onclick="deleteLink(${link.id}, '${link.slug}')">Delete</button>
                        </div>
                    </div>
                </td>
                <td>
                    <span class="click-badge">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                        ${link.total_clicks}
                    </span>
                </td>
                <td style="color: var(--color-text-muted); font-size: 13px; white-space: nowrap;">
                    ${createdDate}
                </td>
                <td style="text-align: right; white-space: nowrap;">
                    <button class="btn btn-secondary btn-sm" onclick="openQrModal(${link.id}, '${link.domain}', '${link.slug}')" title="View & Download QR Code">
                        QR
                    </button>
                    <button class="btn btn-secondary btn-sm" onclick="openAnalyticsModal(${link.id})" title="Click Analytics">
                        Stats
                    </button>
                    <button class="btn btn-ghost btn-sm" onclick="openEditModal(${link.id})" title="Edit link">
                        Edit
                    </button>
                    <button class="btn btn-ghost btn-sm" style="color: #B42318;" onclick="deleteLink(${link.id}, '${link.slug}')" title="Delete link">
                        &times;
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

// --------------------------------------------------------------------------
// Create / Edit Link Modal
// --------------------------------------------------------------------------
function openCreateModal() {
    const modal = document.getElementById('linkModal');
    const title = document.getElementById('linkModalTitle');
    const form = document.getElementById('linkForm');
    if (!modal || !form) return;

    form.reset();
    document.getElementById('linkFormId').value = '';
    title.textContent = 'Create Branded Link';
    document.getElementById('linkFormSubmitBtn').textContent = 'Create Link';

    const domSelect = document.getElementById('linkFormDomain');
    if (domSelect) {
        if (state.currentDomain !== 'all') {
            domSelect.value = state.currentDomain;
        }
        document.getElementById('slugPrefixDomain').textContent = `${domSelect.value}/`;
    }
    document.getElementById('scrapeStatusText').textContent = '';
    modal.classList.add('open');
}

function openEditModal(linkId) {
    const link = state.links.find(l => l.id === linkId);
    if (!link) return;

    const modal = document.getElementById('linkModal');
    document.getElementById('linkModalTitle').textContent = `Edit Link: ${link.domain}/${link.slug}`;
    document.getElementById('linkFormId').value = link.id;
    document.getElementById('linkFormDomain').value = link.domain;
    document.getElementById('slugPrefixDomain').textContent = `${link.domain}/`;
    document.getElementById('linkFormSlug').value = link.slug;
    document.getElementById('linkFormDestination').value = link.destination_url;
    document.getElementById('linkFormTitle').value = link.title || '';
    document.getElementById('linkFormNotes').value = link.notes || '';
    document.getElementById('linkFormSubmitBtn').textContent = 'Save Changes';
    document.getElementById('scrapeStatusText').textContent = '';

    modal.classList.add('open');
}

function closeLinkModal() {
    const modal = document.getElementById('linkModal');
    if (modal) modal.classList.remove('open');
}

async function handleDestinationBlur() {
    const destInput = document.getElementById('linkFormDestination');
    const titleInput = document.getElementById('linkFormTitle');
    const statusText = document.getElementById('scrapeStatusText');
    const val = destInput.value.trim();

    if (!val || titleInput.value.trim()) return;

    try {
        statusText.textContent = 'Fetching page title...';
        const res = await fetch(`/api/links/preview-metadata?url=${encodeURIComponent(val)}`, { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            if (data.title && !titleInput.value.trim()) {
                titleInput.value = data.title;
                statusText.textContent = 'Title auto-filled!';
                setTimeout(() => { statusText.textContent = ''; }, 3000);
            } else {
                statusText.textContent = '';
            }
        }
    } catch {
        statusText.textContent = '';
    }
}

function generateSlugClick() {
    const alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789';
    let res = '';
    for (let i = 0; i < 6; i++) {
        res += alphabet[Math.floor(Math.random() * alphabet.length)];
    }
    document.getElementById('linkFormSlug').value = res;
}

async function handleLinkSubmit(e) {
    e.preventDefault();
    const linkId = document.getElementById('linkFormId').value;
    const domain = document.getElementById('linkFormDomain').value;
    const destination = document.getElementById('linkFormDestination').value.trim();
    const slug = document.getElementById('linkFormSlug').value.trim();
    const title = document.getElementById('linkFormTitle').value.trim();
    const notes = document.getElementById('linkFormNotes').value.trim();

    const submitBtn = document.getElementById('linkFormSubmitBtn');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Saving...';

    try {
        if (linkId) {
            // Edit
            const res = await fetch(`/api/links/${linkId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    destination_url: destination,
                    title: title,
                    notes: notes
                })
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Failed to update link');
            }
            showToast('Link updated successfully');
        } else {
            // Create
            const res = await fetch('/api/links', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    domain: domain,
                    destination_url: destination,
                    slug: slug,
                    title: title,
                    notes: notes
                })
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Failed to create link');
            }
            showToast('Branded link created');
        }
        closeLinkModal();
        loadLinks();
    } catch (err) {
        alert(err.message);
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Save Link';
    }
}

async function deleteLink(linkId, slug) {
    if (!confirm(`Are you sure you want to delete the short link /${slug}?`)) return;

    try {
        const res = await fetch(`/api/links/${linkId}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Failed to delete link');
        showToast(`Link /${slug} deleted`);
        loadLinks();
    } catch (err) {
        alert(err.message);
    }
}

// --------------------------------------------------------------------------
// QR Code Modal
// --------------------------------------------------------------------------
let currentQrUrl = '';

function openQrModal(linkId, domain, slug) {
    const modal = document.getElementById('qrModal');
    currentQrUrl = `https://${domain}/${slug}`;

    document.getElementById('qrModalTitle').textContent = `QR Code: ${domain}/${slug}`;
    document.getElementById('qrModalUrlText').textContent = currentQrUrl;

    const img = document.getElementById('qrModalImg');
    img.src = `/api/links/${linkId}/qr.png`;

    const pngBtn = document.getElementById('qrDownloadPngBtn');
    pngBtn.href = `/api/links/${linkId}/qr.png`;
    pngBtn.setAttribute('download', `${slug}-qr.png`);

    const svgBtn = document.getElementById('qrDownloadSvgBtn');
    svgBtn.href = `/api/links/${linkId}/qr.svg`;
    svgBtn.setAttribute('download', `${slug}-qr.svg`);

    modal.classList.add('open');
}

function closeQrModal() {
    const modal = document.getElementById('qrModal');
    if (modal) modal.classList.remove('open');
}

function copyCurrentQrUrl() {
    copyShortUrl(currentQrUrl);
}

// --------------------------------------------------------------------------
// Analytics Modal
// --------------------------------------------------------------------------
async function openAnalyticsModal(linkId) {
    state.activeAnalyticsLinkId = linkId;
    const modal = document.getElementById('analyticsModal');
    modal.classList.add('open');
    loadLinkAnalyticsData();
}

function closeAnalyticsModal() {
    const modal = document.getElementById('analyticsModal');
    if (modal) modal.classList.remove('open');
    if (state.chartInstance) {
        state.chartInstance.destroy();
        state.chartInstance = null;
    }
}

function switchAnalyticsPeriod(period) {
    state.analyticsPeriod = period;
    document.getElementById('btnPeriod30d').classList.toggle('active', period === '30d');
    document.getElementById('btnPeriod12m').classList.toggle('active', period === '12m');
    loadLinkAnalyticsData();
}

async function loadLinkAnalyticsData() {
    if (!state.activeAnalyticsLinkId) return;

    try {
        const res = await fetch(`/api/analytics/link/${state.activeAnalyticsLinkId}?period=${state.analyticsPeriod}`);
        if (!res.ok) throw new Error('Failed to load analytics');
        const data = await res.json();

        document.getElementById('analyticsModalTitle').textContent = `Performance: /${data.short_link.slug}`;
        document.getElementById('analyticsModalUrl').textContent = data.short_link.destination_url;

        document.getElementById('statModalTotal').textContent = data.total_clicks;
        document.getElementById('statModalQr').textContent = data.qr_scans;
        document.getElementById('statModalDirect').textContent = data.direct_clicks;
        document.getElementById('statModalToday').textContent = data.clicks_today;

        // Render Chart
        renderAnalyticsChart(data.chart.labels, data.chart.clicks, data.chart.qr_scans);

        // Render Devices
        const devEl = document.getElementById('deviceBreakdownList');
        if (devEl) {
            const devEntries = Object.entries(data.devices || {});
            if (devEntries.length === 0) {
                devEl.textContent = 'No device data yet';
            } else {
                devEl.innerHTML = devEntries.map(([dev, cnt]) => `
                    <div style="display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid var(--color-border);">
                        <span style="text-transform: capitalize;">${dev}</span>
                        <strong>${cnt}</strong>
                    </div>
                `).join('');
            }
        }

        // Render Referrers
        const refEl = document.getElementById('referrerBreakdownList');
        if (refEl) {
            const referrers = data.top_referrers || [];
            if (referrers.length === 0) {
                refEl.textContent = 'Direct / No Referrer data';
            } else {
                refEl.innerHTML = referrers.map(r => `
                    <div style="display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid var(--color-border);">
                        <span style="overflow: hidden; text-overflow: ellipsis; max-width: 180px;">${r.referrer}</span>
                        <strong>${r.clicks}</strong>
                    </div>
                `).join('');
            }
        }
    } catch (err) {
        console.error(err);
    }
}

function renderAnalyticsChart(labels, clicks, qrScans) {
    const canvas = document.getElementById('analyticsChartCanvas');
    if (!canvas) return;

    if (state.chartInstance) {
        state.chartInstance.destroy();
    }

    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const textColor = isDark ? '#9AA1A7' : '#5B6168';
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.06)';

    state.chartInstance = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Direct Clicks',
                    data: clicks,
                    backgroundColor: '#1C7678', // FCC brand teal
                    borderRadius: 3,
                },
                {
                    label: 'QR Scans',
                    data: qrScans,
                    backgroundColor: '#F8DC29', // FCC dove gold
                    borderRadius: 3,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: textColor, font: { family: 'Mulish', weight: '700' } }
                }
            },
            scales: {
                x: {
                    grid: { color: gridColor },
                    ticks: { color: textColor, font: { family: 'Mulish' } }
                },
                y: {
                    beginAtZero: true,
                    grid: { color: gridColor },
                    ticks: { color: textColor, font: { family: 'Mulish' }, precision: 0 }
                }
            }
        }
    });
}

// --------------------------------------------------------------------------
// Overview Analytics Tab
// --------------------------------------------------------------------------
async function loadOverviewAnalytics() {
    try {
        const res = await fetch('/api/analytics/overview');
        if (!res.ok) return;
        const data = await res.json();

        const grid = document.getElementById('analyticsOverviewStats');
        if (grid) {
            grid.innerHTML = `
                <div class="stat-card">
                    <div class="stat-label">Active Links</div>
                    <div class="stat-num">${data.total_links}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total Clicks Recorded</div>
                    <div class="stat-num">${data.total_clicks}</div>
                </div>
            `;
        }

        const topEl = document.getElementById('topLinksList');
        if (topEl) {
            if (data.top_links.length === 0) {
                topEl.textContent = 'No links created yet.';
            } else {
                topEl.innerHTML = data.top_links.map(l => `
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--color-border);">
                        <div>
                            <span class="short-url-link">${l.domain}/${l.slug}</span>
                            <div style="font-size: 13px; color: var(--color-text-muted);">${escapeHtml(l.title || l.destination_url)}</div>
                        </div>
                        <span class="click-badge">${l.total_clicks} clicks</span>
                    </div>
                `).join('');
            }
        }
    } catch (err) {
        console.error(err);
    }
}

// --------------------------------------------------------------------------
// Rebrandly CSV Import
// --------------------------------------------------------------------------
function openImportModal() {
    const modal = document.getElementById('importModal');
    document.getElementById('importResultAlert').style.display = 'none';
    if (modal) modal.classList.add('open');
}

function closeImportModal() {
    const modal = document.getElementById('importModal');
    if (modal) modal.classList.remove('open');
}

async function handleImportSubmit(e) {
    e.preventDefault();
    const fileInput = document.getElementById('importCsvFileInput');
    if (!fileInput.files.length) return;

    const btn = document.getElementById('importSubmitBtn');
    const alertBox = document.getElementById('importResultAlert');
    btn.disabled = true;
    btn.textContent = 'Importing...';

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    try {
        const res = await fetch('/api/links/import-rebrandly-csv', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Import failed');

        alertBox.style.display = 'block';
        alertBox.style.background = '#ECFDF3';
        alertBox.style.color = '#027A48';
        alertBox.innerHTML = `<strong>Import Complete!</strong><br>Successfully imported ${data.imported} links (${data.skipped} skipped or duplicates).`;
        loadLinks();
    } catch (err) {
        alertBox.style.display = 'block';
        alertBox.style.background = '#FEE4E2';
        alertBox.style.color = '#B42318';
        alertBox.textContent = err.message;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Import Links';
    }
}

// --------------------------------------------------------------------------
// Team & User Management (Admin Only)
// --------------------------------------------------------------------------
async function loadTeamUsers() {
    const tbody = document.getElementById('teamTableBody');
    if (!tbody) return;

    try {
        const res = await fetch('/api/admin/users');
        if (!res.ok) return;
        const users = await res.json();

        tbody.innerHTML = users.map(u => {
            const isSuper = u.is_default_superadmin;
            const statusBadge = u.status === 'approved' 
                ? '<span style="color: #027A48; font-weight: 700;">Approved</span>' 
                : (u.status === 'pending' ? '<span style="color: #B25E09; font-weight: 800; background: #FEFBE8; padding: 2px 6px; border-radius: 4px;">Pending</span>' : '<span style="color: #B42318;">Revoked</span>');

            const domainList = u.allowed_domains.join(', ') || 'None';

            return `
                <tr>
                    <td>
                        <div style="font-weight: 700; color: var(--color-text-heading);">${escapeHtml(u.name || u.email)}</div>
                        <div style="font-size: 13px; color: var(--color-text-muted);">${escapeHtml(u.email)}</div>
                    </td>
                    <td>
                        <span style="font-weight: 700; font-size: 13px; text-transform: uppercase;">${u.role}</span>
                        ${isSuper ? '<span style="font-size: 11px; background: var(--teal-100); color: var(--teal-800); padding: 1px 6px; border-radius: 4px; margin-left: 4px;">Superadmin</span>' : ''}
                    </td>
                    <td>${statusBadge}</td>
                    <td style="font-size: 13px;">${escapeHtml(domainList)}</td>
                    <td style="text-align: right;">
                        ${u.status === 'pending' ? `
                            <button class="btn btn-primary btn-sm" onclick="approveUser(${u.id}, '${escapeHtml(u.email)}')">Approve</button>
                        ` : ''}
                        ${!isSuper ? `
                            <button class="btn btn-secondary btn-sm" onclick="editUserDomains(${u.id}, '${escapeHtml(u.email)}')">Domains</button>
                            <button class="btn btn-ghost btn-sm" style="color: #B42318;" onclick="deleteUser(${u.id}, '${escapeHtml(u.email)}')">&times;</button>
                        ` : ''}
                    </td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        console.error(err);
    }
}

async function approveUser(userId, email) {
    const role = confirm(`Approve ${email} as Administrator? (Click Cancel for Regular User)`) ? 'admin' : 'user';
    const allowed = prompt(`Comma-separated allowed domains for ${email}:`, 'fcc.li,amp.ad');
    if (allowed === null) return;

    const domainList = allowed.split(',').map(s => s.trim()).filter(Boolean);
    try {
        const res = await fetch(`/api/admin/users/${userId}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                role: role,
                allowed_domains: domainList
            })
        });
        if (!res.ok) throw new Error('Failed to approve user');
        showToast(`User ${email} approved`);
        loadTeamUsers();
    } catch (err) {
        alert(err.message);
    }
}

async function editUserDomains(userId, email) {
    const domains = prompt(`Allowed domains for ${email} (comma-separated, e.g. fcc.li,amp.ad):`);
    if (domains === null) return;

    const domainList = domains.split(',').map(s => s.trim()).filter(Boolean);
    try {
        const res = await fetch(`/api/admin/users/${userId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ allowed_domains: domainList })
        });
        if (!res.ok) throw new Error('Failed to update domains');
        showToast('Domains updated');
        loadTeamUsers();
    } catch (err) {
        alert(err.message);
    }
}

async function deleteUser(userId, email) {
    if (!confirm(`Delete user ${email}?`)) return;
    try {
        const res = await fetch(`/api/admin/users/${userId}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Failed to delete user');
        showToast(`User ${email} deleted`);
        loadTeamUsers();
    } catch (err) {
        alert(err.message);
    }
}

// --------------------------------------------------------------------------
// Utilities
// --------------------------------------------------------------------------
function copyShortUrl(url) {
    navigator.clipboard.writeText(url).then(() => {
        showToast(`Copied ${url}`);
    }).catch(() => {
        prompt('Copy short URL:', url);
    });
}

function showToast(msg) {
    const toast = document.getElementById('toastNotification');
    const msgEl = document.getElementById('toastMessage');
    if (!toast || !msgEl) return;
    msgEl.textContent = msg;
    toast.style.display = 'flex';
    setTimeout(() => {
        toast.style.display = 'none';
    }, 2800);
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function toggleUtmBuilder() {
    const el = document.getElementById('utmBuilderFields');
    if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

function applyUtmToDestination() {
    const destInput = document.getElementById('linkFormDestination');
    const source = document.getElementById('utmSource').value.trim();
    const medium = document.getElementById('utmMedium').value.trim();
    const campaign = document.getElementById('utmCampaign').value.trim();

    if (!destInput.value.trim()) return;

    try {
        const url = new URL(destInput.value.trim());
        if (source) url.searchParams.set('utm_source', source);
        if (medium) url.searchParams.set('utm_medium', medium);
        if (campaign) url.searchParams.set('utm_campaign', campaign);
        destInput.value = url.toString();
        showToast('UTM parameters applied');
    } catch (e) {
        alert('Please enter a valid Destination URL first');
    }
}
