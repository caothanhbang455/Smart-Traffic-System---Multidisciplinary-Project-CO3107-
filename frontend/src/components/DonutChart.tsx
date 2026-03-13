export type DonutItem = { label: string; value: number; color: string }

function buildConicGradient(items: DonutItem[]) {
  const total = items.reduce((s, x) => s + x.value, 0) || 1
  let start = 0
  const parts = items.map((x) => {
    const pct = (x.value / total) * 100
    const from = start
    const to = start + pct
    start = to
    return `${x.color} ${from.toFixed(2)}% ${to.toFixed(2)}%`
  })
  return `conic-gradient(${parts.join(', ')})`
}

export function DonutChart({ items }: { items: DonutItem[] }) {
  const total = items.reduce((s, x) => s + x.value, 0)
  const style = { background: buildConicGradient(items) }

  return (
    <div className="st-donut">
      <div className="st-donut__chart" style={style}>
        <div className="st-donut__hole">
          <div className="st-donut__total">{total}</div>
          <div className="st-donut__label">vehicles</div>
        </div>
      </div>
      <div className="st-donut__legend">
        {items.map((x) => (
          <div className="st-donut__item" key={x.label}>
            <span className="st-donut__swatch" style={{ background: x.color }} />
            <span className="st-donut__name">{x.label}</span>
            <span className="st-donut__val">{x.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

