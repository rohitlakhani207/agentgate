"""The two README charts: the threshold sweep and the calibration diagram.

Each is drawn twice, for light and dark README themes. Series colours follow a fixed
categorical order; text stays in text colours; one y-axis per panel.
"""

from __future__ import annotations

import math
from pathlib import Path

from .metrics import SetupResult, calibration_bins

THEMES = {
    "light": {
        "surface": "#fcfcfb",
        "text": "#0b0b0b",
        "muted": "#52514e",
        "grid": "#e6e5e0",
        "series": ["#2a78d6", "#eb6834", "#1baf7a"],
        "reference": "#a3a29b",
    },
    "dark": {
        "surface": "#1a1a19",
        "text": "#ffffff",
        "muted": "#c3c2b7",
        "grid": "#33332f",
        "series": ["#3987e5", "#d95926", "#199e70"],
        "reference": "#6b6a64",
    },
}
LABELS = {"decider": "Decider 2B", "clef": "Clef-flash", "llm_judge": "LLM judge"}


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _style(ax, t: dict) -> None:
    ax.set_facecolor(t["surface"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(t["grid"])
    ax.tick_params(colors=t["muted"], labelsize=9, length=0)
    ax.grid(True, axis="y", color=t["grid"], linewidth=1, linestyle="-")
    ax.set_axisbelow(True)


def plot_sweep(rows: list[dict], chosen: float | None, out_dir: Path) -> list[Path]:
    """Two panels sharing the threshold axis: shares on top, missed count below."""
    plt = _plt()
    paths = []
    xs = [r["threshold"] for r in rows]
    for theme, t in THEMES.items():
        fig, (top, bottom) = plt.subplots(
            2, 1, figsize=(7.2, 5.6), sharex=True, gridspec_kw={"height_ratios": [3, 2]}
        )
        fig.patch.set_facecolor(t["surface"])
        for ax in (top, bottom):
            _style(ax, t)

        series = [("accuracy", "Accuracy"), ("step1_share", "Settled by Decider alone")]
        for (key, label), color in zip(series, t["series"], strict=False):
            ys = [r[key] * 100 for r in rows]
            top.plot(
                xs,
                ys,
                color=color,
                linewidth=2,
                solid_capstyle="round",
                label=label,
                marker="o",
                markersize=5,
                markeredgecolor=t["surface"],
                markeredgewidth=1.5,
            )
            top.annotate(
                f"{ys[-1]:.0f}%",
                (xs[-1], ys[-1]),
                xytext=(8, 0),
                textcoords="offset points",
                va="center",
                color=t["text"],
                fontsize=9,
            )
        top.set_ylim(0, 105)
        top.set_ylabel("% of calls", color=t["muted"], fontsize=9)
        legend = top.legend(loc="lower left", frameon=False, fontsize=9)
        for text in legend.get_texts():
            text.set_color(t["text"])

        missed = [r["missed"] for r in rows]
        bars = bottom.bar(xs, missed, width=0.014, color=t["series"][2])
        for bar, value in zip(bars, missed, strict=True):
            bottom.annotate(
                str(value),
                (bar.get_x() + bar.get_width() / 2, value),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                color=t["text"],
                fontsize=9,
            )
        bottom.set_ylabel("Missed dangerous", color=t["muted"], fontsize=9)
        bottom.set_ylim(0, max([*missed, 1]) * 1.3)
        bottom.set_xlabel("Decider confidence threshold", color=t["muted"], fontsize=9)
        bottom.set_xticks(xs)
        bottom.set_xticklabels([f"{x:.2f}" for x in xs])

        if chosen is not None:
            for ax in (top, bottom):
                ax.axvline(chosen, color=t["reference"], linewidth=1)
            top.annotate(
                f"chosen {chosen:.2f}",
                (chosen, 103),
                xytext=(4, 0),
                textcoords="offset points",
                color=t["muted"],
                fontsize=9,
                va="top",
            )

        fig.suptitle(
            "Raising the threshold trades step-1 share for safety",
            color=t["text"],
            fontsize=12,
            x=0.02,
            ha="left",
            fontweight="bold",
        )
        fig.tight_layout()
        path = out_dir / f"threshold_sweep_{theme}.png"
        fig.savefig(path, dpi=160, facecolor=t["surface"])
        plt.close(fig)
        paths.append(path)
    return paths


def plot_calibration(results: dict[str, SetupResult], out_dir: Path) -> list[Path]:
    """Reliability diagram: within each confidence bin, how often was the model right?"""
    plt = _plt()
    names = [n for n in ("decider", "clef", "llm_judge") if n in results]
    paths = []
    for theme, t in THEMES.items():
        fig, ax = plt.subplots(figsize=(6.4, 5.2))
        fig.patch.set_facecolor(t["surface"])
        _style(ax, t)
        ax.plot([0, 1], [0, 100], color=t["reference"], linewidth=1)
        # Low on the diagonal, where the data rarely is; rotated to follow the line.
        ax.text(0.1, 13, "perfectly calibrated", color=t["muted"], fontsize=9,
                rotation=math.degrees(math.atan2(100, 1)), rotation_mode="anchor",
                transform_rotates_text=True)  # fmt: skip
        # Three series with a legend: no end labels, which collide where lines converge.
        for name, color in zip(names, t["series"], strict=False):
            bins = calibration_bins(results[name].outcomes)
            xs = [(lo + hi) / 2 for lo, hi, _, _ in bins]
            ys = [acc * 100 for _, _, _, acc in bins]
            ax.plot(
                xs,
                ys,
                color=color,
                linewidth=2,
                marker="o",
                markersize=7,
                markeredgecolor=t["surface"],
                markeredgewidth=2,
                label=LABELS[name],
            )
        ax.set_xlim(0, 1.02)
        ax.set_ylim(0, 105)
        ax.set_xlabel("Reported confidence (binned)", color=t["muted"], fontsize=9)
        ax.set_ylabel("% of decisions that matched the label", color=t["muted"], fontsize=9)
        legend = ax.legend(loc="upper left", frameon=False, fontsize=9)
        for text in legend.get_texts():
            text.set_color(t["text"])
        fig.suptitle(
            "Does 0.9 confidence mean right 9 times in 10?",
            color=t["text"],
            fontsize=12,
            x=0.02,
            ha="left",
            fontweight="bold",
        )
        fig.tight_layout()
        path = out_dir / f"calibration_{theme}.png"
        fig.savefig(path, dpi=160, facecolor=t["surface"])
        plt.close(fig)
        paths.append(path)
    return paths
