import { api } from "./api";
import { AreaChart, Card, Donut, PageHeader, Skeleton, StatCard, compact, money, pct, useAsync } from "./components";
import { RequestTable } from "./pages";

const PALETTE = ["#7c8cff", "#b67cff", "#34d399", "#fbbf24", "#fb7185", "#38bdf8"];

export function OverviewPage() {
  const { data } = useAsync(() => api.overview(), []);
  if (!data) return (<><PageHeader title="Overview" subtitle="Loading gateway activity…" /><Skeleton /></>);

  const total = data.modelShare.reduce((s, m) => s + m.cost, 0);

  return (
    <>
      <PageHeader title="Overview" subtitle="Spend, usage and reliability at a glance" />
      <div className="grid stats">
        <StatCard tone="accent" label="Spend this month" value={money(data.spendMonth)} hint={`${money(data.spendToday)} today`} spark={data.daily.map((d) => d.value)} />
        <StatCard label="Input tokens" value={compact(data.inputTokens)} hint={`${compact(data.outputTokens)} output`} />
        <StatCard label="Cache-read share" value={data.cacheReadFraction === null ? "Unknown" : pct(data.cacheReadFraction)} hint="of eligible input tokens" />
        <StatCard label="Success rate" value={pct(data.successRate)} hint={`${data.active} request(s) in flight`} />
        <StatCard label="Budget remaining" value={money(data.budgetRemaining)} hint="across gateway keys" />
      </div>
      <div className="grid overview-charts">
        <Card title="Spend · last 14 days" action={<span className="muted small">reported + estimated</span>}>
          <AreaChart data={data.daily} format={money} />
        </Card>
        <Card title="Cost by model">
          <Donut
            slices={data.modelShare.map((m, i) => ({ label: m.model, value: m.cost, color: PALETTE[i % PALETTE.length] }))}
            center={money(total)}
            format={money}
          />
        </Card>
      </div>
      <Card title="Recent requests" className="table-card">
        <RequestTable rows={data.recent} />
      </Card>
    </>
  );
}
