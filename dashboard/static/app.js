let currentProjectId = null;
let eventSource = null;

function formatDuration(sec) {
    if (sec < 60) return `${sec}s`;
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    if (m < 60) return `${m}m ${s}s`;
    const h = Math.floor(m / 60);
    const rm = m % 60;
    return `${h}h ${rm}m`;
}
let currentTreeNodes = [];
let selectedNodeId = null;
let lastProjectsSig = null;
let sidebarLayout = 'list';

function setSidebarLayout(layout) {
    sidebarLayout = layout;
    const btnList = document.getElementById('btn-view-list');
    const btnGrid = document.getElementById('btn-view-grid');
    if (!btnList || !btnGrid) return;
    if (layout === 'grid') {
        btnGrid.className = "px-2.5 py-1 bg-blue-600 text-white rounded-r text-xs font-semibold focus:outline-none transition";
        btnList.className = "px-2.5 py-1 bg-gray-700 hover:bg-gray-650 text-gray-300 rounded-l text-xs font-semibold focus:outline-none transition";
    } else {
        btnList.className = "px-2.5 py-1 bg-blue-600 text-white rounded-l text-xs font-semibold focus:outline-none transition";
        btnGrid.className = "px-2.5 py-1 bg-gray-700 hover:bg-gray-650 text-gray-300 rounded-r text-xs font-semibold focus:outline-none transition";
    }
    lastProjectsSig = null;
    fetchProjects();
}
let currentLogType = 'loop';
const MAX_LOG_LINES = 2000;

let prevStatusById = {};
let notificationsEnabled = localStorage.getItem('loop_notify') === 'true';

function initNotifications() {
    const btn = document.getElementById('btn-notification-toggle');
    if (!btn) return;
    if (Notification.permission === 'denied') {
        btn.style.display = 'none';
        return;
    }
    if (Notification.permission === 'granted') {
        if (localStorage.getItem('loop_notify') === null) {
            localStorage.setItem('loop_notify', 'true');
            notificationsEnabled = true;
        }
    }
    updateNotificationButton();
}

function updateNotificationButton() {
    const btn = document.getElementById('btn-notification-toggle');
    const icon = document.getElementById('notification-icon');
    const text = document.getElementById('notification-text');
    if (!btn) return;
    if (Notification.permission === 'granted' && notificationsEnabled) {
        icon.innerText = '🔕';
        text.innerText = 'Disable notifications';
        btn.className = "px-3 py-1 bg-gray-700 hover:bg-gray-650 text-gray-300 rounded text-xs font-semibold flex items-center gap-1.5 transition";
    } else {
        icon.innerText = '🔔';
        text.innerText = 'Enable notifications';
        btn.className = "px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-semibold flex items-center gap-1.5 transition";
    }
}

async function toggleNotifications() {
    if (Notification.permission === 'default') {
        const permission = await Notification.requestPermission();
        if (permission === 'granted') {
            localStorage.setItem('loop_notify', 'true');
            notificationsEnabled = true;
        } else {
            localStorage.setItem('loop_notify', 'false');
            notificationsEnabled = false;
        }
    } else if (Notification.permission === 'granted') {
        notificationsEnabled = !notificationsEnabled;
        localStorage.setItem('loop_notify', notificationsEnabled ? 'true' : 'false');
    }
    updateNotificationButton();
}

function checkStatusTransitions(projects) {
    const isFirstLoad = Object.keys(prevStatusById).length === 0;

    projects.forEach(p => {
        const id = p.id;
        const current = {
            status: p.status,
            is_running: p.is_running,
            stuck: parseInt(p.stuck) || 0,
            repo_name: p.repo_name,
            workspace: p.workspace,
            p_obj: p
        };

        if (!isFirstLoad && prevStatusById[id]) {
            const prev = prevStatusById[id];
            let triggerNotify = false;
            let title = '';
            let body = '';

            if (current.status === 'human_required' && prev.status !== 'human_required') {
                triggerNotify = true;
                title = `⚠️ Action Needed: ${current.repo_name}/${current.workspace}`;
                body = `Project requires human intervention.`;
            }
            else if ((current.status === 'complete' || current.status === 'done') &&
                (prev.status !== 'complete' && prev.status !== 'done')) {
                triggerNotify = true;
                title = `✅ Complete: ${current.repo_name}/${current.workspace}`;
                body = `Project has finished execution successfully.`;
            }
            else if (prev.is_running && !current.is_running && current.status !== 'complete' && current.status !== 'done') {
                triggerNotify = true;
                title = `🛑 Stopped: ${current.repo_name}/${current.workspace}`;
                body = `Execution stopped (possible failure or cancelled).`;
            }
            else if (current.stuck > prev.stuck) {
                triggerNotify = true;
                title = `⚡ Stuck Level Up: ${current.repo_name}/${current.workspace}`;
                body = `Stuck level increased from ${prev.stuck} to ${current.stuck}.`;
            }

            if (triggerNotify && notificationsEnabled && Notification.permission === 'granted') {
                try {
                    const n = new Notification(title, {
                        body: body
                    });
                    n.onclick = () => {
                        window.focus();
                        selectProject(current.p_obj);
                    };
                } catch (err) {
                    console.error("Failed to fire desktop notification:", err);
                }
            }
        }
        prevStatusById[id] = current;
    });
}

function showInitModal() {
    document.getElementById('init-modal').style.display = 'flex';
}

function hideInitModal() {
    document.getElementById('init-modal').style.display = 'none';
}

async function submitInit() {
    const repo = document.getElementById('init-repo').value;
    const ws = document.getElementById('init-ws').value || 'default';
    if (!repo) return alert("Repository path is required");

    const res = await fetch('/api/projects/init', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_path: repo, workspace_name: ws })
    });

    if (res.ok) {
        hideInitModal();
        fetchProjects();
        alert(`Workspace ${ws} initialized in ${repo}!`);
    } else {
        const err = await res.json();
        alert("Failed to initialize: " + err.detail);
    }
}

function showTrackModal() {
    document.getElementById('track-modal').style.display = 'flex';
}

function hideTrackModal() {
    document.getElementById('track-modal').style.display = 'none';
}

async function submitTrack() {
    const repo = document.getElementById('track-repo').value;
    const ws = document.getElementById('track-ws').value || 'default';
    if (!repo) return alert("Repository path is required");

    const res = await fetch('/api/projects/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_path: repo, workspace_name: ws })
    });

    if (res.ok) {
        hideTrackModal();
        fetchProjects();
        alert(`Workspace ${ws} in ${repo} successfully added to dashboard tracking!`);
    } else {
        const err = await res.json();
        alert("Failed to track workspace: " + err.detail);
    }
}

function showParallelModal() {
    document.getElementById('parallel-modal').style.display = 'flex';
    const currentPath = document.getElementById('ws-path')?.innerText;
    if (currentPath && currentPath !== '/path/to/repo') {
        document.getElementById('parallel-repo').value = currentPath;
    }
}

function hideParallelModal() {
    document.getElementById('parallel-modal').style.display = 'none';
}

async function submitParallel() {
    const repo = document.getElementById('parallel-repo').value.trim();
    const branch = document.getElementById('parallel-branch').value.trim();
    const ws = document.getElementById('parallel-ws').value.trim();
    const targetPath = document.getElementById('parallel-path').value.trim();
    const baseRef = document.getElementById('parallel-base').value.trim();
    if (!repo || !branch) return alert("Repository path and branch are required");

    const btn = document.getElementById('btn-submit-parallel');
    const output = document.getElementById('parallel-output');
    btn.disabled = true;
    btn.innerText = "Creating...";
    output.style.display = 'block';
    output.innerText = "Running parallel.py add...";

    const res = await fetch('/api/parallel/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            repo_path: repo,
            branch: branch,
            workspace_name: ws || null,
            target_path: targetPath || null,
            base_ref: baseRef || null
        })
    });

    btn.disabled = false;
    btn.innerText = "Create & Track";

    if (res.ok) {
        const data = await res.json();
        output.innerText = data.output || `Created ${data.repo_path} / ${data.workspace}`;
        await fetchProjects();
        alert(`Parallel worktree created and tracked:\n${data.repo_path}\nworkspace: ${data.workspace}`);
        hideParallelModal();
    } else {
        const err = await res.json();
        output.innerText = err.detail || "Failed to create worktree";
        alert("Failed to create parallel worktree: " + (err.detail || "unknown error"));
    }
}

function updateGlobalSummary(projects) {
    const running = projects.filter(p => p.is_running).length;
    const action = projects.filter(p => !p.is_running && p.status === 'human_required').length;
    const complete = projects.filter(p => p.status === 'complete' || p.status === 'done').length;
    document.getElementById('sum-total').innerText = projects.length;
    document.getElementById('sum-running').innerText = running;
    document.getElementById('sum-action').innerText = action;
    document.getElementById('sum-complete').innerText = complete;
}

async function fetchProjects() {
    const res = await fetch('/api/projects');
    const projects = await res.json();
    renderProjectList(projects);
    updateGlobalInbox(projects);
}

async function updateGlobalInbox(projects) {
    const countSpan = document.getElementById('inbox-count');
    const listDiv = document.getElementById('inbox-list');
    if (!listDiv || !countSpan) return;

    const blockedProjects = projects.filter(p => p.status === 'human_required');
    countSpan.innerText = blockedProjects.length;

    if (blockedProjects.length === 0) {
        listDiv.innerHTML = `
            <div class="text-center py-8 text-gray-500 bg-gray-900 rounded-lg border border-dashed border-gray-700">
                <p class="mt-2 text-sm font-semibold">Inbox clean! No projects require human attention.</p>
            </div>
        `;
        return;
    }

    const contexts = {};
    await Promise.all(blockedProjects.map(async (p) => {
        try {
            const res = await fetch(`/api/projects/${p.id}/human-context`);
            contexts[p.id] = res.ok ? await res.json() : {};
        } catch (err) {
            contexts[p.id] = {};
        }
    }));

    listDiv.innerHTML = '';
    blockedProjects.forEach((p, idx) => {
        const ctx = contexts[p.id] || {};
        const reasonCode = ctx.reason_code || 'unknown';
        const reason = ctx.reason || 'No structured reason was provided.';
        const excerpt = ctx.log_excerpt || 'No log excerpt available.';
        const detailId = `inbox-detail-${idx}`;
        const repoName = escapeHtml(p.repo_name);
        const workspace = escapeHtml(p.workspace);
        const phase = escapeHtml(p.phase || 'N/A');
        const stuck = escapeHtml(p.stuck || '0');
        const safeReasonCode = escapeHtml(reasonCode);

        const card = document.createElement('div');
        card.className = "p-4 bg-gray-900 border border-yellow-600/40 hover:border-yellow-500 rounded-lg transition hover:bg-gray-850 shadow-sm";

        card.innerHTML = `
            <div class="flex justify-between items-start gap-4">
                <div class="min-w-0">
                    <button class="text-left font-bold text-white text-sm hover:text-blue-300 transition"
                        onclick="selectProjectFromInbox('${p.id}')">${repoName}</button>
                    <span class="ml-2 text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded-full font-mono">${workspace}</span>
                    <div class="text-xs text-yellow-500 mt-1 flex flex-wrap items-center gap-2">
                        <span>Phase: <strong>${phase}</strong></span>
                        <span class="text-gray-600">|</span>
                        <span>Stuck: <strong>${stuck}</strong></span>
                        <span class="text-gray-600">|</span>
                        <span class="font-mono">${safeReasonCode}</span>
                    </div>
                    <div class="text-xs text-gray-300 mt-2 line-clamp-2">${escapeHtml(reason)}</div>
                </div>
                <div class="flex items-center gap-2 shrink-0">
                    <button class="px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-200 rounded text-xs font-semibold"
                        onclick="toggleInboxDetail('${detailId}')">Details</button>
                    <button class="px-2 py-1 bg-blue-700 hover:bg-blue-600 text-white rounded text-xs font-semibold"
                        onclick="selectProjectFromInbox('${p.id}')">Open</button>
                </div>
            </div>
            <div id="${detailId}" class="mt-3 hidden border-t border-gray-700 pt-3">
                <div class="text-xs text-gray-400 mb-1 font-semibold">Recent context</div>
                <pre class="text-xs bg-gray-950 border border-gray-800 rounded p-2 overflow-x-auto whitespace-pre-wrap max-h-32">${escapeHtml(excerpt)}</pre>
                <div class="mt-3 flex flex-wrap gap-2">
                    <button class="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-white rounded text-xs"
                        onclick="selectProjectFromInbox('${p.id}', 'logs')">Open Logs</button>
                    <button class="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-white rounded text-xs"
                        onclick="selectProjectFromInbox('${p.id}', 'changes')">View Changes</button>
                    <button class="px-2 py-1 bg-blue-700 hover:bg-blue-600 text-white rounded text-xs"
                        onclick="selectProjectFromInbox('${p.id}', 'overview')">Resolve</button>
                </div>
            </div>
        `;
        listDiv.appendChild(card);
    });
}

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function toggleInboxDetail(detailId) {
    const detail = document.getElementById(detailId);
    if (!detail) return;
    detail.classList.toggle('hidden');
}

async function selectProjectFromInbox(projectId, tab = 'overview') {
    const res = await fetch('/api/projects');
    if (!res.ok) return;
    const projects = await res.json();
    const project = projects.find(p => p.id === projectId);
    if (!project) return;
    await selectProject(project);
    if (tab) switchTab(tab);
}

function showDashboardHome() {
    currentProjectId = null;
    document.getElementById('main-content').style.display = 'none';
    document.getElementById('blank-state-content').style.display = 'block';

    const cards = document.querySelectorAll('.project-card');
    cards.forEach(c => c.classList.remove('selected', 'border-blue-500'));

    fetchProjects();
}

function renderProjectList(projects) {
    updateGlobalSummary(projects);
    checkStatusTransitions(projects);

    const sig = JSON.stringify(projects.map(p =>
        [p.id, p.status, p.is_running, p.stale_lock, p.phase, p.stuck, p.started_at, p.heartbeat_age]
    )) + '|' + currentProjectId + '|' + sidebarLayout;
    if (sig === lastProjectsSig) return;
    lastProjectsSig = sig;

    const listDiv = document.getElementById('project-list');
    listDiv.innerHTML = '';
    if (sidebarLayout === 'grid') {
        listDiv.className = "grid grid-cols-1 md:grid-cols-2 gap-4";
    } else {
        listDiv.className = "space-y-4";
    }

    if (projects.length === 0) {
        listDiv.innerHTML = '<div class="text-gray-500">No projects found in index.md</div>';
        return;
    }

    projects.forEach(p => {
        const isRunning = p.is_running;
        let badgeClass = 'bg-gray-600 text-gray-200';
        let statusLabel = p.status;
        if (isRunning) {
            badgeClass = 'bg-green-600 text-white animate-pulse';
            statusLabel = 'Running';
        } else if (p.status === 'human_required') {
            badgeClass = 'bg-yellow-600 text-white';
            statusLabel = 'Action Needed';
        } else if (p.status === 'complete' || p.status === 'done') {
            badgeClass = 'bg-emerald-600 text-white';
            statusLabel = 'Complete';
        } else if (p.status === 'FAIL') {
            badgeClass = 'bg-red-600 text-white';
        }

        let staleBadge = '';
        if (p.stale_lock && !isRunning) {
            staleBadge = `<span class="ml-2 px-1.5 py-0.5 bg-yellow-600 text-white rounded text-[10px] font-bold">⚠️ Stale Lock</span>`;
        }

        const stuckVal = parseInt(p.stuck) || 0;
        let stuckClass = 'text-gray-200';
        if (p.status === 'human_required' || p.status === 'FROZEN') {
            stuckClass = 'text-red-500 animate-pulse';
        } else if (stuckVal >= 2) {
            stuckClass = 'text-orange-500';
        } else if (stuckVal === 1) {
            stuckClass = 'text-yellow-400';
        }

        let runningInfo = '';
        if (isRunning && p.started_at) {
            const startMs = Date.parse(p.started_at.replace(/-/g, '/'));
            const diffSec = Math.max(0, Math.floor((Date.now() - startMs) / 1000));
            const durStr = formatDuration(diffSec);
            let hbStr = '';
            let hbClass = 'text-gray-400';
            let hbTitle = '';
            if (p.heartbeat_age !== null && p.heartbeat_age !== undefined) {
                hbStr = ` · ♥ ${p.heartbeat_age}s ago`;
                if (p.heartbeat_age > 1800) {
                    hbClass = 'text-red-500 font-bold animate-pulse';
                    hbTitle = 'Possible Stall';
                }
            }
            runningInfo = `<div class="text-[10px] ${hbClass} mt-1" title="${hbTitle}">⏱ running ${durStr}${hbStr}</div>`;
        }

        const card = document.createElement('div');
        card.className = `p-4 bg-gray-800 rounded-lg cursor-pointer border hover:border-blue-500 transition ${currentProjectId === p.id ? 'border-blue-500 bg-gray-750' : 'border-gray-700'}`;
        card.onclick = () => selectProject(p);

        card.innerHTML = `
            <div class="flex justify-between items-start mb-2">
                <div>
                    <div class="font-bold text-lg text-white flex items-center gap-1">${p.repo_name}${staleBadge}</div>
                    <div class="text-xs text-gray-400 font-mono">${p.workspace}</div>
                    ${runningInfo}
                </div>
                <div class="flex items-center gap-2">
                    <span class="px-2 py-0.5 rounded text-xs font-semibold ${badgeClass}">${statusLabel}</span>
                    <button onclick="untrackProject(event, '${p.id}', '${p.repo_name}')" class="text-gray-550 hover:text-red-400 font-bold text-sm px-1.5 py-0.5 rounded hover:bg-gray-700 transition" title="Untrack project">✕</button>
                </div>
            </div>
            <div class="grid grid-cols-2 gap-2 text-xs text-gray-400 pt-2 border-t border-gray-700">
                <div>Phase: <span class="text-gray-200 font-semibold">${p.phase}</span></div>
                <div>Stuck: <span class="${stuckClass} font-semibold">${stuckVal === 0 ? '0' : stuckVal + ' ⚠️'}</span></div>
            </div>
        `;
        listDiv.appendChild(card);
    });
}

async function selectProject(p) {
    currentProjectId = p.id;
    document.getElementById('main-content').style.display = 'block';
    document.getElementById('blank-state-content').style.display = 'none';
    document.getElementById('ws-title').innerText = `${p.repo_name} / ${p.workspace}`;
    document.getElementById('ws-path').innerText = p.repo;
    document.getElementById('ws-phase').innerText = p.phase;
    document.getElementById('ws-stuck').innerText = p.stuck;
    document.getElementById('ws-status').innerText = p.status;

    const isRunning = p.is_running;
    let badgeClass = 'bg-gray-600 text-gray-200';
    let statusLabel = p.status;
    if (isRunning) {
        badgeClass = 'bg-green-600 text-white animate-pulse';
        statusLabel = 'Running';
    } else if (p.status === 'human_required') {
        badgeClass = 'bg-yellow-600 text-white';
        statusLabel = 'Action Needed';
    } else if (p.status === 'complete' || p.status === 'done') {
        badgeClass = 'bg-emerald-600 text-white';
        statusLabel = 'Complete';
    } else if (p.status === 'FAIL') {
        badgeClass = 'bg-red-600 text-white';
    }

    const wsBadge = document.getElementById('ws-status-badge');
    wsBadge.innerText = statusLabel;
    wsBadge.className = `px-2 py-0.5 rounded text-xs font-semibold ${badgeClass}`;

    if (p.is_running) {
        document.getElementById('start-actions-group').style.display = 'none';
        document.getElementById('btn-stop').style.display = 'inline-block';
        document.getElementById('btn-clear-lock').style.display = 'none';
    } else {
        document.getElementById('start-actions-group').style.display = 'flex';
        document.getElementById('btn-stop').style.display = 'none';
        if (p.stale_lock) {
            document.getElementById('btn-clear-lock').style.display = 'inline-block';
        } else {
            document.getElementById('btn-clear-lock').style.display = 'none';
        }
    }

    if (p.stale_lock && !p.is_running) {
        document.getElementById('ws-stale-badge').style.display = 'inline-block';
    } else {
        document.getElementById('ws-stale-badge').style.display = 'none';
    }

    const wsStuck = document.getElementById('ws-stuck');
    const cardWsStuck = document.getElementById('card-ws-stuck');
    const stuckVal = parseInt(p.stuck) || 0;
    if (cardWsStuck && wsStuck) {
        if (p.status === 'human_required' || p.status === 'FROZEN') {
            cardWsStuck.className = "bg-red-950 border border-red-500/50 p-3 rounded";
            wsStuck.className = "text-lg font-bold text-red-500 animate-pulse";
            wsStuck.innerText = `${stuckVal} ⚠️`;
        } else if (stuckVal >= 2) {
            cardWsStuck.className = "bg-orange-950 border border-orange-500/50 p-3 rounded";
            wsStuck.className = "text-lg font-bold text-orange-500 animate-pulse";
            wsStuck.innerText = `${stuckVal} ⚠️`;
        } else if (stuckVal === 1) {
            cardWsStuck.className = "bg-yellow-900/60 border border-yellow-600/40 p-3 rounded";
            wsStuck.className = "text-lg font-semibold text-yellow-400";
            wsStuck.innerText = `${stuckVal} ⚠️`;
        } else {
            cardWsStuck.className = "bg-gray-700 p-3 rounded";
            wsStuck.className = "text-lg font-semibold text-white";
            wsStuck.innerText = stuckVal;
        }
    }

    const wsRunningInfo = document.getElementById('ws-running-info');
    if (isRunning && p.started_at) {
        const startMs = Date.parse(p.started_at.replace(/-/g, '/'));
        const diffSec = Math.max(0, Math.floor((Date.now() - startMs) / 1000));
        const durStr = formatDuration(diffSec);
        let hbStr = '';
        if (p.heartbeat_age !== null && p.heartbeat_age !== undefined) {
            hbStr = ` · Heartbeat ${p.heartbeat_age}s ago`;
            if (p.heartbeat_age > 1800) {
                wsRunningInfo.className = "text-xs text-red-500 font-bold animate-pulse";
                wsRunningInfo.innerText = `⏱ running ${durStr}${hbStr} (⚠️ Possible Stall)`;
            } else {
                wsRunningInfo.className = "text-xs text-gray-300 font-mono";
                wsRunningInfo.innerText = `⏱ running ${durStr}${hbStr}`;
            }
        } else {
            wsRunningInfo.className = "text-xs text-gray-300 font-mono";
            wsRunningInfo.innerText = `⏱ running ${durStr}`;
        }
        wsRunningInfo.style.display = 'inline-block';
    } else {
        wsRunningInfo.style.display = 'none';
    }

    checkHumanContext(p.id, p.status === 'human_required');

    switchTab('overview');
    loadControlData(p.id);
    loadActivityTimeline(p.id);
    loadRoundsSparkline(p.id);

    document.getElementById('node-details-empty').style.display = 'block';
    document.getElementById('node-details-content').style.display = 'none';
    document.getElementById('node-details-actions').style.display = 'none';
    selectedNodeId = null;

    fetchProjects();

    const res = await fetch(`/api/projects/${p.id}/config`);
    if (res.ok) {
        const data = await res.json();
        document.getElementById('config-editor').value = data.content;
    } else {
        document.getElementById('config-editor').value = "# Failed to load config";
    }

    switchLog('loop');
    await loadTree(p.id);
}

async function loadTree(projId) {
    const res = await fetch(`/api/projects/${projId}/tree`);
    if (!res.ok) return;
    const data = await res.json();

    const treeContainer = document.getElementById('tree-container');
    treeContainer.innerHTML = '';

    const tabTree = document.getElementById('tab-tree');
    if (data.tree_enabled) {
        tabTree.style.display = 'inline-block';
        currentTreeNodes = data.nodes;

        const rootNode = data.nodes.find(n => n.id === data.root);
        if (rootNode) {
            const treeRootUl = document.createElement('ul');
            treeRootUl.appendChild(renderTreeNode(rootNode));
            treeContainer.appendChild(treeRootUl);
        } else {
            treeContainer.innerHTML = '<div class="text-gray-500">Root node not found in TREE.md</div>';
        }
    } else {
        tabTree.style.display = 'none';
        if (document.getElementById('tab-tree').classList.contains('text-blue-400')) {
            switchTab('logs');
        }
    }
}

function renderTreeNode(node) {
    const li = document.createElement('li');

    let borderClass = 'border-gray-700';
    switch (node.state) {
        case 'PENDING':
            borderClass = 'border-gray-600 text-gray-400 hover:border-gray-500';
            break;
        case 'IN_PROGRESS':
            borderClass = 'border-blue-500 text-blue-400 shadow-md shadow-blue-900/30 hover:border-blue-400 animate-pulse';
            break;
        case 'CONVERGED':
            borderClass = 'border-emerald-500 text-emerald-400 hover:border-emerald-400';
            break;
        case 'NEEDS_REVISION':
            borderClass = 'border-yellow-500 text-yellow-400 hover:border-yellow-400';
            break;
        case 'FROZEN':
            borderClass = 'border-red-500 text-red-500 hover:border-red-400';
            break;
        case 'DECOMPOSED':
            borderClass = 'border-indigo-500 text-indigo-400 hover:border-indigo-400';
            break;
        default:
            borderClass = 'border-teal-500 text-teal-400 hover:border-teal-400';
    }

    const nodeDiv = document.createElement('div');
    nodeDiv.className = `node-card ${borderClass} ${selectedNodeId === node.id ? 'selected bg-gray-850' : ''}`;
    nodeDiv.onclick = (e) => {
        e.stopPropagation();
        selectTreeNode(node.id);
    };

    nodeDiv.innerHTML = `
        <div class="font-bold font-mono text-sm text-white">${node.id}</div>
        <div class="text-xs text-gray-400 truncate max-w-[180px] mt-1">${node.description || ''}</div>
        <div class="flex justify-between items-center mt-2 text-[10px]">
            <span class="text-gray-500 font-semibold">D:${node.depth} R:${node.reflow_count}</span>
            <span class="font-semibold uppercase tracking-wider">${node.state}</span>
        </div>
    `;

    li.appendChild(nodeDiv);

    if (node.children && node.children.length > 0) {
        const ul = document.createElement('ul');
        node.children.forEach(childId => {
            const childNode = currentTreeNodes.find(n => n.id === childId);
            if (childNode) {
                ul.appendChild(renderTreeNode(childNode));
            }
        });
        li.appendChild(ul);
    }

    return li;
}

function selectTreeNode(nodeId) {
    selectedNodeId = nodeId;

    document.querySelectorAll('.node-card').forEach(el => {
        el.classList.remove('selected');
    });

    const node = currentTreeNodes.find(n => n.id === nodeId);
    if (!node) return;

    document.getElementById('node-details-empty').style.display = 'none';
    document.getElementById('node-details-content').style.display = 'block';
    document.getElementById('node-details-actions').style.display = 'block';

    document.getElementById('nd-id').innerText = node.id;
    document.getElementById('nd-desc').innerText = node.description || '(No description)';
    document.getElementById('nd-depth').innerText = node.depth;
    document.getElementById('nd-stable').innerText = node.stable_rounds;
    document.getElementById('nd-reflow').innerText = node.reflow_count;

    const stateSpan = document.getElementById('nd-state');
    stateSpan.innerText = node.state;

    let stateClass = 'bg-gray-700 text-gray-300';
    switch (node.state) {
        case 'PENDING': stateClass = 'bg-gray-700 text-gray-300'; break;
        case 'IN_PROGRESS': stateClass = 'bg-blue-600 text-white animate-pulse'; break;
        case 'CONVERGED': stateClass = 'bg-emerald-600 text-white'; break;
        case 'NEEDS_REVISION': stateClass = 'bg-yellow-600 text-white'; break;
        case 'FROZEN': stateClass = 'bg-red-600 text-white'; break;
        case 'DECOMPOSED': stateClass = 'bg-indigo-600 text-white'; break;
        default: stateClass = 'bg-teal-600 text-white';
    }
    stateSpan.className = `px-2 py-0.5 rounded font-mono text-xs ${stateClass}`;

    document.querySelectorAll('.node-card').forEach(card => {
        if (card.querySelector('.font-mono').innerText === nodeId) {
            card.classList.add('selected');
        }
    });
}

async function rejectSubtree() {
    if (!currentProjectId || !selectedNodeId) return;
    const confirmReject = confirm(`Are you sure you want to reject subtree [${selectedNodeId}]?\nThis will revert this subtree and all its children back to PENDING and start replanning.`);
    if (!confirmReject) return;

    const btnReject = document.getElementById('btn-reject');
    btnReject.innerText = "Rejecting...";
    btnReject.disabled = true;

    const res = await fetch(`/api/projects/${currentProjectId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subtree_id: selectedNodeId })
    });

    btnReject.innerText = "Reject & Replan Subtree";
    btnReject.disabled = false;

    if (res.ok) {
        alert(`Subtree [${selectedNodeId}] rejected successfully. Re-planning started in the background.`);
        switchTab('logs');
        fetchProjects().then(() => {
            const p = document.getElementById('ws-title').innerText;
            selectProject({ id: currentProjectId, repo_name: p.split('/')[0].trim(), workspace: p.split('/')[1].trim(), phase: '-', stuck: '-', status: '-', is_running: false, repo: document.getElementById('ws-path').innerText });
        });
    } else {
        const err = await res.json();
        alert("Failed to reject: " + err.detail);
    }
}

async function untrackProject(event, projId, repoName) {
    event.stopPropagation();
    const confirmUntrack = confirm(`Are you sure you want to untrack project [${repoName}]?\nIts local files will NOT be deleted.`);
    if (!confirmUntrack) return;

    const res = await fetch(`/api/projects/${projId}`, {
        method: 'DELETE'
    });

    if (res.ok) {
        alert("Project untracked successfully!");
        if (currentProjectId === projId) {
            currentProjectId = null;
            document.getElementById('main-content').style.display = 'none';
        }
        fetchProjects();
    } else {
        const err = await res.json();
        alert("Failed to untrack: " + err.detail);
    }
}

async function checkHumanContext(projId, isHuman) {
    const banner = document.getElementById('human-required-banner');
    if (!isHuman) {
        banner.style.display = 'none';
        return;
    }
    try {
        const res = await fetch(`/api/projects/${projId}/human-context`);
        if (res.ok) {
            const data = await res.json();
            if (data.human_required) {
                banner.style.display = 'block';
                document.getElementById('human-reason').innerText = data.reason || 'Unknown Reason';
                document.getElementById('human-log-excerpt').innerText = data.log_excerpt || 'No log excerpt available.';
                renderNextActions(data.reason_code, data.reason);
            } else {
                banner.style.display = 'none';
            }
        } else {
            banner.style.display = 'none';
        }
    } catch (err) {
        console.error("Error fetching human context:", err);
        banner.style.display = 'none';
    }
}

function renderNextActions(reasonCode, reasonMsg) {
    const textDiv = document.getElementById('next-action-text');
    const btnsDiv = document.getElementById('next-action-buttons');
    textDiv.innerHTML = '';
    btnsDiv.innerHTML = '';

    const safeReason = escapeHtml(reasonMsg || 'No detailed reason was provided.');
    const actions = {
        git_review_human_conflict: {
            instruction: '<strong>Git review conflict.</strong> A human commit likely conflicted with an automatic revert. Review the current diff and git state, then resume when the workspace is safe.',
            buttons: [
                { text: 'View Changes', click: () => switchTab('changes'), class: 'bg-indigo-700 hover:bg-indigo-600' },
                { text: 'Open Logs', click: () => switchTab('logs'), class: 'bg-gray-700 hover:bg-gray-600' }
            ]
        },
        tree_structure_error: {
            instruction: '<strong>Planning tree structure issue.</strong> The tree has a missing or invalid node relationship. Inspect the Planning Tree before resuming.',
            buttons: [
                { text: 'Open Planning Tree', click: () => switchTab('tree'), class: 'bg-indigo-700 hover:bg-indigo-600' },
                { text: 'Open Logs', click: () => switchTab('logs'), class: 'bg-gray-700 hover:bg-gray-600' }
            ]
        },
        max_leaf_reflow_exceeded: {
            instruction: '<strong>Leaf reflow limit reached.</strong> A task was revised too many times. Clarify requirements or manually fix the affected code before resuming.',
            buttons: [
                { text: 'View Requirements', click: () => viewDoc('REQUIREMENTS.md'), class: 'bg-indigo-700 hover:bg-indigo-600' },
                { text: 'View Changes', click: () => switchTab('changes'), class: 'bg-gray-700 hover:bg-gray-600' }
            ]
        },
        stuck_level_2_hard_stop: {
            instruction: '<strong>Hard stop after repeated no-progress rounds.</strong> Review the current changes and requirements, then make a manual adjustment or clarify the task before resuming.',
            buttons: [
                { text: 'View Requirements', click: () => viewDoc('REQUIREMENTS.md'), class: 'bg-indigo-700 hover:bg-indigo-600' },
                { text: 'View Changes', click: () => switchTab('changes'), class: 'bg-gray-700 hover:bg-gray-600' }
            ]
        },
        plan_stuck_threshold_exceeded: {
            instruction: '<strong>Planning did not converge.</strong> Review requirements and planning logs. Clarify the target before starting planning again.',
            buttons: [
                { text: 'View Requirements', click: () => viewDoc('REQUIREMENTS.md'), class: 'bg-indigo-700 hover:bg-indigo-600' },
                { text: 'Open Plan Logs', click: () => { switchTab('logs'); switchLog('plan'); }, class: 'bg-gray-700 hover:bg-gray-600' }
            ]
        },
        max_rounds_reached: {
            instruction: '<strong>Maximum rounds reached.</strong> The loop used its configured round budget. Review the overview, logs, and diff before deciding whether to resume.',
            buttons: [
                { text: 'Open Overview', click: () => switchTab('overview'), class: 'bg-indigo-700 hover:bg-indigo-600' },
                { text: 'Open Logs', click: () => switchTab('logs'), class: 'bg-gray-700 hover:bg-gray-600' }
            ]
        },
        broken_control_file: {
            instruction: '<strong>Control state is damaged.</strong> CONTROL.md is missing or invalid. Repair the workspace state file manually before resuming.',
            buttons: [
                { text: 'Open Logs', click: () => switchTab('logs'), class: 'bg-gray-700 hover:bg-gray-600' }
            ]
        },
        agent_requested: {
            instruction: '<strong>Agent requested human review.</strong> Inspect the logs and current changes, resolve the blocking issue, then resume.',
            buttons: [
                { text: 'Open Logs', click: () => switchTab('logs'), class: 'bg-indigo-700 hover:bg-indigo-600' },
                { text: 'View Changes', click: () => switchTab('changes'), class: 'bg-gray-700 hover:bg-gray-600' }
            ]
        }
    };

    const selected = actions[reasonCode] || {
        instruction: `<strong>Human review required.</strong> ${safeReason} Resolve the issue, then use "I've handled it - Resume".`,
        buttons: [
            { text: 'Open Logs', click: () => switchTab('logs'), class: 'bg-indigo-700 hover:bg-indigo-600' },
            { text: 'View Changes', click: () => switchTab('changes'), class: 'bg-gray-700 hover:bg-gray-600' }
        ]
    };

    textDiv.innerHTML = selected.instruction;

    selected.buttons.forEach(btn => {
        const b = document.createElement('button');
        b.className = `px-3 py-1.5 text-xs font-semibold text-white rounded transition shadow-sm ${btn.class}`;
        b.innerText = btn.text;
        b.onclick = btn.click;
        btnsDiv.appendChild(b);
    });
}

async function resumeProject() {
    if (!currentProjectId) return;
    const banner = document.getElementById('human-required-banner');
    const btnResume = banner.querySelector('button');
    const originalText = btnResume.innerText;
    btnResume.innerText = "Resuming...";
    btnResume.disabled = true;

    const res = await fetch(`/api/projects/${currentProjectId}/resume`, { method: 'POST' });

    btnResume.innerText = originalText;
    btnResume.disabled = false;

    if (res.ok) {
        alert("Project resumed successfully!");
        fetchProjects().then(() => {
            fetch('/api/projects').then(r => r.json()).then(projects => {
                const p = projects.find(x => x.id === currentProjectId);
                if (p) selectProject(p);
            });
        });
    } else {
        const err = await res.json();
        alert("Failed to resume project: " + err.detail);
    }
}

async function loadControlData(projId) {
    try {
        const res = await fetch(`/api/projects/${projId}/control`);
        if (!res.ok) return;
        const data = await res.json();

        document.getElementById('ctrl-model-tier').innerText = data.current_model_tier || 'N/A';
        document.getElementById('ctrl-blocking-issues').innerText = data.blocking_issues || '0';
        document.getElementById('ctrl-enhanced-rounds').innerText = data.enhanced_rounds_used || '0';
        const roundsVal = parseInt(data.rounds_since_progress) || 0;
        const cardRounds = document.getElementById('card-rounds-since');
        const textRounds = document.getElementById('ctrl-rounds-since');
        if (cardRounds && textRounds) {
            textRounds.innerText = roundsVal;
            if (roundsVal >= 5) {
                cardRounds.className = "bg-orange-950 p-4 rounded shadow-sm border border-orange-500/50";
                textRounds.className = "text-xl font-bold text-orange-500 animate-pulse";
            } else if (roundsVal >= 3) {
                cardRounds.className = "bg-yellow-900/60 p-4 rounded shadow-sm border border-yellow-600/40";
                textRounds.className = "text-xl font-bold text-yellow-400";
            } else {
                cardRounds.className = "bg-gray-700 p-4 rounded shadow-sm";
                textRounds.className = "text-xl font-bold text-yellow-400";
            }
        }
        document.getElementById('ctrl-plan-version').innerText = data.plan_version || '1';
        document.getElementById('ctrl-last-mode').innerText = data.last_round_mode || 'N/A';
        document.getElementById('ctrl-last-result').innerText = data.last_round_result || 'N/A';

        const tableBody = document.getElementById('phases-table-body');
        tableBody.innerHTML = '';

        if (data.phases && data.phases.length > 0) {
            data.phases.forEach(ph => {
                let consecCell = '';
                if (ph.threshold !== null && ph.threshold !== undefined) {
                    const val = parseInt(ph.consecutive_pass) || 0;
                    const limit = parseInt(ph.threshold) || 1;
                    const pct = Math.min(100, Math.round(val / limit * 100));
                    const isCompleted = pct >= 100;
                    const barColor = isCompleted ? 'bg-emerald-500' : 'bg-blue-505';
                    consecCell = `
                        <div class="flex items-center gap-2">
                            <span class="font-mono text-gray-200">${val}/${limit}</span>
                            <div class="w-24 bg-gray-700 h-2 rounded-full overflow-hidden" title="${pct}% complete">
                                <div class="${barColor} h-full transition-all duration-300" style="width: ${pct}%"></div>
                            </div>
                        </div>
                    `;
                } else {
                    consecCell = `<span class="text-gray-200 font-mono">${ph.consecutive_pass}</span>`;
                }

                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td class="py-3 px-4 text-white font-semibold">Phase ${ph.id}</td>
                    <td class="py-3 px-4">${consecCell}</td>
                    <td class="py-3 px-4 text-gray-200 font-mono">${ph.total_validations}</td>
                    <td class="py-3 px-4"><span class="px-2 py-0.5 rounded text-xs font-semibold ${ph.last_result === 'PASS' ? 'bg-emerald-600/30 text-emerald-400' : 'bg-red-600/30 text-red-400'}">${ph.last_result}</span></td>
                `;
                tableBody.appendChild(tr);
            });
        } else {
            tableBody.innerHTML = '<tr><td colspan="4" class="py-4 text-center text-gray-500">No phase data available.</td></tr>';
        }

        // Render Requirements Mappings
        const reqPanel = document.getElementById('requirements-panel');
        const reqTableBody = document.getElementById('requirements-table-body');
        if (reqPanel && reqTableBody) {
            reqTableBody.innerHTML = '';
            if (data.requirements_map && data.requirements_map.length > 0) {
                reqPanel.style.display = 'block';
                data.requirements_map.forEach(item => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td class="py-3 px-4 text-white font-mono font-semibold">${item.req_id}</td>
                        <td class="py-3 px-4 text-blue-400 font-mono font-semibold">${item.task_id}</td>
                        <td class="py-3 px-4 text-gray-300">${item.verify || '-'}</td>
                    `;
                    reqTableBody.appendChild(tr);
                });
            } else {
                reqPanel.style.display = 'none';
            }
        }

        // Render Project Issues
        const issPanel = document.getElementById('issues-panel');
        const issTableBody = document.getElementById('issues-table-body');
        if (issPanel && issTableBody) {
            issTableBody.innerHTML = '';
            if (data.issues && data.issues.length > 0) {
                issPanel.style.display = 'block';
                data.issues.forEach(item => {
                    const tr = document.createElement('tr');
                    const lvlClass = item.level === 'BLOCKING' ? 'bg-red-600/30 text-red-400' : 'bg-yellow-600/30 text-yellow-400';
                    const statusClass = item.status === 'OPEN' ? 'text-orange-400 font-bold' : 'text-gray-400';
                    tr.innerHTML = `
                        <td class="py-3 px-4 text-white font-mono font-semibold">${item.id}</td>
                        <td class="py-3 px-4"><span class="px-2 py-0.5 rounded text-xs font-semibold ${lvlClass}">${item.level}</span></td>
                        <td class="py-3 px-4 text-gray-200">${item.title}</td>
                        <td class="py-3 px-4 text-gray-300 font-mono">${item.phase || '-'}/${item.task || '-'}</td>
                        <td class="py-3 px-4 ${statusClass}">${item.status}</td>
                        <td class="py-3 px-4 text-gray-400 font-mono">${item.round || '-'}</td>
                    `;
                    issTableBody.appendChild(tr);
                });
            } else {
                issPanel.style.display = 'none';
            }
        }
    } catch (err) {
        console.error("Error loading control data:", err);
    }
}

async function loadActivityTimeline(projId) {
    try {
        const res = await fetch(`/api/projects/${projId}/activity`);
        if (!res.ok) return;
        const events = await res.json();

        const container = document.getElementById('activity-timeline');
        if (!container) return;
        container.innerHTML = '';

        if (events.length === 0) {
            container.innerHTML = '<div class="text-gray-500 text-sm">No activity events found in loop.log.</div>';
            return;
        }

        events.forEach(e => {
            let dotColorClass = 'bg-gray-500';
            if (e.type === 'complete') dotColorClass = 'bg-green-500';
            else if (e.type === 'review_revert') dotColorClass = 'bg-orange-500';
            else if (e.type === 'human_required') dotColorClass = 'bg-red-500';
            else if (e.type === 'model_upgrade') dotColorClass = 'bg-blue-500';
            else if (e.type === 'progress') dotColorClass = 'bg-teal-600';
            else if (e.type === 'leaf_converged') dotColorClass = 'bg-cyan-500';

            const item = document.createElement('div');
            item.className = 'relative pl-2';
            item.innerHTML = `
                <span class="absolute -left-[31px] top-1.5 w-2.5 h-2.5 rounded-full border border-gray-800 ${dotColorClass}"></span>
                <div class="text-sm">
                    <span class="font-semibold text-gray-200">${e.text}</span>
                    <span class="text-xs text-gray-500 ml-2 font-mono">${e.ts}</span>
                </div>
            `;
            container.appendChild(item);
        });
    } catch (err) {
        console.error("Error loading activity timeline:", err);
    }
}

async function loadRoundsSparkline(projId) {
    try {
        const res = await fetch(`/api/projects/${projId}/rounds?limit=100`);
        if (!res.ok) return;
        const rounds = await res.json();

        const container = document.getElementById('rounds-sparkline');
        if (!container) return;

        if (!rounds || rounds.length === 0) {
            container.innerHTML = '<div class="text-gray-500 text-sm">No round history found in rounds.jsonl.</div>';
            return;
        }

        const stepX = 12;
        const w = Math.max(rounds.length * stepX, 200);
        const h = 60;
        const maxStuck = 2;
        const points = rounds.map((r, i) => {
            const x = i * stepX + 6;
            const stuck = Math.min(Math.max(parseInt(r.stuck_level) || 0, 0), maxStuck);
            const y = h - 6 - (stuck / maxStuck) * (h - 12);
            return { x, y, r };
        });

        const polyline = points.map(p => `${p.x},${p.y}`).join(' ');
        const dots = points.map(p => {
            let color = '#6b7280';
            if (p.r.killed) color = '#a855f7';
            else if (p.r.result === 'PASS') color = '#22c55e';
            else if (p.r.result === 'FAIL') color = '#ef4444';
            const title = `round ${p.r.round ?? '?'} | ${p.r.ts ?? ''} | stuck=${p.r.stuck_level ?? '-'} | result=${p.r.result ?? '-'}${p.r.killed ? ' | killed=' + p.r.killed : ''}`;
            return `<circle cx="${p.x}" cy="${p.y}" r="3" fill="${color}"><title>${title}</title></circle>`;
        }).join('');

        container.innerHTML = `
            <svg width="${w}" height="${h}" class="block">
                <polyline points="${polyline}" fill="none" stroke="#fbbf24" stroke-width="1.5" />
                ${dots}
            </svg>
            <div class="text-[10px] text-gray-500 mt-1">stuck_level over last ${rounds.length} rounds &middot; 🟢 PASS &nbsp;🔴 FAIL &nbsp;🟣 killed &nbsp;⚪ other</div>
        `;
    } catch (err) {
        console.error("Error loading rounds sparkline:", err);
    }
}

function renderColoredDiff(diffText) {
    const container = document.getElementById('diff-window');
    if (!container) return;
    if (!diffText || diffText.trim() === "") {
        container.innerHTML = `<span class="text-gray-505">No changes since last safe point</span>`;
        return;
    }

    const lines = diffText.split('\n');
    const fragment = document.createDocumentFragment();

    lines.forEach(line => {
        const div = document.createElement('div');

        if (line.startsWith('+') && !line.startsWith('+++')) {
            div.className = 'text-green-450 bg-green-950/20';
            div.textContent = line;
        } else if (line.startsWith('-') && !line.startsWith('---')) {
            div.className = 'text-red-455 bg-red-955/20';
            div.textContent = line;
        } else if (line.startsWith('@@')) {
            div.className = 'text-blue-300 font-semibold';
            div.textContent = line;
        } else if (line.startsWith('diff --git') || line.startsWith('index ') || line.startsWith('--- ') || line.startsWith('+++ ')) {
            div.className = 'text-white font-bold border-b border-gray-800 pb-0.5 mt-2';
            div.textContent = line;
        } else {
            div.className = 'text-gray-300';
            div.textContent = line;
        }
        fragment.appendChild(div);
    });

    container.innerHTML = '';
    container.appendChild(fragment);
}

async function loadDiffData() {
    if (!currentProjectId) return;
    const container = document.getElementById('diff-window');
    if (!container) return;
    container.innerHTML = '<span class="text-gray-500">Loading diff...</span>';
    try {
        const res = await fetch(`/api/projects/${currentProjectId}/diff`);
        if (!res.ok) {
            container.innerHTML = `<span class="text-red-500">Failed to load diff</span>`;
            return;
        }
        const data = await res.json();
        document.getElementById('diff-base').innerText = data.base || 'None';
        document.getElementById('diff-head').innerText = data.head || 'None';
        renderColoredDiff(data.diff);
    } catch (err) {
        console.error("Error loading diff:", err);
        container.innerHTML = `<span class="text-red-500">Error: ${err.message}</span>`;
    }
}

function viewNodeSpec() {
    if (!selectedNodeId) return;
    viewDoc(`tree/${selectedNodeId}.decomp.md`);
}

async function viewDoc(path) {
    if (!currentProjectId) return;
    const modal = document.getElementById('doc-modal');
    const titleSpan = document.getElementById('doc-modal-title');
    const contentDiv = document.getElementById('doc-modal-content');
    if (!modal || !titleSpan || !contentDiv) return;

    titleSpan.innerText = path;
    contentDiv.innerHTML = '<span class="text-gray-500">Loading document...</span>';
    modal.style.display = 'flex';

    try {
        const res = await fetch(`/api/projects/${currentProjectId}/doc?path=${encodeURIComponent(path)}`);
        if (!res.ok) {
            const err = await res.json();
            contentDiv.innerHTML = `<span class="text-red-500 font-semibold">Error: ${err.detail || 'Failed to read document'}</span>`;
            return;
        }
        const data = await res.json();
        contentDiv.textContent = data.content;
    } catch (err) {
        console.error("Error fetching document:", err);
        contentDiv.innerHTML = `<span class="text-red-500 font-semibold">Error: ${err.message}</span>`;
    }
}

function hideDocModal() {
    const modal = document.getElementById('doc-modal');
    if (modal) modal.style.display = 'none';
}

async function startProject() {
    if (!currentProjectId) return;
    const modeSelect = document.getElementById('start-mode-select');
    const [mode, stage] = modeSelect.value.split('|');

    const preflightRes = await fetch(`/api/projects/${currentProjectId}/preflight`);
    if (preflightRes.ok) {
        const preflight = await preflightRes.json();
        if (!preflight.ok) {
            await runPreflight();
            const proceed = confirm("Preflight found items that need attention. Start anyway?");
            if (!proceed) return;
        }
    }

    document.getElementById('btn-start').innerText = "Starting...";
    const res = await fetch(`/api/projects/${currentProjectId}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: mode, stage: stage })
    });
    if (res.ok) {
        setTimeout(() => {
            fetchProjects().then(() => {
                const p = document.getElementById('ws-title').innerText;
                selectProject({ id: currentProjectId, repo_name: p.split('/')[0].trim(), workspace: p.split('/')[1].trim(), phase: '-', stuck: '-', status: '-', is_running: true, repo: document.getElementById('ws-path').innerText });
            });
        }, 1000);
    } else {
        const err = await res.json();
        alert("Failed to start: " + err.detail);
        document.getElementById('btn-start').innerText = "Start";
    }
}

async function stopProject() {
    if (!currentProjectId) return;
    document.getElementById('btn-stop').innerText = "Stopping...";
    const res = await fetch(`/api/projects/${currentProjectId}/stop`, { method: 'POST' });
    if (res.ok) {
        setTimeout(() => {
            fetchProjects().then(() => {
                const p = document.getElementById('ws-title').innerText;
                selectProject({ id: currentProjectId, repo_name: p.split('/')[0].trim(), workspace: p.split('/')[1].trim(), phase: '-', stuck: '-', status: '-', is_running: false, repo: document.getElementById('ws-path').innerText });
            });
        }, 1000);
    } else {
        alert("Failed to stop");
        document.getElementById('btn-stop').innerText = "Force Stop";
    }
}

async function clearLock() {
    if (!currentProjectId) return;
    const res = await fetch(`/api/projects/${currentProjectId}/clear-lock`, { method: 'POST' });
    if (res.ok) {
        alert("Lock cleared successfully!");
        fetchProjects().then(() => {
            fetch('/api/projects').then(r => r.json()).then(projects => {
                const p = projects.find(x => x.id === currentProjectId);
                if (p) selectProject(p);
            });
        });
    } else {
        const err = await res.json();
        alert("Failed to clear lock: " + err.detail);
    }
}

async function runPreflight() {
    if (!currentProjectId) return;
    const panel = document.getElementById('preflight-panel');
    const summary = document.getElementById('preflight-summary');
    const list = document.getElementById('preflight-list');
    panel.style.display = 'block';
    summary.innerText = 'Checking...';
    summary.className = 'px-2 py-0.5 rounded text-xs font-semibold bg-gray-600 text-white';
    list.innerHTML = '<div class="text-gray-500">Running checks...</div>';

    const res = await fetch(`/api/projects/${currentProjectId}/preflight`);
    if (!res.ok) {
        const err = await res.json();
        summary.innerText = 'Failed';
        summary.className = 'px-2 py-0.5 rounded text-xs font-semibold bg-red-600 text-white';
        list.innerHTML = `<div class="text-red-400">${err.detail || 'Preflight failed'}</div>`;
        return;
    }

    const data = await res.json();
    summary.innerText = data.ok ? 'Ready' : 'Needs Attention';
    summary.className = data.ok
        ? 'px-2 py-0.5 rounded text-xs font-semibold bg-emerald-600 text-white'
        : 'px-2 py-0.5 rounded text-xs font-semibold bg-yellow-600 text-white';
    list.innerHTML = '';
    data.checks.forEach(check => {
        const row = document.createElement('div');
        row.className = 'flex items-start justify-between gap-3 bg-gray-900 border border-gray-700 rounded p-2';
        row.innerHTML = `
            <div>
                <div class="font-semibold ${check.ok ? 'text-emerald-400' : 'text-yellow-400'}">${check.ok ? '✓' : '!'} ${check.label}</div>
                <div class="text-xs text-gray-400 font-mono mt-0.5">${check.detail || ''}</div>
            </div>
            <span class="text-xs px-2 py-0.5 rounded ${check.ok ? 'bg-emerald-700 text-white' : 'bg-yellow-700 text-white'}">${check.ok ? 'OK' : 'Review'}</span>
        `;
        list.appendChild(row);
    });
}

const wizardPresets = {
    opencode: 'opencode run -m {model} {prompt}',
    codex: 'codex exec --model {model} {prompt}',
    claude: 'claude -p {prompt}',
    gemini: 'gemini -m {model} -p {prompt}'
};

function applyWizardPreset() {
    const preset = document.getElementById('wizard-preset').value;
    if (wizardPresets[preset]) {
        document.getElementById('wizard-build-cmd').value = wizardPresets[preset];
    }
}

async function applyConfigWizard() {
    if (!currentProjectId) return;
    let extraArgs = [];
    const rawExtra = document.getElementById('wizard-extra-args').value.trim();
    if (rawExtra) {
        try {
            extraArgs = JSON.parse(rawExtra);
            if (!Array.isArray(extraArgs)) throw new Error("extra_args must be a JSON array");
        } catch (err) {
            alert("extra_args must be a JSON array, e.g. []");
            return;
        }
    }

    const payload = {
        build_cmd: document.getElementById('wizard-build-cmd').value,
        fast_model: document.getElementById('wizard-fast-model').value,
        normal_model: document.getElementById('wizard-normal-model').value,
        thinking_model: document.getElementById('wizard-thinking-model').value,
        mode: document.getElementById('wizard-mode').value,
        extra_args: extraArgs
    };

    const res = await fetch(`/api/projects/${currentProjectId}/config-wizard`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    if (res.ok) {
        const cfg = await fetch(`/api/projects/${currentProjectId}/config`);
        if (cfg.ok) {
            const data = await cfg.json();
            document.getElementById('config-editor').value = data.content;
        }
        alert("Config wizard applied.");
        runPreflight();
    } else {
        const err = await res.json();
        alert("Failed to apply config wizard: " + err.detail);
    }
}

async function saveConfig() {
    if (!currentProjectId) return;
    const content = document.getElementById('config-editor').value;
    const res = await fetch(`/api/projects/${currentProjectId}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content })
    });
    if (res.ok) {
        alert("Config Saved Successfully!");
    } else {
        const err = await res.json();
        alert("Error saving config: " + err.detail);
    }
}

function switchTab(tab) {
    document.getElementById('content-overview').style.display = tab === 'overview' ? 'block' : 'none';
    document.getElementById('content-logs').style.display = tab === 'logs' ? 'block' : 'none';
    document.getElementById('content-changes').style.display = tab === 'changes' ? 'block' : 'none';
    document.getElementById('content-config').style.display = tab === 'config' ? 'block' : 'none';
    document.getElementById('content-tree').style.display = tab === 'tree' ? 'block' : 'none';

    const tOverview = document.getElementById('tab-overview');
    const tLogs = document.getElementById('tab-logs');
    const tChanges = document.getElementById('tab-changes');
    const tConfig = document.getElementById('tab-config');
    const tTree = document.getElementById('tab-tree');

    tOverview.className = "border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-300 whitespace-nowrap pb-4 px-1 border-b-2 font-medium text-sm";
    tLogs.className = "border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-300 whitespace-nowrap pb-4 px-1 border-b-2 font-medium text-sm";
    tChanges.className = "border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-300 whitespace-nowrap pb-4 px-1 border-b-2 font-medium text-sm";
    tConfig.className = "border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-300 whitespace-nowrap pb-4 px-1 border-b-2 font-medium text-sm";
    tTree.className = "border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-300 whitespace-nowrap pb-4 px-1 border-b-2 font-medium text-sm";

    if (tab === 'overview') {
        tOverview.className = "border-blue-500 text-blue-400 whitespace-nowrap pb-4 px-1 border-b-2 font-medium text-sm";
    } else if (tab === 'logs') {
        tLogs.className = "border-blue-500 text-blue-400 whitespace-nowrap pb-4 px-1 border-b-2 font-medium text-sm";
    } else if (tab === 'changes') {
        tChanges.className = "border-blue-500 text-blue-400 whitespace-nowrap pb-4 px-1 border-b-2 font-medium text-sm";
        loadDiffData();
    } else if (tab === 'config') {
        tConfig.className = "border-blue-500 text-blue-400 whitespace-nowrap pb-4 px-1 border-b-2 font-medium text-sm";
    } else if (tab === 'tree') {
        tTree.className = "border-blue-500 text-blue-400 whitespace-nowrap pb-4 px-1 border-b-2 font-medium text-sm";
    }
}

function logLineMatchesFilter(text) {
    const q = document.getElementById('log-filter').value.trim().toLowerCase();
    return !q || text.toLowerCase().includes(q);
}

function applyLogFilter() {
    const logWindow = document.getElementById('log-window');
    logWindow.querySelectorAll('div').forEach(div => {
        div.style.display = logLineMatchesFilter(div.textContent) ? '' : 'none';
    });
}

function downloadLog() {
    if (!currentProjectId) return;
    window.open(`/api/projects/${currentProjectId}/logs/${currentLogType}/download`, '_blank');
}

function switchLog(type) {
    if (!currentProjectId) return;
    currentLogType = type;
    document.getElementById('current-log-label').innerText = `Viewing: ${type}.log`;

    if (eventSource) {
        eventSource.close();
    }

    const logWindow = document.getElementById('log-window');
    logWindow.innerHTML = '';

    eventSource = new EventSource(`/api/projects/${currentProjectId}/logs/${type}`);
    eventSource.onmessage = function (event) {
        const div = document.createElement('div');
        div.textContent = event.data;
        div.style.display = logLineMatchesFilter(event.data) ? '' : 'none';
        logWindow.appendChild(div);
        while (logWindow.childNodes.length > MAX_LOG_LINES) {
            logWindow.removeChild(logWindow.firstChild);
        }
        logWindow.scrollTop = logWindow.scrollHeight;
    };
    eventSource.onerror = function (error) {
        console.log("EventSource failed:", error);
        eventSource.close();
    };
}

setInterval(() => {
    if (currentProjectId) {
        fetch('/api/projects').then(r => r.json()).then(projects => {
            const p = projects.find(x => x.id === currentProjectId);
            if (p) {
                document.getElementById('ws-phase').innerText = p.phase;

                const wsStuck = document.getElementById('ws-stuck');
                const cardWsStuck = document.getElementById('card-ws-stuck');
                const stuckVal = parseInt(p.stuck) || 0;
                if (cardWsStuck && wsStuck) {
                    if (p.status === 'human_required' || p.status === 'FROZEN') {
                        cardWsStuck.className = "bg-red-950 border border-red-500/50 p-3 rounded";
                        wsStuck.className = "text-lg font-bold text-red-505 animate-pulse";
                        wsStuck.innerText = `${stuckVal} ⚠️`;
                    } else if (stuckVal >= 2) {
                        cardWsStuck.className = "bg-orange-950 border border-orange-500/50 p-3 rounded";
                        wsStuck.className = "text-lg font-bold text-orange-500 animate-pulse";
                        wsStuck.innerText = `${stuckVal} ⚠️`;
                    } else if (stuckVal === 1) {
                        cardWsStuck.className = "bg-yellow-900/60 border border-yellow-600/40 p-3 rounded";
                        wsStuck.className = "text-lg font-semibold text-yellow-400";
                        wsStuck.innerText = `${stuckVal} ⚠️`;
                    } else {
                        cardWsStuck.className = "bg-gray-700 p-3 rounded";
                        wsStuck.className = "text-lg font-semibold text-white";
                        wsStuck.innerText = stuckVal;
                    }
                }

                document.getElementById('ws-status').innerText = p.status;

                const isRunning = p.is_running;
                let badgeClass = 'bg-gray-600 text-gray-200';
                let statusLabel = p.status;
                if (isRunning) {
                    badgeClass = 'bg-green-600 text-white animate-pulse';
                    statusLabel = 'Running';
                } else if (p.status === 'human_required') {
                    badgeClass = 'bg-yellow-600 text-white';
                    statusLabel = 'Action Needed';
                } else if (p.status === 'complete' || p.status === 'done') {
                    badgeClass = 'bg-emerald-600 text-white';
                    statusLabel = 'Complete';
                } else if (p.status === 'FAIL') {
                    badgeClass = 'bg-red-600 text-white';
                }

                const wsBadge = document.getElementById('ws-status-badge');
                wsBadge.innerText = statusLabel;
                wsBadge.className = `px-2 py-0.5 rounded text-xs font-semibold ${badgeClass}`;

                if (p.is_running) {
                    document.getElementById('start-actions-group').style.display = 'none';
                    document.getElementById('btn-stop').style.display = 'inline-block';
                    document.getElementById('btn-stop').innerText = "Force Stop";
                    document.getElementById('btn-clear-lock').style.display = 'none';
                } else {
                    document.getElementById('start-actions-group').style.display = 'flex';
                    document.getElementById('btn-stop').style.display = 'none';
                    if (p.stale_lock) {
                        document.getElementById('btn-clear-lock').style.display = 'inline-block';
                    } else {
                        document.getElementById('btn-clear-lock').style.display = 'none';
                    }
                }

                if (p.stale_lock && !p.is_running) {
                    document.getElementById('ws-stale-badge').style.display = 'inline-block';
                } else {
                    document.getElementById('ws-stale-badge').style.display = 'none';
                }

                const wsRunningInfo = document.getElementById('ws-running-info');
                if (isRunning && p.started_at) {
                    const startMs = Date.parse(p.started_at.replace(/-/g, '/'));
                    const diffSec = Math.max(0, Math.floor((Date.now() - startMs) / 1000));
                    const durStr = formatDuration(diffSec);
                    let hbStr = '';
                    if (p.heartbeat_age !== null && p.heartbeat_age !== undefined) {
                        hbStr = ` · Heartbeat ${p.heartbeat_age}s ago`;
                        if (p.heartbeat_age > 1800) {
                            wsRunningInfo.className = "text-xs text-red-500 font-bold animate-pulse";
                            wsRunningInfo.innerText = `⏱ running ${durStr}${hbStr} (⚠️ Possible Stall)`;
                        } else {
                            wsRunningInfo.className = "text-xs text-gray-300 font-mono";
                            wsRunningInfo.innerText = `⏱ running ${durStr}${hbStr}`;
                        }
                    } else {
                        wsRunningInfo.className = "text-xs text-gray-300 font-mono";
                        wsRunningInfo.innerText = `⏱ running ${durStr}`;
                    }
                    wsRunningInfo.style.display = 'inline-block';
                } else {
                    wsRunningInfo.style.display = 'none';
                }

                checkHumanContext(p.id, p.status === 'human_required');
            }
            renderProjectList(projects);
        });

        const isOverviewActive = document.getElementById('tab-overview').classList.contains('text-blue-400');
        if (isOverviewActive) {
            loadControlData(currentProjectId);
            loadActivityTimeline(currentProjectId);
            loadRoundsSparkline(currentProjectId);
        }

        const isTreeActive = document.getElementById('tab-tree').classList.contains('text-blue-400');
        if (isTreeActive) {
            loadTree(currentProjectId);
        }
    } else {
        fetchProjects();
    }
}, 5000);

initNotifications();
fetchProjects();
