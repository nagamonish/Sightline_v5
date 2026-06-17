const statConfig = [
  { key: "total", label: "Total spaces", tone: "neutral" },
  { key: "available", label: "Available", tone: "available" },
  { key: "occupied", label: "Occupied", tone: "occupied" },
  { key: "occupancy_pct", label: "Occupancy", tone: "percent", suffix: "%" },
];

export function StatCards({ summary }) {
  const totals = summary.reduce(
    (acc, camera) => {
      acc.total += camera.total || 0;
      acc.available += camera.available || 0;
      acc.occupied += camera.occupied || 0;
      return acc;
    },
    { total: 0, available: 0, occupied: 0 },
  );

  const values = {
    ...totals,
    occupancy_pct: totals.total
      ? Math.round((totals.occupied / totals.total) * 100)
      : 0,
  };

  return (
    <section className="stat-grid" aria-label="Occupancy summary">
      {statConfig.map((stat) => (
        <article className={`stat-card ${stat.tone}`} key={stat.key}>
          <span className="stat-label">{stat.label}</span>
          <strong>
            {values[stat.key]}
            {stat.suffix || ""}
          </strong>
        </article>
      ))}
    </section>
  );
}
