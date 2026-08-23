import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Archive,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  CircleDashed,
  Database,
  ExternalLink,
  FileArchive,
  FlaskConical,
  FolderOpen,
  KeyRound,
  Loader2,
  PackageOpen,
  Play,
  RefreshCw,
  Save,
  Server,
  Settings2,
  ShieldCheck,
  Sparkles,
  Terminal,
  UploadCloud,
  Wifi,
  X,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  SectionHeading,
  Segmented,
  StatusDot,
  cn,
} from "./components/ui.jsx";

const REGIONS = ["TW", "TH", "VN", "ID"];
const REGION_SCOPES = { TW: "/Taiwan", TH: "/Thailand", VN: "/Vietnam", ID: "/Indonesia" };
const MODULE_ORDER = ["activity", "skin", "item", "reward", "limit"];
const ACTIVITY_KEYWORDS = ["签到", "定时", "翻倍", "条件", "兑换", "文本", "商城", "活跃度", "全服统一进度", "收集兑换", "通用兑换"];

export function App() {
  const [view, setView] = useState("pack");
  const [settings, setSettings] = useState({});
  const [ftpForms, setFtpForms] = useState({});
  const [region, setRegion] = useState("TW");
  const [ftpRegion, setFtpRegion] = useState("TW");
  const [revision, setRevision] = useState("");
  const [inputSource, setInputSource] = useState("auto");
  const [contentMode, setContentMode] = useState("local_latest");
  const [manualInput, setManualInput] = useState("");
  const [svnPassword, setSvnPassword] = useState("");
  const [backendToken, setBackendToken] = useState("");
  const [backendStatus, setBackendStatus] = useState("pending");
  const [ftpStatus, setFtpStatus] = useState("idle");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [logs, setLogs] = useState([]);
  const [stages, setStages] = useState({ svn: "idle", packaging: "idle", review: "idle", archive: "idle" });
  const [runStatus, setRunStatus] = useState("idle");
  const [settingsMessage, setSettingsMessage] = useState("");
  const [toast, setToast] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(null);
  const [activeGroup, setActiveGroup] = useState("regular");
  const [activeModule, setActiveModule] = useState("");

  const showToast = useCallback((message, tone = "info") => {
    setToast({ message, tone });
    window.setTimeout(() => setToast(null), 4200);
  }, []);

  const addLog = useCallback((message, level = "info") => {
    setLogs((previous) => [...previous.slice(-99), { id: `${Date.now()}-${Math.random()}`, message, level, time: new Date() }]);
  }, []);

  const applySettings = useCallback((safeSettings) => {
    const next = safeSettings || {};
    setSettings(next);
    const nextRegion = REGIONS.includes(next.package_region) ? next.package_region : "TW";
    setRegion(nextRegion);
    setFtpRegion(nextRegion);
    setFtpForms(Object.fromEntries(REGIONS.map((code) => {
      const profile = next.ftp_profiles?.[code] || {};
      return [code, {
        host: profile.host || "",
        port: profile.port || "21",
        username: profile.username || "",
        password: "",
        passwordConfigured: Boolean(profile.password_configured),
        remote_directory: profile.remote_directory || "/",
        passive: profile.passive !== false,
      }];
    })));
  }, []);

  const refreshConnections = useCallback(async () => {
    const baseUrl = String(settings.backend_url || "").trim();
    if (!baseUrl) {
      setBackendStatus("error");
      setFtpStatus("idle");
      return;
    }
    setBackendStatus("pending");
    try {
      const response = await window.aov.request("check_backend", { backend_url: baseUrl, backend_token: backendToken, region });
      setBackendStatus("ok");
      if (response.baseline) {
        setSettings((previous) => ({
          ...previous,
          last_external_revision_spec: response.baseline.released_revision_spec || "",
          last_external_time: response.baseline.release_time || "",
          last_external_package_id: response.baseline.package_id || previous.last_external_package_id || "",
          package_version: response.baseline.package_version || previous.package_version,
        }));
      }
    } catch (error) {
      setBackendStatus("error");
      addLog(error.message, "error");
    }
    try {
      await window.aov.request("check_ftp", { region });
      setFtpStatus("ok");
    } catch (error) {
      setFtpStatus("error");
      addLog(error.message, "warning");
    }
  }, [addLog, backendToken, region, settings.backend_url]);

  useEffect(() => {
    let mounted = true;
    window.aov.request("bootstrap").then((response) => {
      if (!mounted) return;
      applySettings(response.settings);
      if (response.pending_sync_count > 0) showToast(`有 ${response.pending_sync_count} 条待同步归档`, "warning");
      const safeSettings = response.settings || {};
      const nextRegion = REGIONS.includes(safeSettings.package_region) ? safeSettings.package_region : "TW";
      Promise.allSettled([
        window.aov.request("check_backend", { backend_url: safeSettings.backend_url || "", backend_token: "", region: nextRegion }),
        window.aov.request("check_ftp", { region: nextRegion }),
      ]).then(([backend, ftp]) => {
        if (!mounted) return;
        setBackendStatus(backend.status === "fulfilled" ? "ok" : "error");
        setFtpStatus(ftp.status === "fulfilled" ? "ok" : "error");
        if (backend.status === "fulfilled") applyBaseline(backend.value.baseline);
      });
    }).catch((error) => {
      if (!mounted) return;
      setBackendStatus("error");
      showToast(`启动失败：${error.message}`, "error");
    });
    return () => { mounted = false; };
  }, [applySettings, showToast]);

  useEffect(() => {
    const removeEvent = window.aov.onBridgeEvent((message) => {
      if (message.event === "log") addLog(message.data.message, message.data.level);
      if (message.event === "progress") {
        const total = Number(message.data.total_bytes || 0);
        const transferred = Number(message.data.transferred_bytes || 0);
        setUploadProgress({ percent: total ? Math.min(100, transferred * 100 / total) : 0, label: message.data.filename || "FTP 上传" });
      }
      if (message.event === "stage") {
        const stageMap = { source_check: "svn", packaging: "packaging", preflight: "archive", ftp_upload: "archive", backend_archive: "archive", complete: "archive" };
        const stage = stageMap[message.data.stage] || "packaging";
        setStages((previous) => {
          const order = ["svn", "packaging", "review", "archive"];
          const index = order.indexOf(stage);
          return Object.fromEntries(order.map((item, itemIndex) => [item, itemIndex < index ? "complete" : itemIndex === index ? "active" : previous[item] === "complete" ? "complete" : "idle"]));
        });
        if (stage === "archive") setUploadProgress((previous) => previous || { percent: 0, label: "准备归档" });
      }
    });
    const removeError = window.aov.onBridgeError(({ message }) => addLog(message, "error"));
    return () => { removeEvent?.(); removeError?.(); };
  }, [addLog]);

  const setSetting = (key, value) => setSettings((previous) => ({ ...previous, [key]: value }));
  const currentFtp = ftpForms[ftpRegion] || { host: "", port: "21", username: "", password: "", remote_directory: "/", passive: true };

  const applyBaseline = (baseline) => {
    if (!baseline) return;
    setSettings((previous) => ({
      ...previous,
      last_external_revision_spec: baseline.released_revision_spec || previous.last_external_revision_spec || "",
      last_external_time: baseline.release_time || previous.last_external_time || "",
      last_external_package_id: baseline.package_id || previous.last_external_package_id || "",
      package_version: baseline.package_version || previous.package_version || "",
    }));
  };

  const serializeProfile = (profile) => {
    const next = { ...profile };
    delete next.passwordConfigured;
    if (!next.password) delete next.password;
    return next;
  };

  const collectSettings = () => ({
    ...settings,
    local_root: String(settings.local_root || "").trim(),
    tdr_root: String(settings.tdr_root || "").trim(),
    svn_target: String(settings.svn_target || "").trim(),
    svn_exe: String(settings.svn_exe || "svn").trim() || "svn",
    svn_username: String(settings.svn_username || "").trim(),
    package_region: region,
    scope_roots: String(settings.scope_roots || REGION_SCOPES[region]).trim() || REGION_SCOPES[region],
    ftp_profiles: Object.fromEntries(REGIONS.map((code) => [code, serializeProfile(ftpForms[code] || {})])),
  });

  const updateFtp = (key, value) => setFtpForms((previous) => ({ ...previous, [ftpRegion]: { ...currentFtp, [key]: value } }));

  const checkBackend = async () => {
    setBackendStatus("pending");
    try {
      const response = await window.aov.request("check_backend", { backend_url: settings.backend_url || "", backend_token: backendToken, region });
      setBackendStatus("ok");
      applyBaseline(response.baseline);
      showToast("归档后端连接正常", "success");
    } catch (error) {
      setBackendStatus("error");
      showToast(error.message, "error");
    }
  };

  const checkFtp = async (useForm = false) => {
    setFtpStatus("pending");
    try {
      await window.aov.request("check_ftp", { region: ftpRegion, profile: useForm ? serializeProfile(currentFtp) : undefined });
      if (ftpRegion === region) setFtpStatus("ok");
      showToast(`${ftpRegion} FTP 连接正常`, "success");
    } catch (error) {
      if (ftpRegion === region) setFtpStatus("error");
      showToast(error.message, "error");
    }
  };

  const handleRegionChange = (nextRegion) => {
    setRegion(nextRegion);
    setSetting("package_region", nextRegion);
    setSetting("scope_roots", REGION_SCOPES[nextRegion]);
    setBackendStatus("pending");
    setFtpStatus("pending");
    Promise.allSettled([
      window.aov.request("check_backend", { backend_url: settings.backend_url || "", backend_token: backendToken, region: nextRegion }),
      window.aov.request("check_ftp", { region: nextRegion }),
    ]).then(([backend, ftp]) => {
      setBackendStatus(backend.status === "fulfilled" ? "ok" : "error");
      setFtpStatus(ftp.status === "fulfilled" ? "ok" : "error");
      if (backend.status === "fulfilled") applyBaseline(backend.value.baseline);
    });
  };

  const startPack = async (testMode = false) => {
    if (busy) return;
    if (!revision.trim() && inputSource === "auto") {
      showToast("请先填写本次 Revision", "warning");
      return;
    }
    setBusy(true);
    setResult(null);
    setLogs([]);
    setUploadProgress(null);
    setRunStatus("running");
    setStages({ svn: inputSource === "auto" ? "active" : "complete", packaging: inputSource === "auto" ? "idle" : "active", review: "idle", archive: "idle" });
    addLog(`${testMode ? "执行测试" : "开始打包"} · ${region} · ${revision || "手动文件列表"}`);
    try {
      const response = await window.aov.request("pack", {
        ...collectSettings(),
        region,
        current_revision_spec: revision.trim(),
        input_method: inputSource === "files" ? "pasted_svn_file_list" : "revision_spec",
        svn_log_source: inputSource === "auto" ? "auto" : "manual",
        input_text: manualInput,
        svn_password: svnPassword,
        content_mode: contentMode,
        test_mode: testMode,
      });
      setResult(response);
      const responseDetails = Array.isArray(response.content_details) && response.content_details.length ? response.content_details : (response.activity_details || []);
      const firstUsefulGroup = ["ilua", "regular", "item", "related"].find((groupId) => responseDetails.some((item) => {
        const moduleId = String(item.module || "");
        const activityType = String(item.activity_type || "");
        if (groupId === "related") return !item.direct_change;
        if (groupId === "ilua") return item.direct_change && moduleId === "activity" && activityType.toLowerCase().includes("ilua");
        if (groupId === "regular") return item.direct_change && moduleId === "activity" && ACTIVITY_KEYWORDS.some((keyword) => activityType.includes(keyword));
        return item.direct_change && moduleId === "item";
      }));
      setActiveGroup(firstUsefulGroup || "regular");
      setActiveModule("");
      setStages({ svn: "complete", packaging: "complete", review: "active", archive: "idle" });
      setRunStatus("success");
      addLog(`${testMode ? "测试" : "打包"}完成：${response.package_name}`, "success");
      showToast(testMode ? "测试打包完成" : "打包完成，请检查 Report", "success");
    } catch (error) {
      const activeStage = Object.keys(stages).find((stage) => stages[stage] === "active") || "packaging";
      setStages((previous) => ({ ...previous, [activeStage]: "error" }));
      setRunStatus("error");
      addLog(error.message, "error");
      showToast(error.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const saveSettings = async (event) => {
    event.preventDefault();
    setSettingsMessage("正在保存...");
    try {
      const response = await window.aov.request("save_settings", { settings: collectSettings() });
      applySettings(response.settings);
      setSettingsMessage("配置已保存");
      showToast("本地配置已保存", "success");
    } catch (error) {
      setSettingsMessage("保存失败");
      showToast(error.message, "error");
    }
  };

  const confirmArchive = async () => {
    if (!result || busy) return;
    if (!window.confirm(`确认归档 ${result.package_name}？\n\n将上传 FTP 并同步网页后端。`)) return;
    setBusy(true);
    setStages((previous) => ({ ...previous, archive: "active" }));
    try {
      const info = await window.aov.request("inspect_archive", { region });
      let policy = "require_absent";
      if (info.exists && info.remote_size === info.local_size) {
        if (!window.confirm("FTP 已存在同名且同大小文件。确认是同一个包，并只继续网页归档？")) throw new Error("已取消归档");
        policy = "use_existing";
      } else if (info.exists) {
        if (!window.confirm("FTP 已存在同名文件，但大小不同。确认替换远端文件？")) throw new Error("已取消归档");
        policy = "replace";
      }
      const response = await window.aov.request("publish", { region, policy, backend_token: backendToken });
      setStages({ svn: "complete", packaging: "complete", review: "complete", archive: "complete" });
      setRunStatus("success");
      setUploadProgress({ percent: 100, label: "归档完成" });
      showToast(`归档完成：${response.package_id}`, "success");
    } catch (error) {
      setStages((previous) => ({ ...previous, archive: "error" }));
      if (error.message !== "已取消归档") showToast(error.message, "error");
      addLog(error.message, error.message === "已取消归档" ? "warning" : "error");
    } finally {
      setBusy(false);
    }
  };

  const groups = useMemo(() => {
    const details = Array.isArray(result?.content_details) && result.content_details.length ? result.content_details : (result?.activity_details || []);
    const next = [
      { id: "ilua", label: "ilua 活动", items: [] },
      { id: "regular", label: "常规活动", items: [] },
      { id: "item", label: "道具", items: [] },
      { id: "related", label: "关联内容", items: [] },
    ];
    const byId = Object.fromEntries(next.map((group) => [group.id, group]));
    details.forEach((item) => {
      const moduleId = String(item.module || "");
      const activityType = String(item.activity_type || "");
      if (!item.direct_change) byId.related.items.push(item);
      else if (moduleId === "activity" && activityType.toLowerCase().includes("ilua")) byId.ilua.items.push(item);
      else if (moduleId === "activity" && ACTIVITY_KEYWORDS.some((keyword) => activityType.includes(keyword))) byId.regular.items.push(item);
      else if (moduleId === "item") byId.item.items.push(item);
    });
    return next;
  }, [result]);

  const moduleGroups = useMemo(() => {
    const details = Array.isArray(result?.content_details) ? result.content_details : [];
    const map = new Map();
    details.forEach((item) => {
      const id = item.module || "other";
      if (!map.has(id)) map.set(id, { id, name: item.module_name || "其他", items: [] });
      map.get(id).items.push(item);
    });
    return [...map.values()].sort((left, right) => (MODULE_ORDER.indexOf(left.id) < 0 ? 99 : MODULE_ORDER.indexOf(left.id)) - (MODULE_ORDER.indexOf(right.id) < 0 ? 99 : MODULE_ORDER.indexOf(right.id)));
  }, [result]);

  const selectedGroup = groups.find((group) => group.id === activeGroup) || groups[0];
  const overview = result?.module_overview || {};
  const details = Array.isArray(result?.content_details) && result.content_details.length ? result.content_details : (result?.activity_details || []);
  const validation = result?.validation || { warning_count: 0, error_count: 0 };
  const runLabel = runStatus === "running" ? "执行中" : runStatus === "success" ? "已完成" : runStatus === "error" ? "失败" : "待开始";

  const chooseDirectory = async (key) => {
    const selected = await window.aov.selectDirectory();
    if (selected) setSetting(key, selected);
  };

  const stageLabels = { svn: ["读取 SVN", "读取提交记录与本地工作副本"], packaging: ["生成归档包", "过滤区域并生成文件"], review: ["检查 Report", "查看业务模块与风险"], archive: ["确认归档", "人工确认上传与同步"] };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">A</div>
          <div><strong>AOV AutoPacker</strong><span>本地发布工作台</span></div>
        </div>
        <nav className="nav-list" aria-label="主要栏目">
          <button className={cn("nav-item", view === "pack" && "active")} onClick={() => setView("pack")}>
            <PackageOpen size={17} /><span><small>01</small>打包任务</span><ChevronRight size={15} />
          </button>
          <button className={cn("nav-item", view === "settings" && "active")} onClick={() => setView("settings")}>
            <Settings2 size={17} /><span><small>02</small>本地配置</span><ChevronRight size={15} />
          </button>
        </nav>
        <div className="sidebar-spacer" />
        <div className="connection-card">
          <div className="connection-row"><StatusDot status={backendStatus} /><div><span>归档后端</span><strong>{backendStatus === "ok" ? "已连接" : backendStatus === "pending" ? "检查中" : "未连接"}</strong></div></div>
          <div className="connection-row"><StatusDot status={ftpStatus} /><div><span>{region} FTP</span><strong>{ftpStatus === "ok" ? "已连接" : ftpStatus === "pending" ? "检查中" : "未检查"}</strong></div></div>
        </div>
        <div className="sidebar-footer"><ShieldCheck size={14} />本地优先 · 人工确认发布</div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div><div className="eyebrow">{view === "pack" ? "LOCAL PACKAGING" : "MACHINE SETTINGS"}</div><h1>{view === "pack" ? "打包任务" : "本地配置"}</h1></div>
          <div className="topbar-actions"><Button variant="ghost" icon={RefreshCw} onClick={refreshConnections}>刷新连接</Button><div className="operator"><span>A</span><strong>admin</strong></div></div>
        </header>

        {view === "pack" ? (
          <div className="page-stack">
            <div className="page-intro"><div><Badge tone="accent" icon={Sparkles}>React workspace</Badge><h2>把一次发布变成一条可审阅的流水线</h2><p>选择区域和 revision，先在本地生成包与 Report，再决定是否上传和归档。</p></div><div className="intro-meta"><span>HEAD</span><strong>{result?.package_source?.repository_head_revision ? `r${result.package_source.repository_head_revision}` : "未读取"}</strong></div></div>
            <div className="pack-grid">
              <div className="main-column">
                <Card className="hero-card">
                  <SectionHeading eyebrow="01 · PACKAGE SCOPE" title="选择发布范围" description="Revision 只决定本次纳入的提交；内容版本决定实际取文件的方式。" />
                  <div className="field-block"><span className="field-label">打包区域</span><Segmented value={region} onChange={handleRegionChange} options={REGIONS.map((code) => ({ value: code, label: code }))} ariaLabel="打包区域" /><span className="scope-hint"><Database size={14} />{REGION_SCOPES[region]}</span></div>
                  <div className="revision-grid">
                    <Field label="本次 Revision" hint="支持 r10001-r10005 或 r10001,r10003"><input value={revision} onChange={(event) => setRevision(event.target.value)} placeholder="r1740429" autoComplete="off" /></Field>
                    <div className="field"><span className="field-label">内容版本</span><Segmented value={contentMode} onChange={setContentMode} options={[{ value: "local_latest", label: "本地最新" }, { value: "historical_revision", label: "历史精确" }]} ariaLabel="内容版本" /></div>
                  </div>
                  <div className="field-block source-block"><div className="field-label-row"><span className="field-label">SVN 输入方式</span><Badge tone="neutral" icon={Terminal}>{inputSource === "auto" ? "自动读取" : "手动输入"}</Badge></div><Segmented value={inputSource} onChange={setInputSource} options={[{ value: "auto", label: "自动读取" }, { value: "manual", label: "粘贴日志" }, { value: "files", label: "文件列表" }]} ariaLabel="SVN 输入方式" /></div>
                  {inputSource !== "auto" ? <Field label={inputSource === "files" ? "指定 SVN 文件列表" : "SVN log -v 内容"}><textarea value={manualInput} onChange={(event) => setManualInput(event.target.value)} placeholder={inputSource === "files" ? "M /Taiwan/Databin/Server/..." : "粘贴 svn log -v 输出"} rows={5} spellCheck="false" /></Field> : null}
                  <div className="baseline-card"><div><span>上次对外</span><strong>{settings.last_external_revision_spec || "--"}</strong></div><div><span>归档包</span><strong>{settings.last_external_package_id || "未读取"}</strong></div><div><span>对外时间</span><strong>{settings.last_external_time ? new Date(settings.last_external_time).toLocaleString("zh-CN") : "--"}</strong></div></div>
                  <div className="action-row"><Button variant="secondary" icon={FlaskConical} disabled={busy} onClick={() => startPack(true)}>执行测试</Button><Button variant="primary" icon={busy ? Loader2 : Play} disabled={busy} onClick={() => startPack(false)}>{busy ? "执行中..." : "开始打包"}<kbd>⌘ Enter</kbd></Button></div>
                </Card>

                {result ? <ResultCard result={result} groups={groups} selectedGroup={selectedGroup} activeGroup={activeGroup} setActiveGroup={setActiveGroup} details={details} moduleGroups={moduleGroups} activeModule={activeModule} setActiveModule={setActiveModule} overview={overview} validation={validation} onOpenOutput={() => window.aov.openPath(result.output_dir)} onOpenReport={() => window.aov.openPath(result.report_path)} onArchive={confirmArchive} uploadProgress={uploadProgress} /> : <Card className="welcome-card"><div className="welcome-icon"><FileArchive size={22} /></div><div><h3>还没有本次结果</h3><p>执行测试会生成不会上传的本地包；正式打包完成后，这里会显示 Report、业务模块与归档操作。</p></div><ArrowUpRight size={18} /></Card>}
              </div>

              <Card className="run-card"><div className="run-card-heading"><div><div className="eyebrow">RUN STATUS</div><h2>执行状态</h2></div><Badge tone={runStatus === "success" ? "success" : runStatus === "error" ? "danger" : runStatus === "running" ? "accent" : "neutral"} icon={runStatus === "running" ? Loader2 : runStatus === "success" ? CheckCircle2 : runStatus === "error" ? CircleAlert : CircleDashed}>{runLabel}</Badge></div><div className="stage-list">{Object.entries(stageLabels).map(([key, [label, description]], index) => <div className={cn("stage-item", `stage-${stages[key]}`)} key={key}><div className="stage-index">{stages[key] === "complete" ? <Check size={14} /> : stages[key] === "active" ? <Loader2 size={14} className="spin" /> : index + 1}</div><div><strong>{label}</strong><span>{stages[key] === "active" ? "执行中" : stages[key] === "complete" ? "已完成" : description}</span></div></div>)}</div><div className="log-header"><span>活动日志</span><button onClick={() => setLogs([])} disabled={!logs.length}><X size={13} />清空</button></div><div className="log-panel" aria-live="polite">{logs.length ? logs.map((entry) => <p className={entry.level} key={entry.id}><span>{entry.time.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>{entry.message}</p>) : <EmptyState icon={Terminal} title="尚无执行日志" description="启动一次测试或打包后，过程会显示在这里。" />}</div></Card>
            </div>
          </div>
        ) : (
          <SettingsPage settings={settings} setSetting={setSetting} ftpRegion={ftpRegion} setFtpRegion={setFtpRegion} currentFtp={currentFtp} updateFtp={updateFtp} chooseDirectory={chooseDirectory} backendToken={backendToken} setBackendToken={setBackendToken} svnPassword={svnPassword} setSvnPassword={setSvnPassword} checkBackend={checkBackend} checkFtp={checkFtp} saveSettings={saveSettings} settingsMessage={settingsMessage} />
        )}
      </main>
      {toast ? <div className={cn("toast", `toast-${toast.tone}`)}><StatusDot status={toast.tone === "success" ? "ok" : toast.tone === "error" ? "error" : "pending"} />{toast.message}</div> : null}
    </div>
  );
}

function ResultCard({ result, groups, selectedGroup, activeGroup, setActiveGroup, details, moduleGroups, activeModule, setActiveModule, overview, validation, onOpenOutput, onOpenReport, onArchive, uploadProgress }) {
  const source = result.package_source || {};
  const riskCount = Number(overview.structural_risk_count || 0);
  const failureCount = Number(result.failure_count || 0);
  const errorCount = Number(validation.error_count || 0) + failureCount;
  const summaryText = Number(validation.error_count || 0) + Number(validation.warning_count || 0) + Number(result.failure_count || 0) ? `发现 ${Number(validation.error_count || 0) + Number(validation.warning_count || 0) + Number(result.failure_count || 0) + riskCount} 项需关注内容` : "当前未发现风险";
  return <Card className="result-card"><div className="result-heading"><div><div className="eyebrow">PACKAGE RESULT</div><h2>内容概况</h2></div><Badge tone={result.test_mode ? "success" : result.can_archive ? "accent" : "danger"} icon={result.test_mode ? FlaskConical : result.can_archive ? CheckCircle2 : CircleAlert}>{result.test_mode ? "测试完成" : result.can_archive ? "待人工确认" : "禁止归档"}</Badge></div><div className="result-summary"><div><span>本次结论</span><strong>{overview.display_lines?.[0] || "未识别到业务内容更新"}</strong><p>{overview.display_lines?.[1] || "所有差异仍会保留在 Report 中。"}</p></div><div className="summary-grid"><div><span>内容来源</span><strong>{source.mode === "historical_revision" ? `历史 r${source.target_revision}` : `本地最新 · HEAD r${source.repository_head_revision || "--"}`}</strong></div><div><span>关联影响</span><strong>{overview.related_activity_count || 0} 项</strong></div><div><span>结构风险</span><strong className={riskCount ? "text-danger" : ""}>{riskCount || "当前未发现"}</strong></div><div><span>校验结论</span><strong className={errorCount ? "text-danger" : ""}>{summaryText}</strong></div></div></div><div className="content-overview"><div className="subheading"><div><span className="eyebrow">BUSINESS OBJECTS</span><h3>核心内容</h3></div><span className="count-pill">{details.length} 项</span></div><div className="content-tabs">{groups.map((group) => <button key={group.id} className={cn(activeGroup === group.id && "active")} onClick={() => setActiveGroup(group.id)}><strong>{group.items.length}</strong><span>{group.label}</span></button>)}</div><div className="content-list">{selectedGroup?.items.length ? selectedGroup.items.map((item, index) => <article className="content-item" key={`${item.object_id || item.activity_id || index}-${index}`}><span className="content-marker">{selectedGroup.label}</span><div><div className="content-item-title"><strong>{[item.object_id || item.activity_id, item.object_name || item.activity_name].filter(Boolean).join(" ") || "未命名内容"}</strong><Badge tone={item.direct_change ? "accent" : "neutral"}>{item.direct_change ? "本次修改" : "关联影响"}</Badge></div><small>{item.activity_type || item.object_type || item.module_name || "业务内容"}</small><p>{(Array.isArray(item.display_lines) ? item.display_lines : []).slice(0, 2).join(" · ") || "已识别该业务对象，完整内容见详情。"}</p></div></article>) : <EmptyState icon={Database} title={`本次没有${selectedGroup?.label || "核心内容"}更新`} description="其他差异仍会记录在 Report 中。" />}</div></div><div className="package-strip"><div><span>归档包</span><strong>{result.package_name}</strong><code>MD5 {result.md5 || "--"}</code></div><div className="metric-row"><div><span>文件</span><strong>{result.success_count || 0}</strong></div><div><span>告警</span><strong className={validation.warning_count ? "text-warning" : ""}>{validation.warning_count || 0}</strong></div><div><span>错误</span><strong className={errorCount ? "text-danger" : ""}>{errorCount}</strong></div></div></div><div className="result-actions"><Button icon={FolderOpen} onClick={onOpenOutput}>打开目录</Button><Button icon={ExternalLink} onClick={onOpenReport}>打开 Report</Button><Button variant="primary" icon={Archive} disabled={!result.can_archive} onClick={onArchive}>确认归档</Button></div>{uploadProgress ? <div className="progress-wrap"><div><span>{uploadProgress.label}</span><strong>{uploadProgress.percent.toFixed(0)}%</strong></div><progress max="100" value={uploadProgress.percent} /></div> : null}<details className="details-panel"><summary><span>内容详情</span><Badge>{details.length} 项 · {moduleGroups.length} 个 Module</Badge></summary>{moduleGroups.length ? <><div className="module-tabs">{moduleGroups.map((group) => <button key={group.id} className={cn((activeModule || moduleGroups[0].id) === group.id && "active")} onClick={() => setActiveModule(group.id)}>{group.name}<span>{group.items.length}</span></button>)}</div><div className="module-details">{moduleGroups.filter((group) => group.id === (activeModule || moduleGroups[0].id)).flatMap((group) => group.items).map((item, index) => <article key={`${item.object_id || item.activity_id || index}-${index}`}><div><strong>{[item.object_id || item.activity_id, item.object_name || item.activity_name].filter(Boolean).join(" ") || "未命名内容"}</strong><span>{item.direct_change ? "直接更新" : "关联影响"}</span></div><small>{item.activity_type || item.module_name || item.object_type || "业务内容"}</small><pre>{Array.isArray(item.display_lines) ? item.display_lines.join("\n") : ""}</pre></article>)}</div></> : <p className="detail-empty">本次没有识别到可解读的业务内容。</p>}</details></Card>;
}

function SettingsPage({ settings, setSetting, ftpRegion, setFtpRegion, currentFtp, updateFtp, chooseDirectory, backendToken, setBackendToken, svnPassword, setSvnPassword, checkBackend, checkFtp, saveSettings, settingsMessage }) {
  return <div className="page-stack settings-page"><div className="page-intro"><div><Badge tone="accent" icon={Settings2}>MACHINE SETTINGS</Badge><h2>把机器差异收进一处配置</h2><p>密码只在当前会话中使用；保存配置不会把 SVN 密码或后端 token 写入磁盘。</p></div><div className="intro-meta"><span>SCHEMA</span><strong>v1</strong></div></div><form onSubmit={saveSettings}><Card><SectionHeading eyebrow="01 · LOCAL DIRECTORIES" title="本地目录" description="打包读取 ServerBytes，DTXML 校验读取 TdrTable/Xml。" /><div className="form-grid"><Field label="ServerBytes 根目录"><div className="path-field"><input value={settings.local_root || ""} onChange={(event) => setSetting("local_root", event.target.value)} /><Button type="button" size="sm" icon={FolderOpen} onClick={() => chooseDirectory("local_root")}>选择</Button></div></Field><Field label="TdrTable 根目录"><div className="path-field"><input value={settings.tdr_root || ""} onChange={(event) => setSetting("tdr_root", event.target.value)} /><Button type="button" size="sm" icon={FolderOpen} onClick={() => chooseDirectory("tdr_root")}>选择</Button></div></Field></div></Card><Card><SectionHeading eyebrow="02 · SUBVERSION" title="SVN 访问" description="使用系统 svn 命令；认证缓存由 SVN 客户端管理。" /><div className="form-grid"><Field label="SVN URL" className="span-2"><input value={settings.svn_target || ""} onChange={(event) => setSetting("svn_target", event.target.value)} /></Field><Field label="SVN 程序"><input value={settings.svn_exe || "svn"} onChange={(event) => setSetting("svn_exe", event.target.value)} /></Field><Field label="用户名"><input value={settings.svn_username || ""} onChange={(event) => setSetting("svn_username", event.target.value)} /></Field><Field label="本次密码" hint="不会保存"><input type="password" value={svnPassword} onChange={(event) => setSvnPassword(event.target.value)} autoComplete="off" /></Field><label className="check-field"><input type="checkbox" checked={settings.use_auth_cache !== false} onChange={(event) => setSetting("use_auth_cache", event.target.checked)} /><span>使用 SVN 登录缓存</span></label></div></Card><Card><SectionHeading eyebrow="03 · ARCHIVE BACKEND" title="归档后端" description="打包完成后由人工确认是否同步，不会自动上传。" /><div className="form-grid backend-grid"><Field label="Backend URL"><input value={settings.backend_url || ""} onChange={(event) => setSetting("backend_url", event.target.value)} /></Field><Field label="访问 Token" hint="当前会话使用"><input type="password" value={backendToken} onChange={(event) => setBackendToken(event.target.value)} autoComplete="off" /></Field><div className="field-action"><Button type="button" icon={Wifi} onClick={checkBackend}>测试连接</Button></div></div></Card><Card><SectionHeading eyebrow="04 · REGIONAL FTP" title="区域 FTP" description="每个区域独立保存主机和远端目录；密码为空时保持原密码。" action={<Segmented value={ftpRegion} onChange={setFtpRegion} options={REGIONS.map((code) => ({ value: code, label: code }))} ariaLabel="FTP 区域" />} /><div className="form-grid"><Field label="主机"><input value={currentFtp.host || ""} onChange={(event) => updateFtp("host", event.target.value)} /></Field><Field label="端口"><input value={currentFtp.port || "21"} onChange={(event) => updateFtp("port", event.target.value)} inputMode="numeric" /></Field><Field label="用户名"><input value={currentFtp.username || ""} onChange={(event) => updateFtp("username", event.target.value)} /></Field><Field label="密码" hint={currentFtp.passwordConfigured ? "已配置，留空保持" : "当前未配置"}><input type="password" value={currentFtp.password || ""} onChange={(event) => updateFtp("password", event.target.value)} autoComplete="new-password" placeholder={currentFtp.passwordConfigured ? "保持原密码" : "输入密码"} /></Field><Field label="远端目录" className="span-2"><input value={currentFtp.remote_directory || "/"} onChange={(event) => updateFtp("remote_directory", event.target.value)} /></Field><label className="check-field"><input type="checkbox" checked={currentFtp.passive !== false} onChange={(event) => updateFtp("passive", event.target.checked)} /><span>被动模式</span></label><div className="field-action"><Button type="button" icon={Wifi} onClick={() => checkFtp(true)}>测试 {ftpRegion} 连接</Button></div></div></Card><Card><SectionHeading eyebrow="05 · PACKAGING POLICY" title="打包策略" description="提交记录和区域过滤会写入 Report，方便审阅与追溯。" /><div className="form-grid"><Field label="打包版本"><input value={settings.package_version || ""} onChange={(event) => setSetting("package_version", event.target.value)} /></Field><Field label="区域范围"><input value={settings.scope_roots || ""} onChange={(event) => setSetting("scope_roots", event.target.value)} /></Field><label className="check-field"><input type="checkbox" checked={settings.enable_commit_check !== false} onChange={(event) => setSetting("enable_commit_check", event.target.checked)} /><span>启用提交记录检查</span></label><label className="check-field"><input type="checkbox" checked={settings.enable_region_filter !== false} onChange={(event) => setSetting("enable_region_filter", event.target.checked)} /><span>启用区域文件过滤</span></label><Field label="提交白名单" className="span-2"><textarea value={settings.commit_whitelist || ""} onChange={(event) => setSetting("commit_whitelist", event.target.value)} rows={5} /></Field></div></Card><div className="settings-actions"><span className={settingsMessage === "配置已保存" ? "text-success" : "text-muted"}>{settingsMessage}</span><Button variant="primary" icon={Save} type="submit">保存配置</Button></div></form></div>;
}
