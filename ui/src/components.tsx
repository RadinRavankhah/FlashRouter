import { useEffect, useState, type MouseEvent, type ReactNode } from "react";

export const money = (n: number | null) =>
  n === null ? "—" : n !== 0 && n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`;
export const compact = (n: number) =>
  new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);
export const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
export const fmtTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

export function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<{ data: T | null; error: string | null }>({ data: null, error: null });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    loader()
      .then((data) => alive && setState({ data, error: null }))
      .catch((e) => alive && setState({ data: null, error: String(e) }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { ...state, reload: () => setTick((t) => t + 1) };
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="header-actions">{actions}</div>}
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

export function Field({ label, hint, className = "", children }: { label: string; hint?: string; className?: string; children: ReactNode }) {
  return (
    <label className={`field ${className}`}>
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export function Modal({ title, subtitle, onClose, children }: { title: string; subtitle?: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" onMouseDown={(e) => e.stopPropagation()}>
        <header>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </header>
        {children}
      </div>
    </div>
  );
}

export function StatCard({ label, value, hint, tone, spark }: { label: string; value: string; hint?: string; tone?: "accent"; spark?: number[] }) {
  return (
    <div className={`card stat ${tone ?? ""}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint && <div className="hint">{hint}</div>}
      {spark && spark.length > 1 && <Sparkline values={spark} />}
    </div>
  );
}

// Catmull-Rom style cubic path through points: smooth curves without a charting library.
function smoothPath(p: [number, number][]) {
  if (p.length < 2) return "";
  let d = `M ${p[0][0]} ${p[0][1]}`;
  for (let i = 0; i < p.length - 1; i++) {
    const p0 = p[i - 1] ?? p[i];
    const p1 = p[i];
    const p2 = p[i + 1];
    const p3 = p[i + 2] ?? p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C ${c1x} ${c1y}, ${c2x} ${c2y}, ${p2[0]} ${p2[1]}`;
  }
  return d;
}

function niceMax(v: number) {
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const s = v / p;
  const step = s <= 1 ? 1 : s <= 2 ? 2 : s <= 5 ? 5 : 10;
  return step * p;
}

export function Sparkline({ values }: { values: number[] }) {
  const W = 200;
  const H = 40;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const pts = values.map((v, i) => [(i / (values.length - 1)) * W, H - 3 - ((v - min) / (max - min || 1)) * (H - 6)] as [number, number]);
  const line = smoothPath(pts);
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
      <path d={`${line} L ${W} ${H} L 0 ${H} Z`} className="spark-area" />
      <path d={line} className="spark-line" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function AreaChart({ data, format, height = 260 }: { data: { label: string; value: number }[]; format: (n: number) => string; height?: number }) {
  const W = 640;
  const H = height;
  const PL = 56;
  const PR = 16;
  const PT = 20;
  const PB = 32;
  const n = data.length;
  const [hover, setHover] = useState<number | null>(null);

  const top = niceMax(Math.max(...data.map((d) => d.value), 0.01));
  const xAt = (i: number) => PL + (n > 1 ? (i / (n - 1)) * (W - PL - PR) : 0);
  const yAt = (v: number) => PT + (1 - v / top) * (H - PT - PB);
  const points = data.map((d, i) => [xAt(i), yAt(d.value)] as [number, number]);
  const line = smoothPath(points);
  const baseY = H - PB;
  const area = n > 1 ? `${line} L ${xAt(n - 1)} ${baseY} L ${xAt(0)} ${baseY} Z` : "";

  const onMove = (e: MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    const i = Math.round(((px - PL) / (W - PL - PR)) * (n - 1));
    setHover(Math.min(n - 1, Math.max(0, i)));
  };

  const h = hover ?? n - 1;
  const hp = points[h];

  return (
    <div className="area-chart">
      <svg viewBox={`0 0 ${W} ${H}`} onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img" aria-label="Spend over time">
        <defs>
          <linearGradient id="areaFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#7c8cff" stopOpacity="0.32" />
            <stop offset="100%" stopColor="#b67cff" stopOpacity="0" />
          </linearGradient>
          <linearGradient id="areaStroke" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stopColor="#7c8cff" />
            <stop offset="100%" stopColor="#b67cff" />
          </linearGradient>
        </defs>
        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const v = top * f;
          const y = yAt(v);
          return (
            <g key={f}>
              <line className="grid-line" x1={PL} x2={W - PR} y1={y} y2={y} />
              <text className="axis" x={PL - 10} y={y + 4} textAnchor="end">{format(v)}</text>
            </g>
          );
        })}
        {n > 1 && <path d={area} fill="url(#areaFill)" />}
        {n > 1 && <path d={line} fill="none" stroke="url(#areaStroke)" strokeWidth={2.5} strokeLinecap="round" />}
        {data.map((d, i) =>
          i % 2 === 0 || i === n - 1 ? (
            <text key={d.label + i} className="axis" x={xAt(i)} y={H - 8} textAnchor="middle">{d.label}</text>
          ) : null
        )}
        {hp && (
          <g>
            <line className="cursor" x1={hp[0]} x2={hp[0]} y1={PT} y2={baseY} />
            <circle cx={hp[0]} cy={hp[1]} r={5.5} className="dot" />
          </g>
        )}
      </svg>
      {hp && data[h] && (
        <div className="tip" style={{ left: `${(hp[0] / W) * 100}%`, top: `${(hp[1] / H) * 100}%` }}>
          <span>{data[h].label}</span>
          <strong>{format(data[h].value)}</strong>
        </div>
      )}
    </div>
  );
}

export function Donut({ slices, center, format }: { slices: { label: string; value: number; color: string }[]; center: string; format: (n: number) => string }) {
  const R = 54;
  const C = 2 * Math.PI * R;
  const total = slices.reduce((s, x) => s + x.value, 0);
  let acc = 0;
  return (
    <div className="donut">
      <div className="donut-ring">
        <svg viewBox="0 0 140 140" aria-hidden>
          <circle cx="70" cy="70" r={R} className="ring-track" />
          {total > 0 &&
            slices.map((s) => {
              const len = (s.value / total) * C;
              const el = (
                <circle
                  key={s.label}
                  cx="70"
                  cy="70"
                  r={R}
                  className="ring-seg"
                  stroke={s.color}
                  strokeDasharray={`${Math.max(len - 2, 0)} ${C}`}
                  strokeDashoffset={-acc}
                  transform="rotate(-90 70 70)"
                />
              );
              acc += len;
              return el;
            })}
        </svg>
        <div className="donut-center">
          <strong>{center}</strong>
          <span>total</span>
        </div>
      </div>
      <ul className="legend">
        {slices.map((s) => (
          <li key={s.label}>
            <span className="swatch" style={{ background: s.color }} />
            <span className="legend-label">{s.label}</span>
            <span className="muted small num">{format(s.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
