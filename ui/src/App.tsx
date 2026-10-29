import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import {
  Activity,
  Cable,
  KeyRound,
  ScrollText,
  Settings as SettingsIcon,
  Waypoints,
} from "lucide-react";
import { api } from "./api";
import { ToastProvider } from "./components";
import type { Health } from "./types";
import Overview from "./pages/Overview";
import Connections from "./pages/Connections";
import Combos from "./pages/Combos";
import Keys from "./pages/Keys";
import Requests from "./pages/Requests";
import RequestDetail from "./pages/RequestDetail";
import Settings from "./pages/Settings";

const NAV = [
  { to: "/", label: "Overview", icon: Activity, end: true },
  { to: "/connections", label: "Connections", icon: Cable },
  { to: "/combos", label: "Combos", icon: Waypoints },
  { to: "/keys", label: "API keys", icon: KeyRound },
  { to: "/requests", label: "Requests", icon: ScrollText },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

function Sidebar() {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    api
      .get<Health>("/admin/api/health")
      .then(setHealth)
      .catch(() => undefined);
  }, []);

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">F</div>
        <div>
          <div className="brand-name">FlashRouter</div>
          <div className="brand-sub">OpenAI-compatible router</div>
        </div>
      </div>
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
        >
          <Icon size={17} />
          {label}
        </NavLink>
      ))}
      <div className="sidebar-foot">
        <span>API base · /v1</span>
        <span>{health ? `v${health.version}` : "connecting…"}</span>
      </div>
    </aside>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <div className="app-shell">
        <Sidebar />
        <main className="main">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/connections" element={<Connections />} />
            <Route path="/combos" element={<Combos />} />
            <Route path="/keys" element={<Keys />} />
            <Route path="/requests" element={<Requests />} />
            <Route path="/requests/:id" element={<RequestDetail />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Overview />} />
          </Routes>
        </main>
      </div>
    </ToastProvider>
  );
}
