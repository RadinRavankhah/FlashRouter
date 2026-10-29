import { api } from "./api";
import { AreaChart, Card, Donut, PageHeader, Skeleton, StatCard, compact, money, pct, useAsync } from "./components";
import { RequestTable } from "./pages";

const PALETTE = ["#7c8cff", "#b67cff", "#34d399", "#fbbf24", "#fb7185", "#38bdf8"];

export function OverviewPage() {
  const { data } = useAsync(() => api.overview(), []);
  if (!data) return (<><PageHeader title="Overview" subtitle="Loading gateway activity…" /><Skeleton /></>);

  const total = data.recent.reduce((s, m) => s + (m.cost ?? 0), 0);
  const hasData = data.recent.length > 0;

  return (
    <>
      <PageHeader title="Overview" subtitle="Spend, usage and reliability at a glance" />
      <div className="grid stats">
        <StatCard tone="accent" label="Spend this month" value={data.spendMonth === null ? "—" : money(data.spendMonth)} hint={`${data.spendToday === null ? "—" : money(data.spendToday)} today`} spark={data.daily.map((d) => d.value)} />
        <StatCard label="Input tokens" value={data.inputTokens === null ? "—" : compact(data.inputTokens)} hint={`${data.outputTokens === null ? "—" : compact(data.outputTokens)} output`} />
        <StatCard label="Cache-read share" value={data.cacheReadFraction === null ? "Unknown" : pct(data.cacheReadFraction)} hint="of eligible input tokens" />
        <StatCard label="Success rate" value={data.recent.length === 0 ? "—" : pct(data.successRate)} hint={`${data.active} request(s) in flight`} />
        <StatCard label="Budget remaining" value={data.budgetRemaining === null ? "—" : money(data.budgetRemaining)} hint="across gateway keys" />
      </div>
      <div className="grid overview-charts">
        {hasData ? (
          <Card title="Spend · last 14 days" action={<span className="muted small">reported + estimated</span>}>
            <AreaChart data={data.daily} format={money} />
          </Card>
        ) : (
          <Card title="Spend · last 14 days">No requests logged yet.</Card>
        )}
        {hasData ? (
          <Card title="Cost by model">
            <Donut
              slices={data.modelShare.map((m, i) => ({ label: m.model, value: m.cost, color: PALETTE[i % PALETTE.length] }))}
              center={money(total)}
              format={money}
            />
          </Card>
        ) : (
          <Card title="Cost by model">No requests logged yet.</Card>
        )}
      </div>
      <Card title="Recent requests" className="table-card">
        <RequestTable rows={data.recent} />
      </Card>
    </>
  );
}
