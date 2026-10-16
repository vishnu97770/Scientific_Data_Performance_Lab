"""Altair charts built from the frames in ``sdplab.dashboard.data`` (no calculations here).

Every chart plots recorded values, labels its axes with units, scopes log scales explicitly, and
leaves missing measurements out (never zero-filled). Colours are a colour-blind-safe palette, and
variants also differ by shape or position so colour is never the only cue.
"""

from __future__ import annotations

import altair as alt

from sdplab.dashboard.data import VARIANT_ORDER, operation_label, variant_label

COLORS = {
    "csv": "#D55E00",
    "npy": "#0072B2",
    "npz": "#009E73",
    "npz_compressed": "#CC79A7",
    "in_memory": "#555555",
}
SHAPES = {
    "csv": "circle",
    "npy": "square",
    "npz": "triangle-up",
    "npz_compressed": "diamond",
    "in_memory": "cross",
}
HEIGHT = 340


def _variants(frame) -> list[str]:
    present = set(frame["variant"])
    return [v for v in VARIANT_ORDER if v in present]


def _color(frame, legend: bool = True) -> alt.Color:
    vs = _variants(frame)
    return alt.Color(
        "variant_label:N",
        title=None,
        legend=alt.Legend(orient="top", direction="horizontal", columns=4) if legend else None,
        scale=alt.Scale(domain=[variant_label(v) for v in vs], range=[COLORS[v] for v in vs]),
    )


def _shape(frame) -> alt.Shape:
    """Marker shape per variant, merged into the same legend as the colour."""
    vs = _variants(frame)
    return alt.Shape(
        "variant_label:N",
        title=None,
        scale=alt.Scale(domain=[variant_label(v) for v in vs], range=[SHAPES[v] for v in vs]),
        legend=alt.Legend(orient="top", direction="horizontal", columns=4),
    )


def _x_rows(frame) -> alt.X:
    sizes = sorted(set(int(n) for n in frame["rows"]))
    return alt.X(
        "rows:Q",
        title="Dataset size (rows, log scale)",
        scale=alt.Scale(type="log", domain=[min(sizes) * 0.7, max(sizes) * 1.4]),
        axis=alt.Axis(values=sizes, format=",d"),
    )


def time_chart(summary, trials, operation: str, formats: list[str], log_y: bool):
    """Median time with IQR bars and the raw measured trials, for one operation."""
    cells = summary[
        (summary["operation"] == operation)
        & summary["variant"].isin(formats)
        & summary["median_ms"].notna()
    ]
    if cells.empty:
        return None
    cells = cells[["rows", "variant", "variant_label", "median_ms", "q1_ms", "q3_ms", "n_ok"]]
    y_scale = alt.Scale(type="log" if log_y else "linear", zero=not log_y)
    y_title = "Elapsed time (ms" + (", log scale)" if log_y else ")")
    base = alt.Chart(cells)
    line = base.mark_line().encode(
        x=_x_rows(cells),
        y=alt.Y("median_ms:Q", title=y_title, scale=y_scale),
        color=_color(cells),
    )
    points = base.mark_point(filled=True, size=70).encode(
        x="rows:Q",
        y="median_ms:Q",
        color=_color(cells),
        shape=_shape(cells),
        tooltip=[
            alt.Tooltip("variant_label:N", title="Format"),
            alt.Tooltip("rows:Q", title="Rows", format=",d"),
            alt.Tooltip("median_ms:Q", title="Median (ms)", format=".4g"),
            alt.Tooltip("q1_ms:Q", title="Q1 (ms)", format=".4g"),
            alt.Tooltip("q3_ms:Q", title="Q3 (ms)", format=".4g"),
            alt.Tooltip("n_ok:Q", title="Accepted trials"),
        ],
    )
    bars = base.mark_rule().encode(x="rows:Q", y="q1_ms:Q", y2="q3_ms:Q", color=_color(cells))
    layers = [bars, line, points]
    raw = trials[
        (trials["phase"] == "measured")
        & (trials["operation"] == operation)
        & trials["variant"].isin(formats)
        & (trials["status"] == "ok")
        & (trials["correct"] == True)  # noqa: E712 - pandas elementwise comparison
    ].copy()
    if not raw.empty:
        raw = raw[["rows", "variant", "elapsed_ms"]].copy()
        raw["variant_label"] = raw["variant"].map(variant_label)
        layers.append(
            alt.Chart(raw)
            .mark_circle(opacity=0.25, size=22)
            .encode(
                x="rows:Q",
                y=alt.Y("elapsed_ms:Q", scale=y_scale),
                color=_color(cells),
                tooltip=[
                    alt.Tooltip("variant_label:N", title="Format"),
                    alt.Tooltip("elapsed_ms:Q", title="Trial (ms)", format=".4g"),
                ],
            ),
        )
    return alt.layer(*layers).properties(
        height=HEIGHT, title=f"{operation_label(operation)}: median, IQR and raw trials"
    )


def size_chart(file_sizes, formats: list[str]):
    sel = file_sizes[file_sizes["variant"].isin(formats)][
        ["rows", "variant", "variant_label", "file_mb"]
    ]
    if sel.empty:
        return None
    sel = sel.assign(rows_label=sel["rows"].map(lambda n: f"{n:,}"))
    return (
        alt.Chart(sel)
        .mark_bar()
        .encode(
            x=alt.X("rows_label:N", title="Dataset size (rows)", sort=None),
            xOffset=alt.XOffset("variant_label:N"),
            y=alt.Y(
                "file_mb:Q", title="File size on disk (MB, log scale)", scale=alt.Scale(type="log")
            ),
            color=_color(sel),
            tooltip=[
                alt.Tooltip("variant_label:N", title="Format"),
                alt.Tooltip("rows:Q", title="Rows", format=",d"),
                alt.Tooltip("file_mb:Q", title="File size (MB)", format=".4g"),
            ],
        )
        .properties(height=HEIGHT, title="File size by storage format")
    )


def metric_chart(
    summary,
    operation: str,
    formats: list[str],
    column: str,
    y_title: str,
    title: str,
    log_y: bool = False,
):
    """Line chart of one recorded summary column across dataset sizes (throughput, memory)."""
    cells = summary[
        (summary["operation"] == operation)
        & summary["variant"].isin(formats)
        & summary[column].notna()
    ]
    if cells.empty:
        return None
    cells = cells[["rows", "variant", "variant_label", column]]
    base = alt.Chart(cells)
    scale = alt.Scale(type="log" if log_y else "linear", zero=not log_y)
    return (
        base.mark_line(point=alt.OverlayMarkDef(filled=True, size=70))
        .encode(
            x=_x_rows(cells),
            y=alt.Y(f"{column}:Q", title=y_title, scale=scale),
            color=_color(cells),
            tooltip=[
                alt.Tooltip("variant_label:N", title="Format"),
                alt.Tooltip("rows:Q", title="Rows", format=",d"),
                alt.Tooltip(f"{column}:Q", title=y_title, format=".4g"),
            ],
        )
        .properties(height=HEIGHT, title=title)
    )
