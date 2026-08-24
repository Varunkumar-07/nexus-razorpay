import { useEffect, useState } from "react";
import { metricsSummary } from "../api";

function formatRupees(amount) {
  return `Rs.${amount.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatPercent(fraction) {
  return `${(fraction * 100).toFixed(1)}%`;
}

function StatCard({ label, value, sublabel }) {
  return (
    <div className="stat-card">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {sublabel && <div className="stat-sublabel">{sublabel}</div>}
    </div>
  );
}

export default function StatsView() {
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    metricsSummary()
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <main className="stats">
        <p className="loading">Couldn't load metrics. Is the server running?</p>
      </main>
    );
  }

  if (!summary) {
    return (
      <main className="stats">
        <p className="loading">Loading metrics…</p>
      </main>
    );
  }

  const { chat, agent } = summary.by_source;

  return (
    <main className="stats">
      <section className="stat-grid">
        <StatCard label="Total Orders" value={summary.total_orders} />
        <StatCard label="Total Revenue" value={formatRupees(summary.total_revenue_rupees)} />
        <StatCard label="Average Order Value" value={formatRupees(summary.average_order_value_rupees)} />
        <StatCard
          label="Upsell Offer Rate"
          value={formatPercent(summary.upsell_offer_rate)}
          sublabel="of matched recommendations included an upsell"
        />
        <StatCard
          label="Upsell Acceptance Rate"
          value={formatPercent(summary.upsell_acceptance_rate)}
          sublabel="of offered upsells were accepted (vs primary only)"
        />
        <StatCard
          label="Gate Rejection Rate"
          value={formatPercent(summary.gate_rejection_rate)}
          sublabel="of confirmation attempts did not result in an order"
        />
      </section>

      <section className="stats-section">
        <h2 className="stats-section-heading">By Source</h2>
        <div className="source-grid">
          <div className="source-card">
            <h3 className="source-name">Chat (human buyers)</h3>
            <div className="source-row">
              <span>Orders</span>
              <span>{chat.order_count}</span>
            </div>
            <div className="source-row">
              <span>Revenue</span>
              <span>{formatRupees(chat.revenue_rupees)}</span>
            </div>
          </div>
          <div className="source-card">
            <h3 className="source-name">Agent (ScoutBot / API)</h3>
            <div className="source-row">
              <span>Orders</span>
              <span>{agent.order_count}</span>
            </div>
            <div className="source-row">
              <span>Revenue</span>
              <span>{formatRupees(agent.revenue_rupees)}</span>
            </div>
          </div>
        </div>
      </section>

      <section className="stats-section">
        <h2 className="stats-section-heading">Gate Rejection Breakdown</h2>
        <div className="source-grid">
          <div className="source-card">
            <div className="source-row">
              <span>Over Rs.5,000 bound</span>
              <span>{summary.gate_rejection_breakdown.over_bound}</span>
            </div>
            <div className="source-row">
              <span>Buyer declined</span>
              <span>{summary.gate_rejection_breakdown.declined}</span>
            </div>
            <div className="source-row">
              <span>Unclear reply</span>
              <span>{summary.gate_rejection_breakdown.unclear}</span>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
