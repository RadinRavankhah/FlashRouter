import { useEffect, useState, type ReactNode } from "react";

export const money = (n: number | null) =>
  n === null ? "—" : n !== 0 && n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`;
export const compact = (n: number) =>
  new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);
export const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
export const fmtTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

export function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<{ data: T | null; error: string | null }>({ data: null, error: null });
  useEffect(() => {
    let alive = true;
    loader()
      .then((data) => alive && setState({ data, error: null }))
      .catch((e) => alive && setState({ data: null, error: String(e) }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions}
    </header>
  );
}

export function Card({ title, action, children, className = "" }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || action) && (
        <div className="card-head">
          <h3>{title}</h3>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Badge({ tone, children }: { tone: "success" | "warning" | "danger" | "neutral" | "accent"; children: ReactNode }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function StatCard({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "accent" }) {
  return (
    <div className={`card stat ${tone ?? ""}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

export function ProgressBar({ value, max, tone }: { value: number; max: number; tone?: "warning" | "danger" }) {
  const width = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="bar">
      <span className={tone} style={{ width: `${width}%` }} />
    </div>
  );
}

export function Skeleton() {
  return <div className="skeleton" />;
}

export function BarChart({ data, format }: { data: { label: string; value: number }[]; format: (n: number) => string }) {
  const W = 600;
  const H = 220;
  const PAD = 28;
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...data.map((d) => d.value), 1);
  const slot = (W - PAD * 2) / Math.max(data.length, 1);
  const active = hover ?? data.length - 1;

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Spend over time">
        <defs>
          <linearGradient id="barFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#b67cff" />
            <stop offset="1" stopColor="#7c8cff" />
          </linearGradient>
        </defs>
        {data.map((d, i) => {
          const h = (d.value / max) * (H - PAD * 2);
          const x = PAD + i * slot + slot * 0.18;
          return (
            <g key={d.label + i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={x} y={H - PAD - h} width={slot * 0.64} height={h} rx={6} fill="url(#barFill)" opacity={i === active ? 1 : 0.4} />
              {i % 2 === 0 && <text x={x + slot * 0.32} y={H - 8} textAnchor="middle">{d.label}</text>}
            </g>
          );
        })}
      </svg>
      <div className="chart-meta">{data[active] ? `${data[active].label} · ${format(data[active].value)}` : ""}</div>
    </div>
  );
}
