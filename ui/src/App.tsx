import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { GitBranch, KeyRound, LayoutDashboard, Moon, ScrollText, Server, Settings as SettingsIcon, Sun } from "lucide-react";
import { OverviewPage } from "./overview";
import { SetupPage, ProvidersPage, CredentialsPage, KeysPage, RequestsPage, SettingsPage, RoutesPage } from "./pages";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/requests", label: "Requests", icon: ScrollText, end: false },
  { to: "/keys", label: "Gateway keys", icon: KeyRound, end: false },
  { to: "/providers", label: "Providers", icon: Server, end: false },
  { to: "/credentials", label: "Credentials", icon: KeyRound, end: false },
  { to: "/routes", label: "Models & aliases", icon: GitBranch, end: false },
  { to: "/settings", label: "Settings", icon: SettingsIcon, end: false },
];

export default function App() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [configured, setConfigured] = useState<boolean | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    fetch("/admin/setup/status")
      .then((r) => r.json())
      .then((s) => {
        setConfigured(s.configured);
        if (!s.configured && window.location.pathname !== "/setup") {
          navigate("/setup");
        }
      });
  }, [navigate]);

  if (configured === null) {
    return (
      <div className="app">
        <div style={{ padding: "40px", textAlign: "center" }}>Loading…</div>
      </div>
    );
  }

  if (configured === false) {
    return <SetupPage />;
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="logo">G</div>
          <div>
            <div className="brand-name">Gateway</div>
            <div className="brand-sub">local LLM proxy</div>
          </div>
        </div>

        <nav>
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className="nav-link">
              <Icon size={18} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div><span className="live-dot" />Proxy running</div>
          <div className="small">127.0.0.1:8787</div>
          <button className="ghost theme-toggle" onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}>
            {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
            <span>{theme === "dark" ? "Light" : "Dark"} mode</span>
          </button>
        </div>
      </aside>

      <main className="main">
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/requests" element={<RequestsPage />} />
          <Route path="/keys" element={<KeysPage />} />
          <Route path="/providers" element={<ProvidersPage />} />
          <Route path="/credentials" element={<CredentialsPage />} />
          <Route path="/routes" element={<RoutesPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
