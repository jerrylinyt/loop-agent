import React, { useState, useEffect, useRef } from 'react'
import { 
  Play, Square, RotateCcw, Settings, AlertCircle, CheckCircle2, 
  Activity, FileText, Terminal, Plus, Trash2, 
  FolderOpen, GitBranch, FileCode, ArrowLeft, AlertTriangle, Download, Loader2, Sparkles, Layers
} from 'lucide-react'

// Interfaces mapping the backend spec
interface Workspace {
  id: string
  repo: string
  repo_name: string
  workspace: string
  mode: 'flat' | 'tree'
  status: 'running' | 'idle' | 'completed' | 'human_required' | 'preflight_blocked'
  direction: 'forward' | 'neutral' | 'backward' | 'stalled' | 'unknown'
  headline: string
  why: string
  updated_at: string
  current: {
    phase: string
    active_leaf: string | null
    stuck_level: number
    rounds_since_progress: number
    model_tier: string
  }
  run: {
    is_running: boolean
    pid: number | null
    started_at: string | null
    heartbeat_age: number | null
  }
  next_action?: {
    kind: string
    label: string
    detail: string
  }
}

interface TimelineEvent {
  ts: string
  type: string
  severity: 'info' | 'warning' | 'error' | 'success'
  title: string
  detail: string
}

interface ProgressRecord {
  round: number
  ts: string
  phase: string
  result: 'PASS' | 'FAIL' | 'UNKNOWN'
  progressed: boolean
  direction: string
  stuck_level: number
  rounds_since_progress: number
  model_tier: string
  fail_fingerprint: string | null
  summary: string
}

interface TreeNode {
  id: string
  state: 'PENDING' | 'RUNNING' | 'CONVERGED' | 'NEEDS_REVISION'
  children: string[]
  parent: string
  depth: number
  stable_rounds: number
  reflow_count: number
  description: string
}

interface TreeData {
  tree_enabled: boolean
  nodes: TreeNode[]
  root: string | null
}

interface PreflightCheck {
  id: string
  label: string
  ok: boolean
  detail: string
}

interface PreflightData {
  ok: boolean
  checks: PreflightCheck[]
}

export default function App() {
  // Navigation and active state
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(null)
  const [activeWorkspace, setActiveWorkspace] = useState<Workspace | null>(null)
  const [activeTab, setActiveTab] = useState<'overview' | 'tree' | 'config' | 'diagnostics'>('overview')
  
  // Loading & interactive states
  const [loading, setLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  
  // Forms states
  const [showInitModal, setShowInitModal] = useState(false)
  const [showTrackModal, setShowTrackModal] = useState(false)
  const [showParallelModal, setShowParallelModal] = useState(false)
  
  const [initForm, setInitForm] = useState({ repo_path: '', workspace_name: 'default' })
  const [trackForm, setTrackForm] = useState({ repo_path: '', workspace_name: 'default' })
  const [parallelForm, setParallelForm] = useState({ repo_path: '', branch: '', workspace_name: '', target_path: '' })
  
  // Workspace-specific fetched data
  const [timeline, setTimeline] = useState<TimelineEvent[]>([])
  const [progress, setProgress] = useState<ProgressRecord[]>([])
  const [treeData, setTreeData] = useState<TreeData>({ tree_enabled: false, nodes: [], root: null })
  const [preflight, setPreflight] = useState<PreflightData | null>(null)
  
  // Configuration tab state
  const [configYaml, setConfigYaml] = useState('')
  const [isRawConfigEdit, setIsRawConfigEdit] = useState(false)
  const [wizardForm, setWizardForm] = useState({
    build_cmd: '',
    fast_model: '',
    normal_model: '',
    thinking_model: '',
    mode: 'gated'
  })
  
  // Diagnostics tab states
  const [logType, setLogType] = useState<'loop' | 'plan'>('loop')
  const [logLines, setLogLines] = useState<string[]>([])
  const [rawState, setRawState] = useState<string>('')
  const [gitDiff, setGitDiff] = useState<string>('')
  const [activeDiagnosticsSubTab, setActiveDiagnosticsSubTab] = useState<'logs' | 'state' | 'diff'>('logs')
  
  // SSE Event Source reference
  const sseRef = useRef<EventSource | null>(null)
  const logTerminalEndRef = useRef<HTMLDivElement | null>(null)

  // Fetch workspaces list
  const fetchWorkspaces = async () => {
    try {
      const res = await fetch('/api/workspaces')
      if (res.ok) {
        const data = await res.json()
        setWorkspaces(data)
      }
    } catch (e) {
      console.error("Error fetching workspaces", e)
    }
  }

  // Poll workspaces list globally
  useEffect(() => {
    fetchWorkspaces()
    const interval = setInterval(fetchWorkspaces, 4000)
    return () => clearInterval(interval)
  }, [])

  // Poll selected workspace detail, timeline, progress, and tree when active
  useEffect(() => {
    if (!activeWorkspaceId) {
      setActiveWorkspace(null)
      setTimeline([])
      setProgress([])
      setTreeData({ tree_enabled: false, nodes: [], root: null })
      setPreflight(null)
      return
    }

    const fetchWorkspaceDetails = async () => {
      try {
        const [overviewRes, timelineRes, progressRes, treeRes, preflightRes] = await Promise.all([
          fetch(`/api/workspaces/${activeWorkspaceId}/overview`),
          fetch(`/api/workspaces/${activeWorkspaceId}/timeline?limit=50`),
          fetch(`/api/workspaces/${activeWorkspaceId}/progress?limit=100`),
          fetch(`/api/workspaces/${activeWorkspaceId}/tree`),
          fetch(`/api/workspaces/${activeWorkspaceId}/preflight`)
        ])

        if (overviewRes.ok) setActiveWorkspace(await overviewRes.json())
        if (timelineRes.ok) setTimeline(await timelineRes.json())
        if (progressRes.ok) setProgress(await progressRes.json())
        if (treeRes.ok) setTreeData(await treeRes.json())
        if (preflightRes.ok) setPreflight(await preflightRes.json())
      } catch (e) {
        console.error("Error polling workspace details", e)
      }
    }

    fetchWorkspaceDetails()
    const interval = setInterval(fetchWorkspaceDetails, 3000)
    return () => clearInterval(interval)
  }, [activeWorkspaceId])

  // Load config when configuration tab is opened
  useEffect(() => {
    if (activeWorkspaceId && activeTab === 'config') {
      loadConfig()
    }
  }, [activeWorkspaceId, activeTab])

  // Load diagnostics (state, diff) when diagnostics tab is opened
  useEffect(() => {
    if (activeWorkspaceId && activeTab === 'diagnostics') {
      loadDiagnostics()
    }
  }, [activeWorkspaceId, activeTab, activeDiagnosticsSubTab])

  // Set up SSE Log stream
  useEffect(() => {
    if (activeWorkspaceId && activeTab === 'diagnostics' && activeDiagnosticsSubTab === 'logs') {
      startLogStream()
    } else {
      stopLogStream()
    }
    return () => stopLogStream()
  }, [activeWorkspaceId, activeTab, activeDiagnosticsSubTab, logType])

  // Auto-scroll logs terminal
  useEffect(() => {
    if (logTerminalEndRef.current) {
      logTerminalEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logLines])

  const loadConfig = async () => {
    try {
      const res = await fetch(`/api/workspaces/${activeWorkspaceId}/config`)
      if (res.ok) {
        const data = await res.json()
        setConfigYaml(data.content)
        
        // Try parsing YAML to pre-populate wizard fields
        try {
          // Simple regex-based YAML property extract to avoid external parser package issues
          const content = data.content
          const buildCmd = content.match(/build_cmd\s*:\s*([^\n#\r]+)/)?.[1]?.trim().replace(/^['"]|['"]$/g, '') || ''
          const fastModel = content.match(/fast\s*:\s*([^\n#\r]+)/)?.[1]?.trim().replace(/^['"]|['"]$/g, '') || ''
          const normalModel = content.match(/normal\s*:\s*([^\n#\r]+)/)?.[1]?.trim().replace(/^['"]|['"]$/g, '') || ''
          const thinkingModel = content.match(/thinking\s*:\s*([^\n#\r]+)/)?.[1]?.trim().replace(/^['"]|['"]$/g, '') || ''
          const genMode = content.match(/mode\s*:\s*([^\n#\r]+)/)?.[1]?.trim().replace(/^['"]|['"]$/g, '') || 'gated'
          
          setWizardForm({
            build_cmd: buildCmd,
            fast_model: fastModel,
            normal_model: normalModel,
            thinking_model: thinkingModel,
            mode: genMode === 'auto' ? 'auto' : 'gated'
          })
        } catch (e) {
          console.warn("Could not pre-populate wizard fields from YAML", e)
        }
      }
    } catch (e) {
      console.error("Failed to load config", e)
    }
  }

  const loadDiagnostics = async () => {
    if (!activeWorkspaceId) return
    try {
      if (activeDiagnosticsSubTab === 'state') {
        const res = await fetch(`/api/workspaces/${activeWorkspaceId}/diagnostics`)
        if (res.ok) {
          const data = await res.json()
          setRawState(JSON.stringify(data.raw_state, null, 2))
        }
      } else if (activeDiagnosticsSubTab === 'diff') {
        const res = await fetch(`/api/workspaces/${activeWorkspaceId}/diff`)
        if (res.ok) {
          const data = await res.json()
          setGitDiff(data.diff || "No open modifications. Workspace Git directory is clean.")
        }
      }
    } catch (e) {
      console.error("Error loading diagnostics", e)
    }
  }

  const startLogStream = () => {
    stopLogStream()
    setLogLines(["Connecting to log stream..."])
    
    // Server-Sent Events
    const source = new EventSource(`/api/workspaces/${activeWorkspaceId}/logs/${logType}?tail=300`)
    sseRef.current = source
    
    source.onmessage = (event) => {
      const line = event.data
      if (line === "--- end of history (live) ---") {
        setLogLines(prev => [...prev, "--- Log live connection established ---"])
      } else {
        setLogLines(prev => {
          // Limit buffered log lines in UI to avoid browser crashing (e.g. max 1000 lines)
          const current = [...prev, line]
          if (current.length > 1000) {
            return current.slice(current.length - 1000)
          }
          return current
        })
      }
    }
    
    source.onerror = (e) => {
      console.error("SSE connection error", e)
      setLogLines(prev => [...prev, "⚠️ Connection lost. Retrying..."])
    }
  }

  const stopLogStream = () => {
    if (sseRef.current) {
      sseRef.current.close()
      sseRef.current = null
    }
  }

  // Notification helper
  const flashSuccess = (msg: string) => {
    setSuccessMsg(msg)
    setTimeout(() => setSuccessMsg(null), 5000)
  }

  const flashError = (msg: string) => {
    setErrorMsg(msg)
    setTimeout(() => setErrorMsg(null), 6000)
  }

  // Core actions
  const handleStart = async (id: string, mode: string = 'auto') => {
    setLoading(true)
    try {
      const res = await fetch(`/api/workspaces/${id}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, stage: 'all' })
      })
      if (res.ok) {
        flashSuccess("Automated Loop Engine spawned successfully!")
        fetchWorkspaces()
      } else {
        const error = await res.json()
        flashError(error.detail || "Failed to start workspace")
      }
    } catch (e) {
      flashError("Network connection error")
    } finally {
      setLoading(false)
    }
  }

  const handleStop = async (id: string) => {
    setLoading(true)
    try {
      const res = await fetch(`/api/workspaces/${id}/stop`, {
        method: 'POST'
      })
      if (res.ok) {
        flashSuccess("Force stopped running process tree.")
        fetchWorkspaces()
      } else {
        const error = await res.json()
        flashError(error.detail || "Failed to stop workspace")
      }
    } catch (e) {
      flashError("Network connection error")
    } finally {
      setLoading(false)
    }
  }

  const handleResume = async (id: string) => {
    setLoading(true)
    try {
      const res = await fetch(`/api/workspaces/${id}/resume`, {
        method: 'POST'
      })
      if (res.ok) {
        flashSuccess("Workspace resumed successfully after input confirmation.")
        fetchWorkspaces()
      } else {
        const error = await res.json()
        flashError(error.detail || "Failed to resume workspace")
      }
    } catch (e) {
      flashError("Network connection error")
    } finally {
      setLoading(false)
    }
  }

  const handleClearLock = async (id: string) => {
    if (!confirm("Are you sure you want to force-delete the run.lock file? Use this only if the loop process crashed and left a stale lock.")) return
    try {
      const res = await fetch(`/api/workspaces/${id}/clear-lock`, { method: 'POST' })
      if (res.ok) {
        flashSuccess("Lock file cleared successfully.")
        fetchWorkspaces()
      } else {
        const error = await res.json()
        flashError(error.detail || "Failed to clear lock")
      }
    } catch (e) {
      flashError("Network connection error")
    }
  }

  const handleResetPlan = async (id: string) => {
    if (!confirm("Are you sure you want to reset all planning progress? This will clear current plan, phases, and delete files under phases/, then spawn the planning loop again.")) return
    setLoading(true)
    try {
      const res = await fetch(`/api/workspaces/${id}/reset-plan`, { method: 'POST' })
      if (res.ok) {
        flashSuccess("Workspace plan reset and planning loop spawned successfully!")
        fetchWorkspaces()
      } else {
        const error = await res.json()
        flashError(error.detail || "Failed to reset workspace plan")
      }
    } catch (e) {
      flashError("Network connection error")
    } finally {
      setLoading(false)
    }
  }

  const handleResetExecute = async (id: string) => {
    if (!confirm("Reset execute-state for this workspace? This keeps the generated plan, but rewinds execution progress so the agent can run again from the selected point.")) return

    const rawPhase = prompt("Optional: reset from which phase? Leave blank to reset all execute progress.", "")
    if (rawPhase === null) return
    const resetToPhase = rawPhase.trim()

    let resetToTask = ''
    if (resetToPhase) {
      const rawTask = prompt("Optional: reset from which task inside that phase? Leave blank to reset the whole phase onward.", "")
      if (rawTask === null) return
      resetToTask = rawTask.trim()
    }

    setLoading(true)
    try {
      const res = await fetch(`/api/workspaces/${id}/reset-execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reset_to_phase: resetToPhase || null,
          reset_to_task: resetToTask || null
        })
      })
      if (res.ok) {
        const data = await res.json()
        const scope = data.reset_to_task
          ? `phase ${data.reset_to_phase}, task ${data.reset_to_task}`
          : data.reset_to_phase
            ? `phase ${data.reset_to_phase}`
            : 'the beginning'
        flashSuccess(`Execution state reset from ${scope}. Start the engine again when you're ready.`)
        fetchWorkspaces()
      } else {
        const error = await res.json()
        flashError(error.detail || "Failed to reset execute state")
      }
    } catch (e) {
      flashError("Network connection error")
    } finally {
      setLoading(false)
    }
  }

  const handleUntrack = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm("Remove this workspace from the Dashboard track index? This does not delete any files on your disk.")) return
    try {
      const res = await fetch(`/api/workspaces/${id}`, { method: 'DELETE' })
      if (res.ok) {
        flashSuccess("Workspace untracked.")
        if (activeWorkspaceId === id) setActiveWorkspaceId(null)
        fetchWorkspaces()
      } else {
        const error = await res.json()
        flashError(error.detail || "Failed to untrack")
      }
    } catch (e) {
      flashError("Network connection error")
    }
  }

  // Setup / Track Forms submissions
  const handleInitSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const res = await fetch('/api/workspaces/init', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(initForm)
      })
      if (res.ok) {
        flashSuccess(`Workspace [${initForm.workspace_name}] successfully initialized!`)
        setShowInitModal(false)
        setInitForm({ repo_path: '', workspace_name: 'default' })
        fetchWorkspaces()
      } else {
        const err = await res.json()
        flashError(err.detail || "Failed to initialize workspace.")
      }
    } catch (e) {
      flashError("Network connection failure.")
    } finally {
      setLoading(false)
    }
  }

  const handleTrackSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const res = await fetch('/api/workspaces/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(trackForm)
      })
      if (res.ok) {
        flashSuccess("Existing workspace tracked successfully!")
        setShowTrackModal(false)
        setTrackForm({ repo_path: '', workspace_name: 'default' })
        fetchWorkspaces()
      } else {
        const err = await res.json()
        flashError(err.detail || "Workspace not found or not initialized.")
      }
    } catch (e) {
      flashError("Network connection failure.")
    } finally {
      setLoading(false)
    }
  }

  const handleParallelSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const res = await fetch('/api/parallel/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo_path: parallelForm.repo_path,
          branch: parallelForm.branch,
          workspace_name: parallelForm.workspace_name || null,
          target_path: parallelForm.target_path || null
        })
      })
      if (res.ok) {
        flashSuccess("Parallel Git worktree + work branch created and tracked!");
        setShowParallelModal(false)
        setParallelForm({ repo_path: '', branch: '', workspace_name: '', target_path: '' })
        fetchWorkspaces()
      } else {
        const err = await res.json()
        flashError(err.detail || "Failed to establish parallel worktree.")
      }
    } catch (e) {
      flashError("Network connection failure.")
    } finally {
      setLoading(false)
    }
  }

  const handleConfigSave = async () => {
    setLoading(true)
    try {
      const res = await fetch(`/api/workspaces/${activeWorkspaceId}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: configYaml })
      })
      if (res.ok) {
        flashSuccess("YAML configuration validated and saved successfully.")
        setIsRawConfigEdit(false)
        loadConfig()
      } else {
        const err = await res.json()
        flashError(err.detail || "Config contains syntax errors")
      }
    } catch (e) {
      flashError("Network error while saving configuration")
    } finally {
      setLoading(false)
    }
  }

  const handleConfigWizardSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const res = await fetch(`/api/workspaces/${activeWorkspaceId}/config-wizard`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          build_cmd: wizardForm.build_cmd,
          fast_model: wizardForm.fast_model,
          normal_model: wizardForm.normal_model,
          thinking_model: wizardForm.thinking_model,
          mode: wizardForm.mode
        })
      })
      if (res.ok) {
        flashSuccess("Configuration Wizard applied successfully.")
        loadConfig()
      } else {
        const err = await res.json()
        flashError(err.detail || "Failed to update configuration")
      }
    } catch (e) {
      flashError("Network connection error")
    } finally {
      setLoading(false)
    }
  }

  const handleRejectNode = async (nodeId: string) => {
    if (!confirm(`Are you sure you want to reject node [${nodeId}]? This will halt running execution, prune this subtree and trigger a replan phase.`)) return
    try {
      const res = await fetch(`/api/workspaces/${activeWorkspaceId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subtree_id: nodeId })
      })
      if (res.ok) {
        flashSuccess(`Node [${nodeId}] rejected successfully. Replan process spawned.`)
        setActiveTab('overview')
      } else {
        const err = await res.json()
        flashError(err.detail || "Failed to reject subtree.")
      }
    } catch (e) {
      flashError("Network connection failure.")
    }
  }

  // Group workspaces by category
  const groupedWorkspaces = {
    human_required: workspaces.filter(w => w.status === 'human_required'),
    running: workspaces.filter(w => w.status === 'running'),
    stalled: workspaces.filter(w => w.status === 'idle' && w.direction === 'stalled'),
    progressed: workspaces.filter(w => w.status === 'idle' && w.direction === 'forward'),
    complete: workspaces.filter(w => w.status === 'completed'),
    idle: workspaces.filter(w => w.status === 'idle' && w.direction !== 'stalled' && w.direction !== 'forward')
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Top Cockpit Header */}
      <header className="bg-slate-900 border-b border-slate-800 px-6 py-4 flex justify-between items-center shadow-lg">
        <div className="flex items-center space-x-3">
          <Layers className="h-8 w-8 text-indigo-400 animate-pulse" />
          <div>
            <h1 className="text-xl font-bold tracking-tight text-white m-0">Loop Engineering Cockpit</h1>
            <p className="text-xs text-slate-400">Robust Multi-Workspace Automation & Progress Terminal</p>
          </div>
        </div>
        <div className="flex items-center space-x-3 text-sm">
          {workspaces.some(w => w.status === 'running') && (
            <span className="flex items-center space-x-1.5 px-3 py-1 bg-emerald-950 text-emerald-400 rounded-full border border-emerald-800 text-xs font-semibold animate-pulse">
              <span className="h-2 w-2 rounded-full bg-emerald-400"></span>
              <span>Loop Active</span>
            </span>
          )}
          <span className="text-slate-500">System Time: {new Date().toLocaleTimeString()}</span>
        </div>
      </header>

      {/* Global Notifications Alert Banner */}
      {successMsg && (
        <div className="bg-emerald-900/80 text-emerald-200 border-b border-emerald-700 px-6 py-3 text-sm flex items-center space-x-2 transition-all">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
          <span className="font-medium">{successMsg}</span>
        </div>
      )}
      {errorMsg && (
        <div className="bg-rose-950/90 text-rose-200 border-b border-rose-800 px-6 py-3 text-sm flex items-center space-x-2 transition-all">
          <AlertCircle className="h-4 w-4 shrink-0 text-rose-400" />
          <span className="font-medium">{errorMsg}</span>
        </div>
      )}

      {/* Main Layout Area */}
      <main className="flex-1 flex overflow-hidden">
        {activeWorkspaceId === null ? (
          // ================= GLOBAL HOME SCREEN =================
          <div className="flex-1 p-8 overflow-y-auto max-w-7xl mx-auto w-full space-y-8">
            <div className="flex justify-between items-center">
              <div>
                <h2 className="text-2xl font-bold text-white mb-1">Workspace Cockpit Summary</h2>
                <p className="text-slate-400 text-sm">Monitor, deploy, and inspect active requirements validation loops</p>
              </div>
              <div className="flex space-x-3">
                <button 
                  onClick={() => setShowInitModal(true)}
                  className="flex items-center space-x-1.5 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 text-white rounded-lg text-sm font-semibold shadow-md transition-colors"
                >
                  <Plus className="h-4 w-4" />
                  <span>Init Workspace</span>
                </button>
                <button 
                  onClick={() => setShowTrackModal(true)}
                  className="flex items-center space-x-1.5 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-sm font-semibold border border-slate-700 shadow-sm transition-colors"
                >
                  <FolderOpen className="h-4 w-4" />
                  <span>Track Existing</span>
                </button>
                <button 
                  onClick={() => setShowParallelModal(true)}
                  className="flex items-center space-x-1.5 px-4 py-2 bg-emerald-700 hover:bg-emerald-600 active:bg-emerald-800 text-white rounded-lg text-sm font-semibold shadow-md transition-colors"
                >
                  <GitBranch className="h-4 w-4" />
                  <span>Parallel Worktree</span>
                </button>
              </div>
            </div>

            {/* Empty State */}
            {workspaces.length === 0 && (
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-16 text-center max-w-xl mx-auto space-y-6 shadow-xl">
                <Layers className="h-16 w-16 text-slate-600 mx-auto" />
                <div className="space-y-2">
                  <h3 className="text-xl font-bold text-white">No Workspaces Tracked</h3>
                  <p className="text-slate-400 text-sm">Deploy a new requirements convergence loop or import an existing `.loop/` configuration directory to begin monitoring.</p>
                </div>
                <div className="flex flex-col sm:flex-row justify-center gap-3">
                  <button onClick={() => setShowInitModal(true)} className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 rounded-lg font-semibold text-sm transition-all shadow-md">
                    Initialize New Repository
                  </button>
                  <button onClick={() => setShowTrackModal(true)} className="px-5 py-2.5 bg-slate-800 hover:bg-slate-750 border border-slate-700 rounded-lg font-semibold text-sm text-slate-200 transition-all">
                    Track Existing Workspace
                  </button>
                </div>
              </div>
            )}

            {/* Workspaces Groups */}
            {workspaces.length > 0 && (
              <div className="space-y-8">
                {/* Needs Attention / Human Required */}
                {groupedWorkspaces.human_required.length > 0 && (
                  <div className="space-y-3">
                    <h3 className="text-sm font-bold uppercase tracking-wider text-rose-400 flex items-center space-x-2">
                      <span className="h-2 w-2 rounded-full bg-rose-500 animate-ping"></span>
                      <span>Requires Human Input ({groupedWorkspaces.human_required.length})</span>
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                      {groupedWorkspaces.human_required.map(w => renderWorkspaceCard(w))}
                    </div>
                  </div>
                )}

                {/* Running */}
                {groupedWorkspaces.running.length > 0 && (
                  <div className="space-y-3">
                    <h3 className="text-sm font-bold uppercase tracking-wider text-emerald-400 flex items-center space-x-2">
                      <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
                      <span>Running Loops ({groupedWorkspaces.running.length})</span>
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                      {groupedWorkspaces.running.map(w => renderWorkspaceCard(w))}
                    </div>
                  </div>
                )}

                {/* Stalled / Regressing */}
                {groupedWorkspaces.stalled.length > 0 && (
                  <div className="space-y-3">
                    <h3 className="text-sm font-bold uppercase tracking-wider text-amber-500 flex items-center space-x-2">
                      <AlertTriangle className="h-4 w-4" />
                      <span>Stalled or Regressing ({groupedWorkspaces.stalled.length})</span>
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                      {groupedWorkspaces.stalled.map(w => renderWorkspaceCard(w))}
                    </div>
                  </div>
                )}

                {/* Progressed */}
                {groupedWorkspaces.progressed.length > 0 && (
                  <div className="space-y-3">
                    <h3 className="text-sm font-bold uppercase tracking-wider text-indigo-400 flex items-center space-x-2">
                      <Sparkles className="h-4 w-4" />
                      <span>Recently Progressed ({groupedWorkspaces.progressed.length})</span>
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                      {groupedWorkspaces.progressed.map(w => renderWorkspaceCard(w))}
                    </div>
                  </div>
                )}

                {/* Completed */}
                {groupedWorkspaces.complete.length > 0 && (
                  <div className="space-y-3">
                    <h3 className="text-sm font-bold uppercase tracking-wider text-teal-400 flex items-center space-x-2">
                      <CheckCircle2 className="h-4 w-4" />
                      <span>Complete ({groupedWorkspaces.complete.length})</span>
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                      {groupedWorkspaces.complete.map(w => renderWorkspaceCard(w))}
                    </div>
                  </div>
                )}

                {/* Idle / Not Started */}
                {groupedWorkspaces.idle.length > 0 && (
                  <div className="space-y-3">
                    <h3 className="text-sm font-bold uppercase tracking-wider text-slate-400 flex items-center space-x-2">
                      <Layers className="h-4 w-4" />
                      <span>Idle / Not Started ({groupedWorkspaces.idle.length})</span>
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                      {groupedWorkspaces.idle.map(w => renderWorkspaceCard(w))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ) : (
          // ================= WORKSPACE COCKPIT VIEWER =================
          <div className="flex-1 flex flex-col overflow-hidden bg-slate-950">
            {/* Workspace Control Bar */}
            <div className="bg-slate-900 border-b border-slate-800 px-6 py-3.5 flex flex-wrap justify-between items-center gap-4">
              <div className="flex items-center space-x-4">
                <button 
                  onClick={() => { setActiveWorkspaceId(null); stopLogStream(); }}
                  className="p-2 hover:bg-slate-800 rounded-lg text-slate-400 hover:text-white transition-colors"
                  title="Back to Summary"
                >
                  <ArrowLeft className="h-5 w-5" />
                </button>
                <div>
                  <div className="flex items-center space-x-2">
                    <h2 className="text-lg font-bold text-white leading-none m-0">{activeWorkspace?.repo_name}</h2>
                    <span className="px-2 py-0.5 bg-slate-800 text-slate-300 rounded text-xs border border-slate-700 font-mono">
                      {activeWorkspace?.workspace}
                    </span>
                    <span className="px-2 py-0.5 bg-indigo-950 text-indigo-400 rounded text-xs border border-indigo-900 font-semibold capitalize">
                      {activeWorkspace?.mode} Mode
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 mt-1 font-mono break-all">{activeWorkspace?.repo}</p>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center space-x-2.5">
                {preflight && !preflight.ok && (
                  <span className="text-amber-500 text-xs flex items-center space-x-1 mr-2 px-2 py-1 bg-amber-950/40 rounded border border-amber-800/40">
                    <AlertTriangle className="h-3.5 w-3.5" />
                    <span>Config Missing/Placeholders</span>
                  </span>
                )}
                
                {activeWorkspace?.status === 'running' ? (
                  <button 
                    onClick={() => handleStop(activeWorkspace.id)}
                    disabled={loading}
                    className="flex items-center space-x-1.5 px-4 py-2 bg-rose-700 hover:bg-rose-600 disabled:opacity-50 text-white rounded-lg text-sm font-semibold shadow transition-colors"
                  >
                    <Square className="h-4 w-4 fill-white" />
                    <span>Force Stop</span>
                  </button>
                ) : activeWorkspace?.status === 'human_required' ? (
                  <button 
                    onClick={() => handleResume(activeWorkspace.id)}
                    disabled={loading}
                    className="flex items-center space-x-1.5 px-4 py-2 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white rounded-lg text-sm font-semibold shadow transition-colors"
                  >
                    <RotateCcw className="h-4 w-4" />
                    <span>Resume Loop</span>
                  </button>
                ) : (
                  <button 
                    onClick={() => handleStart(activeWorkspace!.id, 'auto')}
                    disabled={loading || (preflight !== null && !preflight.ok)}
                    className="flex items-center space-x-1.5 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg text-sm font-semibold shadow transition-colors"
                  >
                    <Play className="h-4 w-4 fill-white" />
                    <span>Start Engine</span>
                  </button>
                )}

                {activeWorkspace?.run.is_running === false && (
                  <button 
                    onClick={() => handleClearLock(activeWorkspace!.id)}
                    className="p-2 hover:bg-slate-800 rounded-lg text-slate-500 hover:text-rose-400 transition-colors border border-transparent hover:border-slate-700"
                    title="Clear lock file manually"
                  >
                    <RotateCcw className="h-4 w-4" />
                  </button>
                )}

                {activeWorkspace?.status !== 'running' && (
                  <>
                    <button 
                      onClick={() => handleResetExecute(activeWorkspace!.id)}
                      disabled={loading}
                      className="flex items-center space-x-1.5 px-3 py-2 bg-slate-850 hover:bg-slate-800 disabled:opacity-50 text-slate-300 hover:text-white rounded-lg text-sm font-semibold border border-slate-700 transition-colors"
                      title="Reset execute-state and keep the generated plan"
                    >
                      <RotateCcw className="h-4 w-4 text-slate-400" />
                      <span>Reset Execute</span>
                    </button>
                    <button 
                      onClick={() => handleResetPlan(activeWorkspace!.id)}
                      disabled={loading}
                      className="flex items-center space-x-1.5 px-3 py-2 bg-slate-850 hover:bg-slate-800 disabled:opacity-50 text-slate-300 hover:text-white rounded-lg text-sm font-semibold border border-slate-700 transition-colors"
                      title="Reset planning progress and restart planning"
                    >
                      <RotateCcw className="h-4 w-4 text-slate-400" />
                      <span>Reset Plan</span>
                    </button>
                  </>
                )}
              </div>
            </div>

            {/* Inner Dashboard Tabs Navigation */}
            <div className="bg-slate-900 border-b border-slate-800 px-6 flex justify-between items-center shrink-0">
              <div className="flex space-x-6">
                {[
                  { id: 'overview', label: 'Progress Cockpit', icon: Activity },
                  { id: 'tree', label: 'Task Map Tree', icon: GitBranch, disabled: activeWorkspace?.mode !== 'tree' },
                  { id: 'config', label: 'Configuration', icon: Settings },
                  { id: 'diagnostics', label: 'Diagnostics Drawer', icon: Terminal }
                ].map(tab => {
                  const Icon = tab.icon
                  const active = activeTab === tab.id
                  if (tab.disabled) return null
                  return (
                    <button
                      key={tab.id}
                      onClick={() => setActiveTab(tab.id as any)}
                      className={`py-3 px-1 border-b-2 font-semibold text-sm flex items-center space-x-2 transition-all ${
                        active 
                          ? 'border-indigo-500 text-indigo-400' 
                          : 'border-transparent text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      <Icon className="h-4 w-4" />
                      <span>{tab.label}</span>
                    </button>
                  )
                })}
              </div>
              <div className="text-xs text-slate-400 flex items-center space-x-2">
                <span className={`h-2.5 w-2.5 rounded-full ${getStatusColor(activeWorkspace?.status)}`}></span>
                <span className="capitalize font-semibold text-slate-300">Status: {activeWorkspace?.status.replace('_', ' ')}</span>
                <span className="text-slate-600">|</span>
                <span className="font-semibold text-slate-300">Trend:</span>
                <span className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-bold ${getDirectionColor(activeWorkspace?.direction)}`}>
                  {activeWorkspace?.direction}
                </span>
              </div>
            </div>

            {/* Tab Contents View */}
            <div className="flex-1 overflow-hidden flex">
              {activeTab === 'overview' && renderOverviewTab()}
              {activeTab === 'tree' && renderTreeTab()}
              {activeTab === 'config' && renderConfigTab()}
              {activeTab === 'diagnostics' && renderDiagnosticsTab()}
            </div>
          </div>
        )}
      </main>

      {/* ================= MODAL DIALOGS ================= */}
      {showInitModal && (
        <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm flex justify-center items-center z-50 p-4">
          <form onSubmit={handleInitSubmit} className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-md p-6 space-y-4 shadow-2xl">
            <h3 className="text-xl font-bold text-white flex items-center space-x-2">
              <Plus className="h-5 w-5 text-indigo-400" />
              <span>Initialize Workspace</span>
            </h3>
            <p className="text-slate-400 text-sm">Establish a new `.loop/` requirements monitoring directory structure on an existing codebase.</p>
            <div className="space-y-3">
              <div className="space-y-1">
                <label className="block text-xs font-bold text-slate-300 uppercase tracking-wide">Repository Folder Path</label>
                <input 
                  type="text" 
                  value={initForm.repo_path}
                  onChange={e => setInitForm({...initForm, repo_path: e.target.value})}
                  placeholder="e.g. C:\Users\yuting\IdeaProjects\my-project"
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>
              <div className="space-y-1">
                <label className="block text-xs font-bold text-slate-300 uppercase tracking-wide">Workspace Name</label>
                <input 
                  type="text" 
                  value={initForm.workspace_name}
                  onChange={e => setInitForm({...initForm, workspace_name: e.target.value})}
                  placeholder="default"
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>
            </div>
            <div className="flex justify-end space-x-3 pt-2">
              <button 
                type="button" 
                onClick={() => setShowInitModal(false)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-slate-300 text-sm font-semibold transition-colors"
              >
                Cancel
              </button>
              <button 
                type="submit"
                disabled={loading}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded-lg text-white text-sm font-semibold transition-colors shadow-md flex items-center space-x-1"
              >
                {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                <span>Initialize</span>
              </button>
            </div>
          </form>
        </div>
      )}

      {showTrackModal && (
        <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm flex justify-center items-center z-50 p-4">
          <form onSubmit={handleTrackSubmit} className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-md p-6 space-y-4 shadow-2xl">
            <h3 className="text-xl font-bold text-white flex items-center space-x-2">
              <FolderOpen className="h-5 w-5 text-indigo-400" />
              <span>Track Existing Workspace</span>
            </h3>
            <p className="text-slate-400 text-sm">Add an already initialized loop environment directory to the dashboard console tracking registry.</p>
            <div className="space-y-3">
              <div className="space-y-1">
                <label className="block text-xs font-bold text-slate-300 uppercase tracking-wide">Repository Folder Path</label>
                <input 
                  type="text" 
                  value={trackForm.repo_path}
                  onChange={e => setTrackForm({...trackForm, repo_path: e.target.value})}
                  placeholder="e.g. C:\Users\yuting\IdeaProjects\my-project"
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>
              <div className="space-y-1">
                <label className="block text-xs font-bold text-slate-300 uppercase tracking-wide">Workspace Name</label>
                <input 
                  type="text" 
                  value={trackForm.workspace_name}
                  onChange={e => setTrackForm({...trackForm, workspace_name: e.target.value})}
                  placeholder="default"
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>
            </div>
            <div className="flex justify-end space-x-3 pt-2">
              <button 
                type="button" 
                onClick={() => setShowTrackModal(false)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-slate-300 text-sm font-semibold transition-colors"
              >
                Cancel
              </button>
              <button 
                type="submit"
                disabled={loading}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded-lg text-white text-sm font-semibold transition-colors shadow-md flex items-center space-x-1"
              >
                {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                <span>Track</span>
              </button>
            </div>
          </form>
        </div>
      )}

      {showParallelModal && (
        <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm flex justify-center items-center z-50 p-4">
          <form onSubmit={handleParallelSubmit} className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-md p-6 space-y-4 shadow-2xl">
            <h3 className="text-xl font-bold text-white flex items-center space-x-2">
              <GitBranch className="h-5 w-5 text-indigo-400" />
              <span>Parallel Worktree Creation</span>
            </h3>
            <p className="text-slate-400 text-sm">Deploy an isolated Git worktree and work branch to concurrently run multiple independent validation cycles.</p>
            <div className="space-y-3">
              <div className="space-y-1">
                <label className="block text-xs font-bold text-slate-300 uppercase tracking-wide">Base Git Repository Path</label>
                <input 
                  type="text" 
                  value={parallelForm.repo_path}
                  onChange={e => setParallelForm({...parallelForm, repo_path: e.target.value})}
                  placeholder="e.g. C:\Users\yuting\IdeaProjects\main-repo"
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>
              <div className="space-y-1">
                <label className="block text-xs font-bold text-slate-300 uppercase tracking-wide">Branch Name (New or Existing)</label>
                <input 
                  type="text" 
                  value={parallelForm.branch}
                  onChange={e => setParallelForm({...parallelForm, branch: e.target.value})}
                  placeholder="e.g. feature/my-new-task"
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>
              <div className="space-y-1">
                <label className="block text-xs font-bold text-slate-300 uppercase tracking-wide">Workspace Name (Optional)</label>
                <input 
                  type="text" 
                  value={parallelForm.workspace_name}
                  onChange={e => setParallelForm({...parallelForm, workspace_name: e.target.value})}
                  placeholder="If omitted, sanitized branch is used"
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                />
              </div>
              <div className="space-y-1">
                <label className="block text-xs font-bold text-slate-300 uppercase tracking-wide">Target Path (Optional sibling directory)</label>
                <input 
                  type="text" 
                  value={parallelForm.target_path}
                  onChange={e => setParallelForm({...parallelForm, target_path: e.target.value})}
                  placeholder="If omitted, placed under base_repo/../sibling"
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                />
              </div>
            </div>
            <div className="flex justify-end space-x-3 pt-2">
              <button 
                type="button" 
                onClick={() => setShowParallelModal(false)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-slate-300 text-sm font-semibold transition-colors"
              >
                Cancel
              </button>
              <button 
                type="submit"
                disabled={loading}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded-lg text-white text-sm font-semibold transition-colors shadow-md flex items-center space-x-1"
              >
                {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                <span>Deploy Worktree</span>
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )

  // ================= RENDER CARD COMPONENT =================
  function renderWorkspaceCard(w: Workspace) {
    const isRunning = w.status === 'running'
    return (
      <div 
        key={w.id}
        onClick={() => { setActiveWorkspaceId(w.id); setActiveTab('overview'); }}
        className="bg-slate-900/90 hover:bg-slate-900 border border-slate-800 hover:border-slate-700 rounded-xl p-5 cursor-pointer shadow-md hover:shadow-lg transition-all group relative overflow-hidden flex flex-col justify-between min-h-[190px]"
      >
        {/* Glow progress bar for running loop */}
        {isRunning && <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-indigo-500 via-emerald-400 to-indigo-500 animate-pulse"></div>}

        <div className="space-y-3">
          <div className="flex justify-between items-start">
            <div className="space-y-0.5">
              <h4 className="text-white font-bold group-hover:text-indigo-400 transition-colors m-0 text-base">{w.repo_name}</h4>
              <span className="inline-block px-1.5 py-0.5 bg-slate-800 text-slate-400 rounded text-[10px] font-mono border border-slate-700 mt-1">
                {w.workspace}
              </span>
            </div>
            <div className="flex items-center space-x-2">
              <span className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider ${getDirectionColor(w.direction)}`}>
                {w.direction}
              </span>
              <button 
                onClick={(e) => handleUntrack(w.id, e)}
                className="p-1 text-slate-500 hover:text-rose-400 rounded transition-colors opacity-0 group-hover:opacity-100"
                title="Untrack Workspace"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="space-y-1">
            <p className="text-xs text-white font-semibold line-clamp-1">{w.headline}</p>
            <p className="text-slate-400 text-xs line-clamp-2">{w.why || "Idle workspace. Waiting to execute validation round."}</p>
          </div>
        </div>

        <div className="border-t border-slate-800/80 pt-3 mt-3 flex justify-between items-center text-[11px] text-slate-500">
          <div className="flex items-center space-x-1.5 font-semibold text-slate-400">
            <Layers className="h-3.5 w-3.5" />
            <span>Phase {w.current.phase || "1"}</span>
            {w.current.active_leaf && (
              <>
                <span className="text-slate-700">•</span>
                <span className="text-emerald-400 font-mono text-[10px]">[{w.current.active_leaf}]</span>
              </>
            )}
          </div>
          <span>{w.updated_at ? w.updated_at.split(' ')[1] : ''}</span>
        </div>
      </div>
    )
  }

  // ================= TAB COMPONENT: PROGRESS COCKPIT (OVERVIEW) =================
  function renderOverviewTab() {
    if (!activeWorkspace) return null

    const status = activeWorkspace.status
    const nextAction = activeWorkspace.next_action

    return (
      <div className="flex-1 flex overflow-hidden">
        {/* Left Side: Overview & Charts */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Answer Card */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-md relative overflow-hidden">
            <div className={`absolute left-0 top-0 bottom-0 w-1.5 ${
              status === 'running' ? 'bg-emerald-500' :
              status === 'human_required' ? 'bg-amber-500' :
              status === 'completed' ? 'bg-indigo-500' : 'bg-slate-700'
            }`}></div>
            <div className="space-y-4">
              <div>
                <span className="text-xs font-bold uppercase tracking-wide text-indigo-400">Current Status Summary</span>
                <h3 className="text-2xl font-bold text-white mt-1 leading-tight">{activeWorkspace.headline}</h3>
                <p className="text-slate-300 text-sm mt-2 leading-relaxed">{activeWorkspace.why}</p>
              </div>
              
              <div className="border-t border-slate-850 pt-4 flex flex-wrap gap-x-8 gap-y-3 text-xs text-slate-400 font-semibold">
                <div>
                  <span className="text-slate-500 block">Workspace Mode:</span>
                  <span className="text-white capitalize">{activeWorkspace.mode}</span>
                </div>
                <div>
                  <span className="text-slate-500 block">Current Phase:</span>
                  <span className="text-white">Phase {activeWorkspace.current.phase}</span>
                </div>
                <div>
                  <span className="text-slate-500 block">Stuck Level:</span>
                  <span className="text-white">{activeWorkspace.current.stuck_level} / 3</span>
                </div>
                <div>
                  <span className="text-slate-500 block">Rounds Since Progress:</span>
                  <span className="text-white">{activeWorkspace.current.rounds_since_progress}</span>
                </div>
                {activeWorkspace.run.pid && (
                  <div>
                    <span className="text-slate-500 block">Engine Process ID:</span>
                    <span className="text-white font-mono">{activeWorkspace.run.pid}</span>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* SVG Progress Chart */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
            <div className="flex justify-between items-center">
              <div>
                <h3 className="text-sm font-bold uppercase tracking-wider text-slate-300 m-0">Convergence Analytics History</h3>
                <p className="text-xs text-slate-500 mt-0.5">Historical verification rounds, validation results, and stuck triggers</p>
              </div>
              <div className="flex items-center space-x-4 text-xs font-semibold">
                <span className="flex items-center space-x-1.5 text-emerald-400">
                  <span className="h-2 w-2 rounded-full bg-emerald-400"></span>
                  <span>PASS</span>
                </span>
                <span className="flex items-center space-x-1.5 text-rose-500">
                  <span className="h-2 w-2 rounded-full bg-rose-500"></span>
                  <span>FAIL</span>
                </span>
              </div>
            </div>

            {progress.length === 0 ? (
              <div className="border border-dashed border-slate-800 rounded-lg p-12 text-center text-slate-500 space-y-2 text-sm">
                <Activity className="h-8 w-8 text-slate-700 mx-auto" />
                <p>No analytics historical records. Run the validation engine to generate trend charts.</p>
              </div>
            ) : (
              renderProgressChart()
            )}
          </div>
        </div>

        {/* Right Side: Next Action Panel & Cause Timeline */}
        <div className="w-[380px] border-l border-slate-850 bg-slate-900/40 overflow-y-auto p-6 space-y-6 shrink-0 flex flex-col">
          {/* Next Action Box */}
          {nextAction && (
            <div className="bg-slate-900 border border-slate-850 rounded-xl p-5 shadow-sm space-y-4 relative">
              <div className="flex items-start justify-between">
                <div className="space-y-0.5">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-400 block">Action Recommendation</span>
                  <h4 className="text-sm font-bold text-white">{nextAction.label}</h4>
                </div>
                <div className={`p-1.5 rounded-lg ${
                  nextAction.kind === 'input' ? 'bg-amber-950/40 text-amber-400' :
                  nextAction.kind === 'start' ? 'bg-indigo-950/40 text-indigo-400' : 'bg-slate-800 text-slate-400'
                }`}>
                  {nextAction.kind === 'input' ? <AlertTriangle className="h-4 w-4" /> : <Activity className="h-4 w-4" />}
                </div>
              </div>
              <p className="text-xs text-slate-400 leading-relaxed">{nextAction.detail}</p>
              
              {nextAction.kind === 'input' && (
                <button 
                  onClick={() => handleResume(activeWorkspace.id)}
                  className="w-full py-2 bg-amber-600 hover:bg-amber-500 active:bg-amber-700 text-white rounded-lg text-xs font-semibold transition-colors flex items-center justify-center space-x-1 shadow-md"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  <span>Resume Execution Now</span>
                </button>
              )}
              {nextAction.kind === 'start' && (
                <button 
                  onClick={() => handleStart(activeWorkspace.id)}
                  className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold transition-colors flex items-center justify-center space-x-1 shadow-md"
                >
                  <Play className="h-3.5 w-3.5 fill-white" />
                  <span>Start Validation Loop</span>
                </button>
              )}
            </div>
          )}

          {/* Cause Timeline Feed */}
          <div className="flex-1 flex flex-col overflow-hidden">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3 shrink-0">Cause-driven Event Timeline</h3>
            <div className="flex-1 overflow-y-auto space-y-4 pr-1">
              {timeline.length === 0 ? (
                <p className="text-slate-600 text-xs italic text-center py-8">No recorded activity events.</p>
              ) : (
                timeline.map((evt, idx) => {
                  let Icon = Activity
                  let iconColor = 'text-slate-500'
                  let bgColor = 'bg-slate-900'

                  if (evt.type === 'loop_completed') {
                    Icon = CheckCircle2
                    iconColor = 'text-indigo-400'
                    bgColor = 'bg-indigo-950/20'
                  } else if (evt.type === 'round_passed' || evt.type === 'progress_made') {
                    Icon = CheckCircle2
                    iconColor = 'text-emerald-400'
                    bgColor = 'bg-emerald-950/10'
                  } else if (evt.type === 'round_failed') {
                    Icon = AlertCircle
                    iconColor = 'text-rose-500'
                    bgColor = 'bg-rose-950/10'
                  } else if (evt.type === 'human_required' || evt.type === 'preflight_blocked') {
                    Icon = AlertTriangle
                    iconColor = 'text-amber-500'
                    bgColor = 'bg-amber-950/15'
                  } else if (evt.type === 'model_escalated') {
                    Icon = Sparkles
                    iconColor = 'text-indigo-300'
                    bgColor = 'bg-slate-900'
                  }

                  return (
                    <div key={idx} className={`p-4 rounded-xl border border-slate-800/80 ${bgColor} text-xs space-y-2 relative`}>
                      <div className="flex items-start justify-between">
                        <span className="text-[10px] text-slate-500 font-mono">{evt.ts.split('T')?.[1]?.substring(0, 8) || evt.ts}</span>
                        <Icon className={`h-4 w-4 ${iconColor}`} />
                      </div>
                      <div className="space-y-0.5">
                        <h4 className="font-bold text-slate-200">{evt.title}</h4>
                        <p className="text-slate-400 text-[11px] leading-relaxed">{evt.detail}</p>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </div>
      </div>
    )
  }

  // ================= INTERACTIVE SVG CHART BUILDER =================
  function renderProgressChart() {
    // Collect coordinates and ranges
    const chartHeight = 150
    const chartWidth = 500
    const padding = 25
    
    // Sort array in ascending order of round number for line plotting
    const sortedProgress = [...progress].sort((a, b) => a.round - b.round)
    
    const rounds = sortedProgress.map(p => p.round)
    const minRound = Math.min(...rounds, 1)
    const maxRound = Math.max(...rounds, 10)
    
    const maxStuck = Math.max(...sortedProgress.map(p => p.stuck_level), 3)

    // Calculate coordinate converters
    const getX = (round: number) => {
      const ratio = maxRound === minRound ? 0.5 : (round - minRound) / (maxRound - minRound)
      return padding + ratio * (chartWidth - padding * 2)
    }

    const getY = (stuck: number) => {
      const ratio = stuck / maxStuck
      return chartHeight - padding - ratio * (chartHeight - padding * 2)
    }

    // Build line points path
    let pointsPath = ""
    sortedProgress.forEach((p, idx) => {
      const x = getX(p.round)
      const y = getY(p.stuck_level)
      if (idx === 0) pointsPath += `M ${x} ${y}`
      else pointsPath += ` L ${x} ${y}`
    })

    return (
      <div className="relative">
        <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} className="w-full h-auto bg-slate-950/40 rounded-lg border border-slate-800/60">
          {/* Horizontal Grid lines */}
          {[0, 1, 2, 3].map(lvl => {
            const y = getY(lvl)
            return (
              <g key={lvl}>
                <line x1={padding} y1={y} x2={chartWidth - padding} y2={y} stroke="#1e293b" strokeDasharray="3,3" />
                <text x={padding - 10} y={y + 3} fill="#475569" fontSize="8" textAnchor="end" fontFamily="monospace">
                  S{lvl}
                </text>
              </g>
            )
          })}

          {/* SVG Connector Path */}
          {pointsPath && (
            <path 
              d={pointsPath} 
              fill="none" 
              stroke="rgba(99, 102, 241, 0.4)" 
              strokeWidth="1.5" 
            />
          )}

          {/* Highlight data dots */}
          {sortedProgress.map((p, idx) => {
            const x = getX(p.round)
            const y = getY(p.stuck_level)
            const isPass = p.result === 'PASS'
            
            return (
              <g key={idx} className="group cursor-pointer">
                <circle 
                  cx={x} 
                  cy={y} 
                  r="4" 
                  fill={isPass ? '#10b981' : '#f43f5e'} 
                  className="transition-all group-hover:r-6"
                />
                <circle 
                  cx={x} 
                  cy={y} 
                  r="8" 
                  fill="transparent" 
                  className="hover:stroke-indigo-500 hover:stroke-[1.5px]"
                />
                {/* Embedded SVG dynamic tooltips */}
                <title>
                  {`Round ${p.round} [Phase ${p.phase}]\nResult: ${p.result}\nTier: ${p.model_tier}\nSummary: ${p.summary}`}
                </title>
              </g>
            )
          })}
        </svg>

        {/* Dynamic Horizontal Rounds axis details */}
        <div className="flex justify-between px-6 pt-1 text-[10px] text-slate-500 font-mono">
          <span>Round {minRound}</span>
          <span>Round {Math.floor((minRound + maxRound) / 2)}</span>
          <span>Round {maxRound}</span>
        </div>
      </div>
    )
  }

  // ================= TAB COMPONENT: TREE MODE TASK MAP =================
  function renderTreeTab() {
    if (!treeData.tree_enabled) {
      return (
        <div className="flex-1 p-8 text-center space-y-3 flex flex-col justify-center items-center">
          <GitBranch className="h-12 w-12 text-slate-700" />
          <h3 className="text-lg font-bold text-white">Flat Mode Workspace</h3>
          <p className="text-slate-400 text-sm max-w-sm">This workspace is configured in flat mode. Planning trees and visual hierarchical nodes are only available for workspaces deploying Tree Hill Climbing structures.</p>
        </div>
      )
    }

    const activeLeaf = activeWorkspace?.current.active_leaf

    return (
      <div className="flex-1 flex overflow-hidden">
        {/* Left Side: Planning Tree Topology Node grid */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          <div className="flex justify-between items-center">
            <div>
              <h3 className="text-sm font-bold uppercase tracking-wider text-slate-300 m-0">Tree Node Hierarchy Progress</h3>
              <p className="text-xs text-slate-500 mt-0.5">Visualize phase convergence, backtracking revision flows, and reflow triggers</p>
            </div>
            {activeLeaf && (
              <span className="text-xs px-2.5 py-1 bg-indigo-950/80 text-indigo-400 rounded-lg border border-indigo-900 font-mono">
                Active Leaf: <strong className="text-emerald-400">[{activeLeaf}]</strong>
              </span>
            )}
          </div>

          {/* Grid Layout of Nodes */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {treeData.nodes.map(node => {
              const isActive = node.id === activeLeaf
              const isRoot = node.id === treeData.root
              
              let stateColor = 'border-slate-800 bg-slate-900/50 text-slate-400'
              if (node.state === 'CONVERGED') stateColor = 'border-emerald-800 bg-emerald-950/15 text-emerald-400'
              else if (node.state === 'RUNNING') stateColor = 'border-blue-700 bg-blue-950/20 text-blue-300'
              else if (node.state === 'NEEDS_REVISION') stateColor = 'border-amber-700 bg-amber-950/25 text-amber-400'

              return (
                <div 
                  key={node.id} 
                  className={`border rounded-xl p-5 relative overflow-hidden transition-all flex flex-col justify-between min-h-[160px] ${stateColor} ${
                    isActive ? 'ring-2 ring-indigo-500/80 ring-offset-2 ring-offset-slate-950' : ''
                  }`}
                >
                  <div className="space-y-2">
                    <div className="flex justify-between items-start">
                      <div className="space-y-0.5">
                        <div className="flex items-center space-x-1.5">
                          <span className="font-bold text-slate-200 text-sm">{node.id}</span>
                          {isRoot && <span className="px-1 py-0.5 bg-indigo-900 text-[8px] text-white rounded uppercase font-bold">Root</span>}
                        </div>
                        <span className="text-[10px] text-slate-500 font-mono">Depth {node.depth}</span>
                      </div>
                      <span className={`px-2 py-0.5 rounded text-[9px] font-bold ${
                        node.state === 'CONVERGED' ? 'bg-emerald-900/60' :
                        node.state === 'RUNNING' ? 'bg-blue-900/50' :
                        node.state === 'NEEDS_REVISION' ? 'bg-amber-900/50' : 'bg-slate-800'
                      }`}>
                        {node.state}
                      </span>
                    </div>

                    <p className="text-xs text-slate-300 line-clamp-2 leading-relaxed">{node.description}</p>
                  </div>

                  <div className="border-t border-slate-800/40 pt-3 mt-4 flex items-center justify-between text-[10px] text-slate-500 font-mono">
                    <div className="flex space-x-3">
                      <span>Rounds: {node.stable_rounds}</span>
                      <span>Reflows: {node.reflow_count}</span>
                    </div>

                    {node.state !== 'PENDING' && (
                      <button 
                        onClick={() => handleRejectNode(node.id)}
                        disabled={loading || activeWorkspace?.status === 'running'}
                        className="px-2 py-1 bg-rose-950/40 hover:bg-rose-900/40 disabled:opacity-30 disabled:hover:bg-rose-950/40 text-rose-400 rounded border border-rose-900/40 transition-colors cursor-pointer text-[10px]"
                        title="Reject subtree and force replanning"
                      >
                        Reject Node
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    )
  }

  // ================= TAB COMPONENT: CONFIGURATION PANEL =================
  function renderConfigTab() {
    return (
      <div className="flex-1 flex overflow-hidden">
        {/* Left Form Side */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          <div className="flex justify-between items-center border-b border-slate-850 pb-4">
            <div>
              <h3 className="text-base font-bold text-white m-0">Loop Config Editor</h3>
              <p className="text-xs text-slate-500 mt-1">Fill fields via Wizard panel or edit raw `loop.config.yaml` file with YAML syntax validations</p>
            </div>
            <div className="flex space-x-2 text-xs">
              <button 
                onClick={() => setIsRawConfigEdit(false)}
                className={`px-3 py-1.5 rounded-lg font-semibold border transition-all ${
                  !isRawConfigEdit 
                    ? 'bg-slate-800 text-white border-slate-700' 
                    : 'text-slate-400 hover:text-white border-transparent'
                }`}
              >
                Wizard Form
              </button>
              <button 
                onClick={() => setIsRawConfigEdit(true)}
                className={`px-3 py-1.5 rounded-lg font-semibold border transition-all ${
                  isRawConfigEdit 
                    ? 'bg-slate-800 text-white border-slate-700' 
                    : 'text-slate-400 hover:text-white border-transparent'
                }`}
              >
                Raw YAML
              </button>
            </div>
          </div>

          {!isRawConfigEdit ? (
            // Configuration Wizard
            <form onSubmit={handleConfigWizardSave} className="space-y-6 max-w-2xl bg-slate-900/40 p-6 rounded-xl border border-slate-850">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-2">
                  <label className="block text-xs font-bold text-slate-300 uppercase tracking-wide">Build command</label>
                  <input 
                    type="text" 
                    value={wizardForm.build_cmd}
                    onChange={e => setWizardForm({...wizardForm, build_cmd: e.target.value})}
                    placeholder="e.g. npm run test"
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-indigo-500"
                    required
                  />
                  <p className="text-[10px] text-slate-500">The build or testing command utilized to validate converged results.</p>
                </div>

                <div className="space-y-2">
                  <label className="block text-xs font-bold text-slate-300 uppercase tracking-wide">Generation Mode</label>
                  <select 
                    value={wizardForm.mode}
                    onChange={e => setWizardForm({...wizardForm, mode: e.target.value})}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="auto">Auto (No human checks)</option>
                    <option value="gated">Gated (Requires confirmation gates)</option>
                  </select>
                  <p className="text-[10px] text-slate-500">Control if validation stages automatically proceed.</p>
                </div>
              </div>

              <div className="border-t border-slate-800/80 pt-6 space-y-4">
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-300 m-0">Models Specifications</h4>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  <div className="space-y-1.5">
                    <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider">Fast Model</label>
                    <input 
                      type="text" 
                      value={wizardForm.fast_model}
                      onChange={e => setWizardForm({...wizardForm, fast_model: e.target.value})}
                      placeholder="gemini-2.5-flash"
                      className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                      required
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider">Normal Model</label>
                    <input 
                      type="text" 
                      value={wizardForm.normal_model}
                      onChange={e => setWizardForm({...wizardForm, normal_model: e.target.value})}
                      placeholder="gemini-2.5-pro"
                      className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                      required
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider">Thinking Model</label>
                    <input 
                      type="text" 
                      value={wizardForm.thinking_model}
                      onChange={e => setWizardForm({...wizardForm, thinking_model: e.target.value})}
                      placeholder="gemini-2.0-flash-thinking"
                      className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                      required
                    />
                  </div>
                </div>
              </div>

              <div className="flex justify-end pt-4">
                <button 
                  type="submit"
                  disabled={loading}
                  className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-sm font-semibold transition-colors shadow-md flex items-center space-x-1.5"
                >
                  {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                  <span>Apply Wizard Settings</span>
                </button>
              </div>
            </form>
          ) : (
            // Raw Config YAML Textarea Editor
            <div className="space-y-4">
              <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-950">
                <textarea 
                  value={configYaml}
                  onChange={e => setConfigYaml(e.target.value)}
                  className="w-full min-h-[400px] p-5 bg-slate-950/80 font-mono text-xs leading-relaxed text-slate-100 placeholder-slate-600 focus:outline-none resize-y"
                  spellCheck="false"
                />
              </div>
              <div className="flex justify-end">
                <button 
                  onClick={handleConfigSave}
                  disabled={loading}
                  className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-sm font-semibold transition-all shadow-md flex items-center space-x-1.5"
                >
                  {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                  <span>Save configuration YAML</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }

  // ================= TAB COMPONENT: DIAGNOSTICS TERMINAL DRAWER =================
  function renderDiagnosticsTab() {
    return (
      <div className="flex-1 flex overflow-hidden bg-slate-950">
        {/* Left Navigation SubTab List */}
        <div className="w-[180px] border-r border-slate-850 shrink-0 p-4 space-y-2">
          {[
            { id: 'logs', label: 'Streaming Logs', icon: Terminal },
            { id: 'state', label: 'raw state.json', icon: FileCode },
            { id: 'diff', label: 'Uncommitted Diff', icon: FileText }
          ].map(sub => {
            const Icon = sub.icon
            const active = activeDiagnosticsSubTab === sub.id
            return (
              <button
                key={sub.id}
                onClick={() => setActiveDiagnosticsSubTab(sub.id as any)}
                className={`w-full py-2 px-3 text-left rounded-lg text-xs font-semibold flex items-center space-x-2 transition-colors ${
                  active 
                    ? 'bg-indigo-950 text-indigo-400 border border-indigo-900' 
                    : 'text-slate-400 hover:bg-slate-900/50 hover:text-slate-200 border border-transparent'
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                <span>{sub.label}</span>
              </button>
            )
          })}
        </div>

        {/* Dynamic content rendering */}
        <div className="flex-1 overflow-hidden flex flex-col p-6">
          {activeDiagnosticsSubTab === 'logs' && (
            <div className="flex-1 flex flex-col overflow-hidden space-y-4">
              <div className="flex justify-between items-center shrink-0">
                <div className="flex items-center space-x-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Stream Source:</span>
                  <div className="flex rounded-lg overflow-hidden border border-slate-800 text-[11px] font-bold">
                    <button 
                      onClick={() => setLogType('loop')}
                      className={`px-3 py-1 ${logType === 'loop' ? 'bg-slate-800 text-white' : 'bg-slate-950 text-slate-400 hover:text-slate-200'}`}
                    >
                      loop.log
                    </button>
                    <button 
                      onClick={() => setLogType('plan')}
                      className={`px-3 py-1 ${logType === 'plan' ? 'bg-slate-800 text-white' : 'bg-slate-950 text-slate-400 hover:text-slate-200'}`}
                    >
                      plan.log
                    </button>
                  </div>
                </div>
                
                <a 
                  href={`/api/workspaces/${activeWorkspaceId}/logs/${logType}/download`}
                  className="flex items-center space-x-1.5 px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 text-xs rounded-lg border border-slate-800 transition-colors"
                >
                  <Download className="h-3.5 w-3.5" />
                  <span>Download file</span>
                </a>
              </div>

              {/* Streaming Log Line list */}
              <div className="flex-1 border border-slate-850 rounded-xl overflow-y-auto bg-slate-950 p-4 font-mono text-[11px] leading-relaxed select-text flex flex-col space-y-1">
                {logLines.map((line, idx) => (
                  <div key={idx} className="flex hover:bg-slate-900/40 py-0.5 rounded px-1 transition-colors">
                    <span className="w-10 text-slate-600 select-none text-right pr-3">{idx + 1}</span>
                    <span className="text-slate-300 flex-1 whitespace-pre-wrap break-all">{line}</span>
                  </div>
                ))}
                <div ref={logTerminalEndRef} />
              </div>
            </div>
          )}

          {activeDiagnosticsSubTab === 'state' && (
            <div className="flex-1 flex flex-col overflow-hidden space-y-4">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400 block shrink-0">Prettified state.json Contents</span>
              <pre className="flex-1 border border-slate-850 rounded-xl overflow-y-auto bg-slate-950 p-5 font-mono text-[11px] leading-relaxed text-slate-300 select-text">
                {rawState || "state.json is empty or not initialized."}
              </pre>
            </div>
          )}

          {activeDiagnosticsSubTab === 'diff' && (
            <div className="flex-1 flex flex-col overflow-hidden space-y-4">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400 block shrink-0">Workspace Git status uncommitted modifications diff</span>
              <div className="flex-1 border border-slate-850 rounded-xl overflow-y-auto bg-slate-950 p-5 font-mono text-[11px] leading-relaxed text-slate-300 select-text flex flex-col">
                {gitDiff.split('\n').map((line, i) => {
                  let lineClass = 'text-slate-300'
                  if (line.startsWith('+') && !line.startsWith('+++')) lineClass = 'text-emerald-400 bg-emerald-950/10'
                  else if (line.startsWith('-') && !line.startsWith('---')) lineClass = 'text-rose-400 bg-rose-950/10'
                  else if (line.startsWith('diff') || line.startsWith('index') || line.startsWith('@@')) lineClass = 'text-indigo-400'
                  
                  return (
                    <div key={i} className={`whitespace-pre-wrap break-all ${lineClass}`}>
                      {line}
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }

  // ================= GENERAL HELPERS =================
  function getStatusColor(status?: string) {
    if (!status) return 'bg-slate-600'
    switch (status) {
      case 'running': return 'bg-emerald-500'
      case 'human_required': return 'bg-amber-500'
      case 'complete': return 'bg-indigo-500'
      case 'preflight_blocked': return 'bg-rose-500'
      default: return 'bg-slate-600'
    }
  }

  function getDirectionColor(direction?: string) {
    if (!direction) return 'bg-slate-800 text-slate-400 border border-slate-700'
    switch (direction) {
      case 'forward': return 'bg-emerald-950 text-emerald-400 border border-emerald-800'
      case 'backward': return 'bg-rose-950 text-rose-400 border border-rose-800'
      case 'stalled': return 'bg-amber-950 text-amber-500 border border-amber-800'
      case 'neutral': return 'bg-slate-800 text-slate-300 border border-slate-700'
      default: return 'bg-slate-800 text-slate-400 border border-slate-700'
    }
  }
}
