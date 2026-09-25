import { useId, useState, type ReactNode } from "react";
import { Box, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";

/**
 * A bar chart that follows the house rules: thin bars (<= 24px) with a 4px
 * rounded data-end and a square baseline, a 2px surface gap between touching
 * fills, hairline solid gridlines, a legend whenever there are two or more
 * series, a per-mark hover and focus tooltip, and a table view twin so no
 * value is reachable only by hovering.
 *
 * Colours are roles, not hex, defined once in `viz.css`; the categorical
 * slots and the ordinal ramp were validated with the palette script against
 * this console's white surface.
 */

export interface Series {
  key: string;
  label: string;
  /** A CSS variable name from viz.css, e.g. "--series-1". */
  color: string;
  values: (number | null)[];
}

export interface BarChartProps {
  title?: string;
  categories: string[];
  series: Series[];
  /** "grouped" places series side by side; "stacked" stacks them. */
  mode?: "grouped" | "stacked";
  /** Fixed upper bound, e.g. 7 for a Likert mean or 100 for a percentage. */
  max?: number;
  format?: (v: number) => string;
  height?: number;
  /** Per-category colour override for a single ordinal series. */
  ordinalColors?: string[];
  emptyText?: string;
}

const PLOT_LEFT = 44;
const PLOT_RIGHT = 8;
const PLOT_TOP = 18;
const AXIS_BAND = 26;
const BAR_MAX = 24;
const GAP = 2;

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

export function BarChart({ title, categories, series, mode = "grouped", max, format = (v) => String(v), height = 220, ordinalColors, emptyText = "No data yet." }: BarChartProps) {
  const [hover, setHover] = useState<{ c: number; s: number; x: number; y: number } | null>(null);
  const [table, setTable] = useState(false);
  const id = useId();
  const width = 560;
  const plotW = width - PLOT_LEFT - PLOT_RIGHT;
  const plotH = height - PLOT_TOP - AXIS_BAND;

  const totals = categories.map((_, ci) =>
    mode === "stacked" ? series.reduce((s, sr) => s + (sr.values[ci] ?? 0), 0)
      : Math.max(...series.map((sr) => sr.values[ci] ?? 0)));
  const dataMax = Math.max(0, ...totals);
  const yMax = max ?? niceMax(dataMax);
  const empty = dataMax === 0 && series.every((sr) => sr.values.every((v) => !v));
  const y = (v: number) => PLOT_TOP + plotH - (v / yMax) * plotH;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * yMax);

  const slotW = plotW / Math.max(1, categories.length);
  const groupN = mode === "grouped" ? series.length : 1;
  const barW = Math.min(BAR_MAX, (slotW * 0.7 - GAP * (groupN - 1)) / groupN);
  const groupW = barW * groupN + GAP * (groupN - 1);

  const showLegend = series.length >= 2;

  return (
    <Box className="viz-root">
      {(title || showLegend) && (
        <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 2, mb: 1, flexWrap: "wrap" }}>
          {title && <Typography variant="subtitle2" color="text.secondary">{title}</Typography>}
          {showLegend && (
            <Box className="viz-legend" role="list">
              {series.map((sr) => (
                <span key={sr.key} role="listitem" className="viz-legend-item">
                  <span className="viz-swatch" style={{ background: `var(${sr.color})` }} />
                  {sr.label}
                </span>
              ))}
            </Box>
          )}
        </Box>
      )}

      {empty ? (
        <Typography color="text.secondary" variant="body2" sx={{ py: 4, textAlign: "center" }}>{emptyText}</Typography>
      ) : table ? (
        <Table size="small">
          <TableHead>
            <TableRow><TableCell /> {series.map((sr) => <TableCell key={sr.key} align="right">{sr.label}</TableCell>)}</TableRow>
          </TableHead>
          <TableBody>
            {categories.map((c, ci) => (
              <TableRow key={c}><TableCell>{c}</TableCell>
                {series.map((sr) => <TableCell key={sr.key} align="right" sx={{ fontVariantNumeric: "tabular-nums" }}>{sr.values[ci] == null ? "—" : format(sr.values[ci]!)}</TableCell>)}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : (
        <Box sx={{ position: "relative" }}>
          <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" aria-labelledby={`${id}-t`}>
            <title id={`${id}-t`}>{title ?? "chart"}</title>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={PLOT_LEFT} x2={width - PLOT_RIGHT} y1={y(t)} y2={y(t)} className={t === 0 ? "viz-baseline" : "viz-grid"} />
                <text x={PLOT_LEFT - 6} y={y(t) + 4} textAnchor="end" className="viz-tick">{format(t)}</text>
              </g>
            ))}
            {categories.map((c, ci) => {
              const cx = PLOT_LEFT + slotW * ci + slotW / 2;
              let stackY = 0;
              return (
                <g key={c}>
                  <text x={cx} y={height - 8} textAnchor="middle" className="viz-cat">{c}</text>
                  {series.map((sr, si) => {
                    const v = sr.values[ci] ?? 0;
                    const color = ordinalColors ? ordinalColors[ci] : sr.color;
                    let x0: number, y0: number, h: number;
                    if (mode === "stacked") {
                      x0 = cx - barW / 2;
                      const top = y(stackY + v);
                      const bottom = y(stackY);
                      h = Math.max(0, bottom - top - (stackY > 0 && v > 0 ? GAP : 0));
                      y0 = top;
                      stackY += v;
                    } else {
                      x0 = cx - groupW / 2 + si * (barW + GAP);
                      y0 = y(v);
                      h = Math.max(0, y(0) - y0);
                    }
                    if (v <= 0) return null;
                    const r = Math.min(4, h, barW / 2);
                    const isTop = mode !== "stacked" || si === series.length - 1 || series.slice(si + 1).every((s) => !(s.values[ci] ?? 0));
                    const path = isTop
                      ? `M${x0},${y0 + h} L${x0},${y0 + r} Q${x0},${y0} ${x0 + r},${y0} L${x0 + barW - r},${y0} Q${x0 + barW},${y0} ${x0 + barW},${y0 + r} L${x0 + barW},${y0 + h} Z`
                      : `M${x0},${y0} h${barW} v${h} h${-barW} Z`;
                    const active = hover && hover.c === ci && hover.s === si;
                    return (
                      <g key={sr.key}>
                        <path d={path} fill={`var(${color})`} opacity={active ? 0.85 : 1} />
                        {/* The hit target is bigger than the mark. */}
                        <rect x={x0 - 6} y={PLOT_TOP} width={barW + 12} height={plotH} fill="transparent" tabIndex={0}
                          aria-label={`${c}, ${sr.label}: ${format(v)}`}
                          onPointerEnter={() => setHover({ c: ci, s: si, x: x0 + barW / 2, y: y0 })}
                          onFocus={() => setHover({ c: ci, s: si, x: x0 + barW / 2, y: y0 })}
                          onPointerLeave={() => setHover(null)} onBlur={() => setHover(null)} />
                        {mode !== "stacked" && categories.length * series.length <= 10 && (
                          <text x={x0 + barW / 2} y={y0 - 5} textAnchor="middle" className="viz-value">{format(v)}</text>
                        )}
                      </g>
                    );
                  })}
                </g>
              );
            })}
          </svg>
          {hover && (
            <Tooltip x={(hover.x / width) * 100} y={(hover.y / height) * 100}>
              <strong>{format(series[hover.s].values[hover.c] ?? 0)}</strong>
              <span className="viz-tip-key" style={{ background: `var(${ordinalColors ? ordinalColors[hover.c] : series[hover.s].color})` }} />
              {series.length > 1 ? `${series[hover.s].label} · ` : ""}{categories[hover.c]}
            </Tooltip>
          )}
        </Box>
      )}
      <Box sx={{ textAlign: "right" }}>
        <button type="button" className="viz-toggle" onClick={() => setTable((t) => !t)}>{table ? "Chart" : "Table"}</button>
      </Box>
    </Box>
  );
}

function Tooltip({ x, y, children }: { x: number; y: number; children: ReactNode }) {
  return (
    <div className="viz-tip" style={{ left: `${x}%`, top: `${y}%` }} role="status">{children}</div>
  );
}
