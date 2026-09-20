"""
Generate a professional 12-slide PowerPoint deck from .tmp/ai_trends_analysis.json.
Design: dark navy (#0A1628) background, white text, cyan (#00D4FF) accents.
Output: .tmp/ai_youtube_report_YYYY-MM-DD.pptx

Dependencies: python-pptx, plotly, kaleido
"""

import os
import json
from datetime import datetime, timezone

import plotly.graph_objects as go
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

ANALYSIS_PATH = os.path.join(os.path.dirname(__file__), "..", ".tmp", "ai_trends_analysis.json")
TMP_DIR = os.path.join(os.path.dirname(__file__), "..", ".tmp")

# Design constants
BG = RGBColor(0x0A, 0x16, 0x28)       # Dark navy
ACCENT = RGBColor(0x00, 0xD4, 0xFF)   # Cyan
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GRAY = RGBColor(0xAA, 0xAA, 0xAA)
DARK_ACCENT = RGBColor(0x00, 0x8A, 0xA8)

SLIDE_W = Inches(13.33)
SLIDE_H = Inches(7.5)

PLOTLY_BG = "rgba(0,0,0,0)"
PLOTLY_PAPER_BG = "rgba(10,22,40,1)"
PLOTLY_FONT = dict(family="Arial", color="white", size=13)
PLOTLY_CYAN = "#00D4FF"
PLOTLY_NAVY = "#0A1628"


# ---------------------------------------------------------------------------
# Slide helpers
# ---------------------------------------------------------------------------

def set_bg(slide, prs):
    """Fill slide background with dark navy."""
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = BG


def add_text(slide, text, left, top, width, height,
             font_size=18, bold=False, color=WHITE, align=PP_ALIGN.LEFT):
    txb = slide.shapes.add_textbox(left, top, width, height)
    tf = txb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.color.rgb = color
    return txb


def add_divider(slide, top):
    """Thin cyan horizontal rule."""
    line = slide.shapes.add_connector(
        1,  # MSO_CONNECTOR.STRAIGHT
        Inches(0.5), top,
        SLIDE_W - Inches(0.5), top,
    )
    line.line.color.rgb = ACCENT
    line.line.width = Pt(1.5)


def add_slide(prs, layout_idx=6):
    layout = prs.slide_layouts[layout_idx]
    slide = prs.slides.add_slide(layout)
    set_bg(slide, prs)
    return slide


def embed_chart(slide, img_path, left=Inches(0.4), top=Inches(1.3),
                width=Inches(12.5), height=Inches(5.8)):
    if os.path.exists(img_path):
        slide.shapes.add_picture(img_path, left, top, width, height)


def save_plotly(fig, filename):
    path = os.path.join(TMP_DIR, filename)
    fig.write_image(path, width=1300, height=620, scale=2)
    return path


def apply_plotly_theme(fig):
    fig.update_layout(
        paper_bgcolor=PLOTLY_PAPER_BG,
        plot_bgcolor=PLOTLY_PAPER_BG,
        font=PLOTLY_FONT,
        margin=dict(l=60, r=40, t=40, b=60),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="white")),
    )
    fig.update_xaxes(color="white", gridcolor="rgba(255,255,255,0.1)", tickfont=dict(color="white"))
    fig.update_yaxes(color="white", gridcolor="rgba(255,255,255,0.1)", tickfont=dict(color="white"))
    return fig


def slide_header(slide, title, subtitle=None):
    add_text(slide, title,
             left=Inches(0.5), top=Inches(0.2),
             width=Inches(12), height=Inches(0.7),
             font_size=28, bold=True, color=WHITE)
    if subtitle:
        add_text(slide, subtitle,
                 left=Inches(0.5), top=Inches(0.85),
                 width=Inches(12), height=Inches(0.35),
                 font_size=13, color=GRAY)
    add_divider(slide, Inches(1.2))


# ---------------------------------------------------------------------------
# Individual slides
# ---------------------------------------------------------------------------

def slide_title(prs, date_str, total_videos):
    slide = add_slide(prs)

    # Large title
    add_text(slide, "AI & Automation",
             left=Inches(1), top=Inches(1.5),
             width=Inches(11), height=Inches(1.2),
             font_size=52, bold=True, color=WHITE, align=PP_ALIGN.CENTER)

    add_text(slide, "YouTube Intelligence Report",
             left=Inches(1), top=Inches(2.6),
             width=Inches(11), height=Inches(0.9),
             font_size=36, bold=False, color=ACCENT, align=PP_ALIGN.CENTER)

    add_text(slide, date_str,
             left=Inches(1), top=Inches(3.6),
             width=Inches(11), height=Inches(0.5),
             font_size=18, color=GRAY, align=PP_ALIGN.CENTER)

    add_text(slide, f"Analysis of {total_videos:,} videos across top AI channels",
             left=Inches(1), top=Inches(4.2),
             width=Inches(11), height=Inches(0.5),
             font_size=15, color=GRAY, align=PP_ALIGN.CENTER)

    add_text(slide, "Powered by WAT Framework",
             left=Inches(1), top=Inches(6.8),
             width=Inches(11), height=Inches(0.4),
             font_size=11, color=GRAY, align=PP_ALIGN.CENTER)


def slide_executive_summary(prs, insights):
    slide = add_slide(prs)
    slide_header(slide, "Executive Summary", "Key findings from this week's data")

    top = Inches(1.5)
    for i, insight in enumerate(insights[:6]):
        bullet = f"  {insight}"
        add_text(slide, f"{'●'}  {insight}",
                 left=Inches(0.6), top=top + Inches(i * 0.85),
                 width=Inches(12.1), height=Inches(0.8),
                 font_size=14, color=WHITE)


def slide_top_videos_table(prs, top_videos):
    slide = add_slide(prs)
    slide_header(slide, "Top 10 Videos by Views", "Most watched AI content right now")

    cols = ["#", "Title", "Channel", "Views", "Eng. Rate"]
    col_widths = [Inches(0.4), Inches(6.2), Inches(2.5), Inches(1.5), Inches(1.2)]
    col_lefts = [Inches(0.3)]
    for w in col_widths[:-1]:
        col_lefts.append(col_lefts[-1] + w)

    header_top = Inches(1.4)
    row_h = Inches(0.47)

    # Header row
    for i, (col, left, w) in enumerate(zip(cols, col_lefts, col_widths)):
        add_text(slide, col, left=left, top=header_top, width=w, height=row_h,
                 font_size=12, bold=True, color=ACCENT)

    for row_idx, v in enumerate(top_videos[:10]):
        row_top = header_top + Inches(0.45) + Inches(row_idx * 0.47)
        row_color = RGBColor(0x12, 0x28, 0x44) if row_idx % 2 == 0 else BG
        values = [
            str(row_idx + 1),
            (v.get("title", "")[:55] + "…") if len(v.get("title", "")) > 55 else v.get("title", ""),
            v.get("channel_name", "")[:28],
            f"{v.get('view_count', 0):,}",
            f"{v.get('engagement_rate', 0) * 100:.1f}%",
        ]
        for val, left, w in zip(values, col_lefts, col_widths):
            add_text(slide, val, left=left, top=row_top, width=w, height=row_h,
                     font_size=11, color=WHITE)


def slide_most_viewed(prs, top_videos):
    labels = [(v.get("title", "")[:35] + "…") if len(v.get("title", "")) > 35 else v.get("title", "")
              for v in top_videos[:15]]
    values = [v.get("view_count", 0) for v in top_videos[:15]]
    channels = [v.get("channel_name", "") for v in top_videos[:15]]

    # Reverse for horizontal bar (plotly draws bottom to top)
    labels, values, channels = labels[::-1], values[::-1], channels[::-1]

    fig = go.Figure(go.Bar(
        x=values, y=labels,
        orientation="h",
        marker_color=PLOTLY_CYAN,
        text=[f"{v:,.0f}" for v in values],
        textposition="outside",
        textfont=dict(color="white", size=10),
        hovertemplate="%{y}<br>Views: %{x:,}<extra></extra>",
    ))
    apply_plotly_theme(fig)
    fig.update_layout(title=dict(text="", font=dict(color="white")),
                      xaxis_title="View Count", yaxis_title="")
    img = save_plotly(fig, "chart_most_viewed.png")

    slide = add_slide(prs)
    slide_header(slide, "Most Viewed This Week", "Top 15 videos by total view count")
    embed_chart(slide, img)


def slide_engagement_champions(prs, top_by_engagement):
    labels = [(v.get("title", "")[:35] + "…") if len(v.get("title", "")) > 35 else v.get("title", "")
              for v in top_by_engagement[:10]]
    values = [round(v.get("engagement_rate", 0) * 100, 2) for v in top_by_engagement[:10]]
    labels, values = labels[::-1], values[::-1]

    fig = go.Figure(go.Bar(
        x=values, y=labels,
        orientation="h",
        marker_color="#FF6B6B",
        text=[f"{v:.1f}%" for v in values],
        textposition="outside",
        textfont=dict(color="white", size=11),
    ))
    apply_plotly_theme(fig)
    fig.update_layout(xaxis_title="Engagement Rate (%)", yaxis_title="")
    img = save_plotly(fig, "chart_engagement.png")

    slide = add_slide(prs)
    slide_header(slide, "Engagement Champions", "Highest (likes + comments) / views ratio")
    embed_chart(slide, img)


def slide_trending_keywords(prs, trending_keywords):
    top = trending_keywords[:20]
    labels = [k["keyword"] for k in top]
    values = [k["count"] for k in top]

    colors = [PLOTLY_CYAN if i < 5 else "#4A90D9" for i in range(len(labels))]

    fig = go.Figure(go.Bar(
        x=labels, y=values,
        marker_color=colors,
        text=values,
        textposition="outside",
        textfont=dict(color="white", size=10),
    ))
    apply_plotly_theme(fig)
    fig.update_layout(xaxis_title="Keyword", yaxis_title="Frequency in Titles",
                      xaxis_tickangle=-40)
    img = save_plotly(fig, "chart_keywords.png")

    slide = add_slide(prs)
    slide_header(slide, "Trending Topics & Keywords", "Most frequent words in video titles (stopwords removed)")
    embed_chart(slide, img)


def slide_channel_comparison(prs, channel_stats):
    top_channels = channel_stats[:10]
    names = [c["channel_name"] for c in top_channels]
    avg_views = [c["avg_views"] for c in top_channels]
    video_counts = [c["video_count"] for c in top_channels]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Avg Views/Video", x=names, y=avg_views,
        marker_color=PLOTLY_CYAN, yaxis="y",
    ))
    fig.add_trace(go.Bar(
        name="Videos Analyzed", x=names, y=video_counts,
        marker_color="#FF6B6B", yaxis="y2",
    ))
    apply_plotly_theme(fig)
    fig.update_layout(
        barmode="group",
        yaxis=dict(title="Avg Views/Video", color="white", gridcolor="rgba(255,255,255,0.1)"),
        yaxis2=dict(title="Video Count", overlaying="y", side="right", color="white"),
        legend=dict(orientation="h", y=1.1),
        xaxis_tickangle=-30,
    )
    img = save_plotly(fig, "chart_channels.png")

    slide = add_slide(prs)
    slide_header(slide, "Channel Comparison", "Average views per video vs. volume of uploads")
    embed_chart(slide, img)


def slide_content_type(prs, content_type_distribution):
    labels = list(content_type_distribution.keys())
    values = list(content_type_distribution.values())

    colors = ["#00D4FF", "#FF6B6B", "#4A90D9", "#F5A623", "#7ED321", "#9B59B6"]

    fig = go.Figure(go.Pie(
        labels=labels, values=values,
        marker=dict(colors=colors[:len(labels)], line=dict(color="#0A1628", width=2)),
        textinfo="label+percent",
        textfont=dict(size=14, color="white"),
        hole=0.35,
    ))
    apply_plotly_theme(fig)
    fig.update_layout(showlegend=True)
    img = save_plotly(fig, "chart_content_types.png")

    slide = add_slide(prs)
    slide_header(slide, "Content Type Breakdown", "What kinds of AI videos dominate the niche")
    embed_chart(slide, img, left=Inches(2), top=Inches(1.4), width=Inches(9), height=Inches(5.8))


def slide_upload_days(prs, upload_day_distribution):
    days = list(upload_day_distribution.keys())
    counts = list(upload_day_distribution.values())
    max_day = max(upload_day_distribution, key=upload_day_distribution.get)

    bar_colors = [PLOTLY_CYAN if d == max_day else "#4A90D9" for d in days]

    fig = go.Figure(go.Bar(
        x=days, y=counts,
        marker_color=bar_colors,
        text=counts,
        textposition="outside",
        textfont=dict(color="white", size=12),
    ))
    apply_plotly_theme(fig)
    fig.update_layout(xaxis_title="Day of Week", yaxis_title="Number of Videos Uploaded")
    img = save_plotly(fig, "chart_upload_days.png")

    slide = add_slide(prs)
    slide_header(slide, "Best Days to Publish", f"Upload patterns — {max_day} sees the most activity")
    embed_chart(slide, img)


def slide_views_vs_engagement(prs, videos_data):
    # Use top_by_views as representative sample
    views = [v.get("view_count", 0) for v in videos_data]
    eng = [round(v.get("engagement_rate", 0) * 100, 2) for v in videos_data]
    channels = [v.get("channel_name", "") for v in videos_data]
    titles = [(v.get("title", "")[:40] + "…") if len(v.get("title", "")) > 40 else v.get("title", "")
              for v in videos_data]

    fig = go.Figure(go.Scatter(
        x=views, y=eng,
        mode="markers",
        marker=dict(
            color=PLOTLY_CYAN,
            size=8,
            opacity=0.7,
            line=dict(color="white", width=0.5),
        ),
        text=[f"{t}<br>{c}" for t, c in zip(titles, channels)],
        hovertemplate="%{text}<br>Views: %{x:,}<br>Eng Rate: %{y:.1f}%<extra></extra>",
    ))
    apply_plotly_theme(fig)
    fig.update_layout(
        xaxis_title="Total Views",
        yaxis_title="Engagement Rate (%)",
        xaxis_type="log",
    )
    img = save_plotly(fig, "chart_scatter.png")

    slide = add_slide(prs)
    slide_header(slide, "Views vs. Engagement", "Find the sweet spot: high views AND high engagement")
    embed_chart(slide, img)


def slide_rising_fast(prs, rising_fast):
    slide = add_slide(prs)
    slide_header(slide, "Rising Fast", "Highest views-per-day among videos published in the last 7 days")

    cols = ["#", "Title", "Channel", "Views/Day", "Days Old"]
    col_widths = [Inches(0.4), Inches(6.0), Inches(2.7), Inches(1.6), Inches(1.2)]
    col_lefts = [Inches(0.3)]
    for w in col_widths[:-1]:
        col_lefts.append(col_lefts[-1] + w)

    header_top = Inches(1.4)
    row_h = Inches(0.47)

    for i, (col, left, w) in enumerate(zip(cols, col_lefts, col_widths)):
        add_text(slide, col, left=left, top=header_top, width=w, height=row_h,
                 font_size=12, bold=True, color=ACCENT)

    for row_idx, v in enumerate(rising_fast[:10]):
        row_top = header_top + Inches(0.45) + Inches(row_idx * 0.47)
        title = v.get("title", "")
        values = [
            str(row_idx + 1),
            (title[:52] + "…") if len(title) > 52 else title,
            v.get("channel_name", "")[:30],
            f"{v.get('views_per_day', 0):,.0f}",
            f"{v.get('days_since_published', 0):.1f}d",
        ]
        for val, left, w in zip(values, col_lefts, col_widths):
            add_text(slide, val, left=left, top=row_top, width=w, height=row_h,
                     font_size=11, color=WHITE)


def slide_recommendations(prs, insights, top_keywords, top_content_type):
    slide = add_slide(prs)
    slide_header(slide, "Content Recommendations", "Data-driven action items for your channel")

    top_kws = ", ".join([k["keyword"] for k in top_keywords[:5]])
    top_type = max(top_content_type, key=top_content_type.get) if top_content_type else "tutorial"

    recs = [
        f"Include these keywords in your next titles: {top_kws}",
        f"Lead with {top_type}-style content — it's the dominant format in the AI niche right now",
        "Aim for engagement rate >3% — videos with high comments signal algorithmic boost",
        "Publish early in the week to ride peak upload-day traffic from competing channels",
        "Target 10–20 minute video length for tutorials — best balance of depth and retention in AI content",
        "Study the rising fast videos: replicate their hook structure within the first 30 seconds",
    ]

    for i, rec in enumerate(recs):
        icon = "→"
        add_text(slide, f"{icon}  {rec}",
                 left=Inches(0.6), top=Inches(1.5) + Inches(i * 0.85),
                 width=Inches(12.1), height=Inches(0.8),
                 font_size=14, color=WHITE)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not os.path.exists(ANALYSIS_PATH):
        raise FileNotFoundError(f"Not found: {ANALYSIS_PATH}. Run analyze_trends.py first.")

    with open(ANALYSIS_PATH, encoding="utf-8") as f:
        data = json.load(f)

    os.makedirs(TMP_DIR, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    output_filename = f"ai_youtube_report_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.pptx"
    output_path = os.path.join(TMP_DIR, output_filename)

    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    total_videos = data.get("total_videos_analyzed", 0)
    insights = data.get("key_insights", [])
    top_by_views = data.get("top_videos_by_views", [])
    top_by_engagement = data.get("top_videos_by_engagement", [])
    rising_fast = data.get("rising_fast", [])
    trending_keywords = data.get("trending_keywords", [])
    channel_stats = data.get("channel_stats", [])
    content_types = data.get("content_type_distribution", {})
    upload_days = data.get("upload_day_distribution", {})

    print("Building slides...")

    print("  Slide 1: Title")
    slide_title(prs, date_str, total_videos)

    print("  Slide 2: Executive Summary")
    slide_executive_summary(prs, insights)

    print("  Slide 3: Top Videos Table")
    slide_top_videos_table(prs, top_by_views)

    print("  Slide 4: Most Viewed (chart)")
    slide_most_viewed(prs, top_by_views)

    print("  Slide 5: Engagement Champions (chart)")
    slide_engagement_champions(prs, top_by_engagement)

    print("  Slide 6: Trending Keywords (chart)")
    slide_trending_keywords(prs, trending_keywords)

    print("  Slide 7: Channel Comparison (chart)")
    slide_channel_comparison(prs, channel_stats)

    print("  Slide 8: Content Type Breakdown (pie)")
    slide_content_type(prs, content_types)

    print("  Slide 9: Best Upload Days (chart)")
    slide_upload_days(prs, upload_days)

    print("  Slide 10: Views vs. Engagement (scatter)")
    all_enriched = top_by_views + [v for v in top_by_engagement if v not in top_by_views]
    slide_views_vs_engagement(prs, all_enriched)

    print("  Slide 11: Rising Fast Table")
    slide_rising_fast(prs, rising_fast)

    print("  Slide 12: Content Recommendations")
    slide_recommendations(prs, insights, trending_keywords, content_types)

    prs.save(output_path)
    print(f"\nDeck saved: {output_path}")
    return output_path


if __name__ == "__main__":
    main()
