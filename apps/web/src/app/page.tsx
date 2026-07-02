"use client";

import { signOut, useSession } from "next-auth/react";
import Image from "next/image";
import { useMemo, useState } from "react";

type PeriodKey =
  | "today"
  | "yesterday"
  | "last_7_days"
  | "last_14_days"
  | "last_15_days"
  | "last_30_days"
  | "last_3_months"
  | "last_6_months"
  | "this_month"
  | "last_month"
  | "this_quarter"
  | "this_year"
  | "last_year"
  | "all_time"
  | "custom";

type DashboardPeriod = {
  signups?: number;
  uploads?: number;
  paid?: number;
  revenue?: number;
  signup_pct?: number;
  upload_pct?: number;
  paid_pct?: number;
  revenue_pct?: number;
  linkedin_posts?: number;
  youtube_videos?: number;
  linkedin_followers?: number;
};

type SummaryResponse = {
  success: boolean;
  source: string;
  data: Record<string, DashboardPeriod>;
};

type YoutubeVideo = {
  title?: string;
  name?: string;
  views?: number;
  view_count?: number;
};

type YoutubeResponse = {
  success?: boolean;
  video_count?: number;
  top_videos?: YoutubeVideo[];
};

type LinkedInPost = {
  title?: string;
  text?: string;
  impressions?: number;
};

type LinkedInResponse = {
  success?: boolean;
  post_count?: number;
  top_posts?: LinkedInPost[];
};

type FeatureStatus = "live" | "needs_oauth" | "not_migrated";

type FeatureItem = {
  name: string;
  status: FeatureStatus;
};

type FeatureRegistryResponse = {
  success: boolean;
  modules: Record<string, {
    icon: string;
    features: FeatureItem[];
  }>;
};

type CustomerSuccessResponse = {
  success?: boolean;
  customer_success_master?: number;
  customer_success_enriched?: number;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8080";

const nav = [
  "Dashboard",
  "KPI",
  "Google Analytics",
  "YouTube",
  "LinkedIn",
  "Customer Success",
  "Cross-Platform",
  "AI & Insights",
  "Custom Modules",
  "Reports",
  "Settings",
];

const periods: { label: string; value: PeriodKey; mapped: string }[] = [
  { label: "Today", value: "today", mapped: "this_month" },
  { label: "Yesterday", value: "yesterday", mapped: "last_month" },
  { label: "Last 7 Days", value: "last_7_days", mapped: "last_month" },
  { label: "Last 14 Days", value: "last_14_days", mapped: "last_month" },
  { label: "Last 15 Days", value: "last_15_days", mapped: "last_month" },
  { label: "Last 30 Days", value: "last_30_days", mapped: "last_month" },
  { label: "Last 3 Months", value: "last_3_months", mapped: "this_year" },
  { label: "Last 6 Months", value: "last_6_months", mapped: "this_year" },
  { label: "This Month", value: "this_month", mapped: "this_month" },
  { label: "Last Month", value: "last_month", mapped: "last_month" },
  { label: "This Quarter", value: "this_quarter", mapped: "this_year" },
  { label: "This Year", value: "this_year", mapped: "this_year" },
  { label: "Last Year", value: "last_year", mapped: "last_year" },
  { label: "All Time", value: "all_time", mapped: "all_time" },
  { label: "Custom Range", value: "custom", mapped: "last_month" },
];

function fmtNum(v?: number) {
  return new Intl.NumberFormat("en-US").format(v || 0);
}

function fmtMoney(v?: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(v || 0);
}


function FeatureGrid({
  moduleName,
  features,
}: {
  moduleName: string;
  features: FeatureRegistryResponse | null;
}) {
  const featureModule = features?.modules?.[moduleName];

  if (!featureModule) {
    return null;
  }

  return (
    <section className="panel" style={{ marginTop: 18 }}>
      <div className="panel-head">
        <h3>{featureModule.icon} {moduleName} Features</h3>
        <span>{featureModule.features.length} subfeatures</span>
      </div>

      <div className="stack">
        {featureModule.features.map((item) => (
          <div key={item.name}>
            <span>
              {item.status === "live"
                ? "Live"
                : item.status === "needs_oauth"
                ? "Needs OAuth"
                : "Migration Pending"}
            </span>
            <b>{item.name}</b>
          </div>
        ))}
      </div>
    </section>
  );
}


function MetricCard({
  label,
  value,
  delta,
  code,
}: {
  label: string;
  value: string;
  delta?: number;
  code: string;
}) {
  const up = Number(delta || 0) >= 0;

  return (
    <div className="metric-card">
      <div className="metric-top">
        <span>{label}</span>
        <b>{code}</b>
      </div>
      <div className="metric-value">{value}</div>
      {delta !== undefined ? (
        <div className="metric-delta">
          <span className={up ? "up" : "down"}>
            {up ? "+" : ""}
            {Number(delta).toFixed(1)}%
          </span>{" "}
          vs previous
        </div>
      ) : null}
    </div>
  );
}

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`/api/backend${path}`, { cache: "no-store" });

  if (!res.ok) {
    throw new Error(await res.text());
  }

  return res.json() as Promise<T>;
}

export default function Home() {
  const { data: session, status } = useSession();

  const [active, setActive] = useState("Dashboard");
  const [period, setPeriod] = useState<PeriodKey>("last_month");
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [youtube, setYoutube] = useState<YoutubeResponse | null>(null);
  const [linkedin, setLinkedin] = useState<LinkedInResponse | null>(null);
  const [cs, setCs] = useState<CustomerSuccessResponse | null>(null);
  const [ga4Module, setGa4Module] = useState<Record<string, unknown> | null>(null);
  const [crossModule, setCrossModule] = useState<Record<string, unknown> | null>(null);
  const [customModule, setCustomModule] = useState<Record<string, unknown> | null>(null);
  const [settingsModule, setSettingsModule] = useState<Record<string, unknown> | null>(null);
  const [features, setFeatures] = useState<FeatureRegistryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");

  async function loadData() {
    setLoading(true);
    setLoadError("");

    try {
      const [
        summaryData,
        youtubeData,
        linkedinData,
        csData,
        ga4Data,
        crossData,
        customData,
        settingsData,
        featureData,
      ] = await Promise.all([
        apiFetch<SummaryResponse>("/api/v1/dashboard/summary"),
        apiFetch<YoutubeResponse>("/api/v1/youtube/overview"),
        apiFetch<LinkedInResponse>("/api/v1/linkedin/overview"),
        apiFetch<CustomerSuccessResponse>("/api/v1/customer-success/overview"),
        apiFetch<Record<string, unknown>>("/api/v1/ga4/overview"),
        apiFetch<Record<string, unknown>>("/api/v1/cross-platform/overview"),
        apiFetch<Record<string, unknown>>("/api/v1/custom-modules"),
        apiFetch<Record<string, unknown>>("/api/v1/settings/overview"),
        apiFetch<FeatureRegistryResponse>("/api/v1/features"),
      ]);

      setSummary(summaryData);
      setYoutube(youtubeData);
      setLinkedin(linkedinData);
      setCs(csData);
      setGa4Module(ga4Data);
      setCrossModule(crossData);
      setCustomModule(customData);
      setSettingsModule(settingsData);
      setFeatures(featureData);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Unknown backend error");
    } finally {
      setLoading(false);
    }
  }

  const mapped = periods.find((p) => p.value === period)?.mapped || "last_month";
  const data: DashboardPeriod = summary?.data?.[mapped] || {};

  const trend = useMemo(() => {
    const d = summary?.data || {};
    return ["last_year", "this_year", "last_month", "this_month"].map((key) => ({
      label: key.replace("_", " "),
      signups: d[key]?.signups || 0,
    }));
  }, [summary]);

  const maxTrend = Math.max(1, ...trend.map((x) => x.signups));


  if (status === "loading") {
    return (
      <main className="login-shell">
        <section className="login-card">
          <h1>Eagle Analytics Hub</h1>
          <p>Checking secure session...</p>
        </section>
      </main>
    );
  }

  if (!session?.user?.email) {
    return (
      <main className="login-shell">
        <section className="login-card">
          <h1>Eagle Analytics Hub</h1>
          <p>Your session is not active. Please go to the login page.</p>
          <a className="primary-button" href="/login" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", textDecoration: "none", marginTop: 16 }}>
            Go to Login
          </a>
        </section>
      </main>
    );
  }

  return (
    <main className="hub-shell">
      <aside className="sidebar">
        <div className="brand">
          <Image src="/brand/eagle-logo.png" alt="Eagle3D logo" width={52} height={52} />
          <div>
            <h1>Eagle Analytics Hub</h1>
            <p>Unified command center</p>
          </div>
        </div>

        <nav className="nav">
          {nav.map((item) => (
            <button
              key={item}
              onClick={() => setActive(item)}
              className={active === item ? "active" : ""}
            >
              <code>{item.slice(0, 2)}</code>
              {item}
            </button>
          ))}
        </nav>

        <div className="sidebar-status">
          <strong>
            <i /> MongoDB Live
          </strong>
          <p>FastAPI backend connected to Eagle3D source data.</p>
        </div>
      </aside>

      <section className="main">
        <div className="mobile-nav">
          {nav.map((item) => (
            <button
              key={item}
              onClick={() => setActive(item)}
              className={active === item ? "active" : ""}
            >
              {item}
            </button>
          ))}
        </div>

        <header className="header">
          <div>
            <p className="eyebrow">Eagle3D Streaming</p>
            <h2>{active}</h2>
            <p>
              Enterprise analytics for KPI, GA4, YouTube, LinkedIn, Customer
              Success, and cross-platform growth.
            </p>
          </div>

          <div className="header-actions">
            <select
              className="select"
              value={period}
              onChange={(e) => setPeriod(e.target.value as PeriodKey)}
            >
              {periods.map((p) => (
                <option value={p.value} key={p.value}>
                  {p.label}
                </option>
              ))}
            </select>

            <button className="primary-button" onClick={loadData} disabled={loading}>
              {loading ? "Loading..." : "Load Data"}
            </button>

            <button className="secondary-button" onClick={() => signOut({ callbackUrl: "/login" })}>
              Logout
            </button>
          </div>
        </header>

        <section className="content">
          {!summary && !loadError ? (
            <div className="welcome-panel">
              <p className="eyebrow">Welcome</p>
              <h3>Command your growth data from one place.</h3>
              <p>
                Designed in Eagle3D’s premium dark product language. Load live
                MongoDB analytics from your FastAPI backend.
              </p>
              <button className="primary-button" onClick={loadData}>
                Load Dashboard Data
              </button>
            </div>
          ) : null}

          {loadError ? (
            <div className="error-panel">
              <b>Backend API error</b>
              <p>{loadError}</p>
              <small>Make sure FastAPI is running on {API_BASE}.</small>
            </div>
          ) : null}

          {summary ? (
            <>
              {(active === "Dashboard" || active === "KPI") && (
                <>
                  <div className="metric-grid">
                    <MetricCard label="Revenue" value={fmtMoney(data.revenue)} delta={data.revenue_pct} code="$" />
                    <MetricCard label="Verified Signups" value={fmtNum(data.signups)} delta={data.signup_pct} code="SU" />
                    <MetricCard label="Project Uploads" value={fmtNum(data.uploads)} delta={data.upload_pct} code="UP" />
                    <MetricCard label="Paid Customers" value={fmtNum(data.paid)} delta={data.paid_pct} code="PC" />
                  </div>

                  <div className="dashboard-grid">
                    <section className="panel">
                      <div className="panel-head">
                        <h3>Business Performance</h3>
                        <span>{periods.find((p) => p.value === period)?.label}</span>
                      </div>

                      <div className="bar-list">
                        {trend.map((row) => (
                          <div className="bar-row" key={row.label}>
                            <div className="bar-meta">
                              <b>{row.label}</b>
                              <span>{fmtNum(row.signups)} signups</span>
                            </div>
                            <div className="track">
                              <i style={{ width: `${Math.max(4, (row.signups / maxTrend) * 100)}%` }} />
                            </div>
                          </div>
                        ))}
                      </div>
                    </section>

                    <section className="panel">
                      <div className="panel-head">
                        <h3>Platform Data</h3>
                        <span>Live</span>
                      </div>

                      <div className="stack">
                        <div><span>YouTube Videos</span><b>{fmtNum(youtube?.video_count || data.youtube_videos)}</b></div>
                        <div><span>LinkedIn Posts</span><b>{fmtNum(linkedin?.post_count || data.linkedin_posts)}</b></div>
                        <div><span>LinkedIn Followers</span><b>{fmtNum(data.linkedin_followers)}</b></div>
                        <div><span>Customer Records</span><b>{fmtNum(cs?.customer_success_master || 0)}</b></div>
                      </div>
                    </section>
                  </div>
                </>
              )}

              {active === "YouTube" && (
                <section className="panel">
                  <div className="panel-head">
                    <h3><span className="brand-pill yt">YT</span> YouTube Videos</h3>
                    <span>{fmtNum(youtube?.video_count || 0)} videos</span>
                  </div>
                  <div className="item-list">
                    {(youtube?.top_videos || []).map((v, i) => (
                      <div key={`${v.title || i}`}>
                        <b>{v.title || v.name || "Untitled"}</b>
                        <span>{fmtNum(v.views || v.view_count || 0)} views</span>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {active === "LinkedIn" && (
                <section className="panel">
                  <div className="panel-head">
                    <h3><span className="brand-pill li">in</span> LinkedIn Posts</h3>
                    <span>{fmtNum(linkedin?.post_count || 0)} posts</span>
                  </div>
                  <div className="item-list">
                    {(linkedin?.top_posts || []).map((p, i) => (
                      <div key={`${p.title || p.text || i}`}>
                        <b>{p.title || p.text || "LinkedIn Post"}</b>
                        <span>{fmtNum(p.impressions || 0)} impressions</span>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {active === "Customer Success" && (
                <section className="panel">
                  <div className="panel-head">
                    <h3>Customer Success</h3>
                    <span>MongoDB</span>
                  </div>
                  <div className="metric-grid">
                    <MetricCard label="Master Records" value={fmtNum(cs?.customer_success_master)} code="CS" />
                    <MetricCard label="Enriched Records" value={fmtNum(cs?.customer_success_enriched)} code="EN" />
                    <MetricCard label="Paid Customers" value={fmtNum(data.paid)} code="PC" />
                    <MetricCard label="Revenue" value={fmtMoney(data.revenue)} code="$" />
                  </div>
                </section>
              )}

              {active === "Google Analytics" && (
                <section className="panel">
                  <div className="panel-head">
                    <h3>Google Analytics 4</h3>
                    <span>{String(ga4Module?.status ? "Configured" : "Needs setup")}</span>
                  </div>
                  <div className="stack">
                    {["Traffic Overview", "Pages", "Events", "Countries", "Devices", "Channels", "Strategic QA"].map((x) => (
                      <div key={x}>
                        <span>GA4 Module</span>
                        <b>{x}</b>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {active === "Cross-Platform" && (
                <section className="panel">
                  <div className="panel-head">
                    <h3>Cross-Platform Intelligence</h3>
                    <span>Unified</span>
                  </div>
                  <div className="metric-grid">
                    <MetricCard label="Timeline Days" value={fmtNum(Number(crossModule?.timeline_days || 0))} code="TL" />
                    <MetricCard label="YouTube Videos" value={fmtNum(Number((crossModule?.platforms as Record<string, number> | undefined)?.youtube_videos || 0))} code="YT" />
                    <MetricCard label="LinkedIn Posts" value={fmtNum(Number((crossModule?.platforms as Record<string, number> | undefined)?.linkedin_posts || 0))} code="LI" />
                    <MetricCard label="Customers" value={fmtNum(Number((crossModule?.platforms as Record<string, number> | undefined)?.customer_records || 0))} code="CS" />
                  </div>
                  <div className="stack" style={{ marginTop: 18 }}>
                    {["Unified Timeline", "Correlations", "Attribution", "Funnel", "Growth", "Insights"].map((x) => (
                      <div key={x}><span>Analysis Section</span><b>{x}</b></div>
                    ))}
                  </div>
                </section>
              )}

              {active === "AI & Insights" && (
                <section className="panel">
                  <div className="panel-head">
                    <h3>AI & Insights</h3>
                    <span>Assistant modules</span>
                  </div>
                  <div className="stack">
                    {["Ask AI", "AI KPI", "AI YouTube", "AI LinkedIn", "AI GA4", "AI Customer Success", "Predictions", "AI Tools"].map((x) => (
                      <div key={x}><span>AI Module</span><b>{x}</b></div>
                    ))}
                  </div>
                </section>
              )}

              {active === "Custom Modules" && (
                <section className="panel">
                  <div className="panel-head">
                    <h3>Custom Modules</h3>
                    <span>{Array.isArray(customModule?.modules) ? customModule.modules.length : 0} active</span>
                  </div>
                  {Array.isArray(customModule?.modules) && customModule.modules.length > 0 ? (
                    <div className="stack">
                      {customModule.modules.map((m, i) => {
                        const mod = m as Record<string, unknown>;
                        return <div key={i}><span>{String(mod.team || "Team Module")}</span><b>{String(mod.name || mod.slug || "Custom Module")}</b></div>;
                      })}
                    </div>
                  ) : (
                    <p style={{ color: "var(--soft)", lineHeight: 1.7 }}>
                      No custom modules yet. Create modules from Settings in the backend system, upload sheets, and they will appear here.
                    </p>
                  )}
                </section>
              )}

              {active === "Reports" && (
                <section className="panel">
                  <div className="panel-head">
                    <h3>Reports</h3>
                    <span>Exports & summaries</span>
                  </div>
                  <div className="stack">
                    <div><span>Report Type</span><b>KPI Executive Summary</b></div>
                    <div><span>Report Type</span><b>Cross-Platform Growth Report</b></div>
                    <div><span>Report Type</span><b>Customer Success Report</b></div>
                    <div><span>Report Type</span><b>YouTube / LinkedIn Performance Report</b></div>
                  </div>
                </section>
              )}

              {active === "Settings" && (
                <section className="panel">
                  <div className="panel-head">
                    <h3>Settings</h3>
                    <span>System control</span>
                  </div>
                  <div className="metric-grid">
                    <MetricCard label="Access Users" value={fmtNum(Number(settingsModule?.access_users || 0))} code="AU" />
                    <MetricCard label="Access Logs" value={fmtNum(Number(settingsModule?.access_logs || 0))} code="LG" />
                    <MetricCard label="API Logs" value={fmtNum(Number(settingsModule?.api_ingest_logs || 0))} code="API" />
                    <MetricCard label="Auth Mode" value="Google OAuth Pending" code="SSO" />
                  </div>
                </section>
              )}

              <FeatureGrid moduleName={active} features={features} />

              <footer className="footer">
                Eagle Analytics Hub · Eagle3D Streaming · Live MongoDB source · FastAPI backend
              </footer>
            </>
          ) : null}
        </section>
      </section>
    </main>
  );
}
