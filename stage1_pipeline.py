"""
t20_pipeline.py
────────────────────────────────────────────────────────────
T20 Batting Records — AWS S3 ETL Pipeline

FLOW:
  S3 Bucket 1 (private vault)
      ↓  boto3 reads t20.csv into RAM
  EC2 + Python
      ↓  pandas cleans the data
      ↓  build HTML report with KPI cards + chart + table
  S3 Bucket 2 (public website)
      ↓  boto3 uploads index.html
  Browser
      → anyone visits the S3 website URL and sees the report

AUTH:
  IAM Role attached to EC2 handles everything automatically.
  No keys, no passwords, no .pem file needed inside this script.

RUN ON EC2:
  python3 t20_pipeline.py
"""

import boto3
import io
import json
from datetime import datetime
import pandas as pd


# ════════════════════════════════════════════════════════════
#  SECTION 1 — CONFIG
#  These are the only values you need to change.
#  Everything else in this file stays exactly as written.
# ════════════════════════════════════════════════════════════

# Name of your PRIVATE bucket (Bucket 1 — the vault)
# This is where you uploaded t20.csv
# Find it: AWS Console → S3 → your private bucket name
VAULT_BUCKET  = "s3-private-rawdata"

# Name of your PUBLIC bucket (Bucket 2 — the website)
# This is the bucket with Static Website Hosting enabled
# Find it: AWS Console → S3 → your public bucket name
PUBLIC_BUCKET = "s3-public-webhosting"

# Exact filename of your CSV as it appears inside Bucket 1
# Go to Bucket 1 in AWS Console, click the file, copy its name exactly
# If there is a space in the name write it with the space: "t20 data.csv"
CSV_KEY = "t20.csv"

# Name the output file will have in Bucket 2
# Keep this as index.html — S3 static website looks for this by default
REPORT_KEY = "index.html"


# ════════════════════════════════════════════════════════════
#  SECTION 2 — LOAD
#  Connects to S3 Bucket 1 and reads t20.csv into a
#  pandas DataFrame (a table in RAM).
#
#  How auth works here:
#    boto3.client("s3") checks the EC2 metadata service
#    at 169.254.169.254 and gets temp keys from the IAM
#    Role you attached to this EC2 in the AWS console.
#    No keys are written in this code.
#
#  What obj["Body"] is:
#    A raw byte stream — like water coming through a pipe.
#    .read() collects all the bytes.
#    io.BytesIO() wraps bytes so pandas thinks it is a file.
# ════════════════════════════════════════════════════════════

def load():
    print(f"[LOAD] Reading s3://{VAULT_BUCKET}/{CSV_KEY} ...")
    s3  = boto3.client("s3")
    obj = s3.get_object(Bucket=VAULT_BUCKET, Key=CSV_KEY)
    df  = pd.read_csv(io.BytesIO(obj["Body"].read()))
    print(f"  Loaded: {df.shape[0]} rows x {df.shape[1]} columns")
    return df


# ════════════════════════════════════════════════════════════
#  SECTION 3 — CLEAN
#  Fixes specific issues found in t20.csv.
#  No AWS involved — this is pure pandas working on the
#  DataFrame that is already in RAM.
#
#  Issues found in this dataset:
#    1. Unnamed: 0  — junk index column (0-49 page numbers)
#    2. Unnamed: 15 — completely empty column, all NaN
#    3. Runs, Ave, SR, Inns, NO, BF, 100, 50, 0, 4s, 6s
#       all loaded as strings — need to convert to numbers
#    4. HS column has "172" and "162*" — asterisk means
#       not out, strip it before numeric comparison
#    5. Some cells have "-" instead of a number when
#       data is unavailable — pd.to_numeric converts these
#       to NaN automatically with errors="coerce"
#    6. Column names 100/50/0/4s/6s are confusing
#       — rename to readable names
# ════════════════════════════════════════════════════════════

def clean(df):
    print("[CLEAN] Cleaning data ...")

    # ── drop the two junk columns ─────────────────────────────────────────────
    df = df.drop(columns=["Unnamed: 0", "Unnamed: 15"], errors="ignore")
    # errors="ignore" means if the column doesn't exist, don't crash

    # ── rename columns to readable names ─────────────────────────────────────
    df = df.rename(columns={
        "Mat" : "Matches",
        "Inns": "Innings",
        "NO"  : "Not_Out",
        "Ave" : "Average",
        "BF"  : "Balls_Faced",
        "SR"  : "Strike_Rate",
        "100" : "Centuries",
        "50"  : "Half_Centuries",
        "0"   : "Ducks",
        "4s"  : "Fours",
        "6s"  : "Sixes",
    })

    # ── handle HS column: "162*" → 162 ───────────────────────────────────────
    # We keep original HS column for display ("162*" looks good in the table)
    # We create HS_numeric separately just for finding highest score
    df["HS_numeric"] = (
        df["HS"]
        .astype(str)
        .str.replace("*", "", regex=False)
    )
    df["HS_numeric"] = pd.to_numeric(df["HS_numeric"], errors="coerce")

    # ── convert all numeric columns from string to number ────────────────────
    # errors="coerce" means: if a cell has "-" or any non-number,
    # convert it to NaN (empty) instead of crashing
    numeric_cols = [
        "Runs", "Average", "Strike_Rate", "Innings",
        "Not_Out", "Balls_Faced", "Centuries",
        "Half_Centuries", "Ducks", "Fours", "Sixes"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # ── remove rows where Runs is missing ────────────────────────────────────
    # These rows have no run data and are useless for the report
    before = len(df)
    df = df.dropna(subset=["Runs"])
    removed = before - len(df)
    if removed > 0:
        print(f"  Removed {removed} rows with missing Runs")

    # ── remove duplicate players ──────────────────────────────────────────────
    df = df.drop_duplicates(subset=["Player"])

    print(f"  Clean: {df.shape[0]} players ready")
    return df


# ════════════════════════════════════════════════════════════
#  SECTION 4 — BUILD HTML
#  This function does two things:
#    A) Pull numbers from the DataFrame into Python variables
#    B) Write those variables into one big HTML string
#       using f-strings
#
#  The HTML string contains:
#    - <style> tag with all the CSS (dark theme, cards, table)
#    - KPI cards with numbers baked in
#    - A bar chart using Chart.js (loaded from CDN)
#    - A top 10 stats table
#
#  No CSV is attached to the HTML.
#  No DataFrame goes to S3.
#  Just a complete self-contained webpage with numbers in it.
#
#  f-string rule:
#    {variable}  → injects the Python variable value
#    {{ }}       → literal curly brace (needed for CSS rules)
# ════════════════════════════════════════════════════════════

def build_html(df):
    print("[REPORT] Building HTML ...")

    # ── A) pull KPI numbers from the DataFrame ────────────────────────────────

    total_players  = len(df)

    # top run scorer
    top_idx        = df["Runs"].idxmax()
    top_player     = df.loc[top_idx, "Player"]
    top_runs       = int(df.loc[top_idx, "Runs"])

    # most sixes — T20 specific, important stat
    six_idx        = df["Sixes"].idxmax()
    six_player     = df.loc[six_idx, "Player"]
    most_sixes     = int(df.loc[six_idx, "Sixes"])

    # highest individual score
    hs_idx         = df["HS_numeric"].idxmax()
    highest_score  = df.loc[hs_idx, "HS"]
    highest_scorer = df.loc[hs_idx, "Player"]

    # best strike rate among players with 20+ matches
    # min 20 matches filter prevents a player with 1 game skewing the stat
    qualified      = df[df["Matches"] >= 20]
    sr_idx         = qualified["Strike_Rate"].idxmax()
    best_sr        = round(float(qualified.loc[sr_idx, "Strike_Rate"]), 2)
    best_sr_name   = qualified.loc[sr_idx, "Player"]

    # most centuries
    cent_idx       = df["Centuries"].idxmax()
    most_centuries = int(df.loc[cent_idx, "Centuries"])
    cent_player    = df.loc[cent_idx, "Player"]

    # ── top 10 by runs (for the chart and table) ──────────────────────────────
    top10 = df.nlargest(10, "Runs")[
        ["Player", "Span", "Matches", "Runs", "HS",
         "Average", "Strike_Rate", "Centuries", "Half_Centuries", "Sixes"]
    ].reset_index(drop=True)

    # chart labels: strip country code "(INDIA)" for shorter display
    chart_labels = [p.split("(")[0].strip() for p in top10["Player"].tolist()]
    chart_runs   = [int(r) for r in top10["Runs"].tolist()]

    # ── build table rows as HTML string ───────────────────────────────────────
    table_rows = ""
    for i, row in top10.iterrows():
        avg_display = f"{row['Average']:.2f}" if pd.notna(row['Average']) else "-"
        sr_display  = f"{row['Strike_Rate']:.2f}" if pd.notna(row['Strike_Rate']) else "-"
        table_rows += f"""
        <tr>
            <td class="rank">#{i + 1}</td>
            <td class="player-name">{row['Player']}</td>
            <td>{row['Span']}</td>
            <td class="num">{int(row['Matches'])}</td>
            <td class="num highlight">{int(row['Runs']):,}</td>
            <td class="num">{row['HS']}</td>
            <td class="num">{avg_display}</td>
            <td class="num">{sr_display}</td>
            <td class="num">{int(row['Centuries'])}</td>
            <td class="num">{int(row['Half_Centuries'])}</td>
            <td class="num sixes">{int(row['Sixes'])}</td>
        </tr>"""

    generated_at = datetime.now().strftime("%d %B %Y, %H:%M UTC")

    # ── B) full HTML string with CSS + Chart.js ───────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>T20 International Batting Records</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #0f1117;
      color: #e8f0fe;
      padding: 2rem;
    }}
    .header {{
      margin-bottom: 2rem;
      border-bottom: 1px solid #2d3139;
      padding-bottom: 1rem;
    }}
    .header h1 {{ font-size: 1.5rem; font-weight: 500; color: #fff; }}
    .header p  {{ font-size: 0.85rem; color: #6B7280; margin-top: 4px; }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
      gap: 1rem;
      margin-bottom: 2rem;
    }}
    .kpi {{
      background: #1a1e24;
      border: 1px solid #2d3139;
      border-radius: 10px;
      padding: 1.25rem;
    }}
    .kpi .label {{
      font-size: 0.72rem;
      color: #6B7280;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .kpi .value {{
      font-size: 1.6rem;
      font-weight: 600;
      margin-top: 4px;
    }}
    .kpi .sub {{ font-size: 0.75rem; color: #6B7280; margin-top: 3px; }}
    .green {{ color: #1D9E75; }}
    .blue  {{ color: #378ADD; }}
    .amber {{ color: #EF9F27; }}
    .coral {{ color: #D85A30; }}
    .purple {{ color: #A78BFA; }}
    .chart-card, .table-card {{
      background: #1a1e24;
      border: 1px solid #2d3139;
      border-radius: 10px;
      padding: 1.5rem;
      margin-bottom: 2rem;
    }}
    .table-card {{ overflow-x: auto; }}
    .section-title {{
      font-size: 0.82rem;
      font-weight: 500;
      color: #9ca3af;
      margin-bottom: 1rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    canvas {{ max-height: 300px; }}
    table  {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
    th {{
      background: #1D9E75;
      color: #fff;
      padding: 0.65rem 0.9rem;
      text-align: left;
      font-weight: 500;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }}
    td {{
      padding: 0.65rem 0.9rem;
      border-bottom: 1px solid #1e2229;
      white-space: nowrap;
    }}
    tr:hover td {{ background: #22262e; }}
    .rank        {{ color: #6B7280; font-size: 0.8rem; }}
    .num         {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .player-name {{ font-weight: 500; color: #e8f0fe; }}
    .highlight   {{ color: #1D9E75; font-weight: 600; }}
    .sixes       {{ color: #A78BFA; font-weight: 500; }}
    footer {{
      margin-top: 2rem;
      font-size: 0.75rem;
      color: #374151;
      text-align: right;
    }}
    footer span {{ color: #1D9E75; }}
  </style>
</head>
<body>

  <div class="header">
    <h1>T20 International Batting Records — All Time</h1>
    <p>{total_players:,} players · Auto-generated {generated_at}</p>
  </div>

  <div class="kpi-grid">

    <div class="kpi">
      <div class="label">All-Time Run Leader</div>
      <div class="value green">{top_runs:,}</div>
      <div class="sub">{top_player}</div>
    </div>

    <div class="kpi">
      <div class="label">Most Sixes</div>
      <div class="value purple">{most_sixes}</div>
      <div class="sub">{six_player}</div>
    </div>

    <div class="kpi">
      <div class="label">Highest Individual Score</div>
      <div class="value amber">{highest_score}</div>
      <div class="sub">{highest_scorer}</div>
    </div>

    <div class="kpi">
      <div class="label">Best Strike Rate</div>
      <div class="value coral">{best_sr}</div>
      <div class="sub">{best_sr_name} (min 20 matches)</div>
    </div>

    <div class="kpi">
      <div class="label">Most Centuries</div>
      <div class="value blue">{most_centuries}</div>
      <div class="sub">{cent_player}</div>
    </div>

    <div class="kpi">
      <div class="label">Total Players</div>
      <div class="value green">{total_players:,}</div>
      <div class="sub">T20I career records</div>
    </div>

  </div>

  <div class="chart-card">
    <div class="section-title">Top 10 all-time T20 run scorers</div>
    <canvas id="runsChart"></canvas>
  </div>

  <div class="table-card">
    <div class="section-title">Top 10 — full stats</div>
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Player</th>
          <th>Span</th>
          <th style="text-align:right">Mat</th>
          <th style="text-align:right">Runs</th>
          <th style="text-align:right">HS</th>
          <th style="text-align:right">Avg</th>
          <th style="text-align:right">SR</th>
          <th style="text-align:right">100s</th>
          <th style="text-align:right">50s</th>
          <th style="text-align:right">6s</th>
        </tr>
      </thead>
      <tbody>
        {table_rows}
      </tbody>
    </table>
  </div>

  <footer>
    Generated by <span>t20_pipeline.py</span>
    running on AWS EC2 → uploaded to S3 static website
  </footer>

  <script>
    new Chart(document.getElementById('runsChart'), {{
      type: 'bar',
      data: {{
        labels: {json.dumps(chart_labels)},
        datasets: [{{
          label: 'Total Runs',
          data: {json.dumps(chart_runs)},
          backgroundColor: '#1D9E75',
          borderRadius: 5,
          borderSkipped: false,
        }}]
      }},
      options: {{
        responsive: true,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
          x: {{
            ticks: {{ color: '#9ca3af', font: {{ size: 11 }} }},
            grid:  {{ color: '#1e2229' }}
          }},
          y: {{
            ticks: {{
              color: '#9ca3af',
              font: {{ size: 11 }},
              callback: val => val.toLocaleString()
            }},
            grid: {{ color: '#1e2229' }}
          }}
        }}
      }}
    }});
  </script>

</body>
</html>"""

    print(f"  HTML built: {len(html):,} characters")
    return html


# ════════════════════════════════════════════════════════════
#  SECTION 5 — UPLOAD
#  Sends the HTML string directly to S3 Bucket 2.
#
#  Key points:
#    Body=html.encode("utf-8")
#      converts the Python string to bytes before sending
#      encode("utf-8") handles any special characters safely
#
#    ContentType="text/html"
#      tells S3 to serve this as a webpage in the browser
#      without this, S3 serves it as a file download
#
#    If index.html already exists in Bucket 2 it is
#    silently overwritten — this is intentional.
#    Every run = fresh report at the same URL.
# ════════════════════════════════════════════════════════════

def upload(html):
    print(f"[UPLOAD] Pushing to s3://{PUBLIC_BUCKET}/{REPORT_KEY} ...")
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket      = PUBLIC_BUCKET,
        Key         = REPORT_KEY,
        Body        = html.encode("utf-8"),
        ContentType = "text/html; charset=utf-8",
    )
    print(f"  Done — visit your S3 website URL to see the report")


# ════════════════════════════════════════════════════════════
#  SECTION 6 — MAIN
#  Calls each step in order.
#  If any step fails (wrong bucket name, missing column etc.)
#  Python stops here and prints the error message.
# ════════════════════════════════════════════════════════════

def run():
    print("=" * 55)
    print("  T20 PIPELINE — starting")
    print("=" * 55)

    df = load()
    df = clean(df)
    html = build_html(df)
    upload(html)

    print("=" * 55)
    print("  PIPELINE COMPLETE")
    print("=" * 55)


if __name__ == "__main__":
    run()
