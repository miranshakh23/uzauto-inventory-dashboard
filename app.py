"""
UzAuto Motors Inventory Excess Analysis — jonli dashboard backend.

Neon Postgres bazasidan (inventory.excess_analysis va
inventory.weekly_trend jadvallaridan) real vaqtda o'qiydi.

Endpointlar:
  GET /                 -> sahifa
  GET /api/filters       -> filtr uchun region/mfu/supplier ro'yxati
  GET /api/summary       -> Excessive sahifasi ma'lumotlari (filtrlash mumkin)
  GET /api/inventory      -> Inventory sahifasi ma'lumotlari (filtrlash mumkin)
  GET /api/trend         -> haftalik trend (jami zaxira / excess)

Filtrlash: ?region=...&mfu=...&supplier=... (bo'sh yoki 'All' bo'lsa e'tiborsiz qoldiriladi)
"""
import os
import psycopg2
import psycopg2.extras
from flask import Flask, jsonify, request, send_file

app = Flask(__name__)

DB_URL = os.environ.get("DATABASE_URL")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_conn():
    return psycopg2.connect(DB_URL)


def build_filter(args):
    """Query-string dan WHERE bo'lagi va parametrlarni quradi."""
    clauses = []
    params = []
    for field, col in (("region", "region"), ("mfu", "mfu"), ("supplier", "supplier")):
        val = args.get(field)
        if val and val != "All":
            clauses.append(f"{col} = %s")
            params.append(val)
    where = (" AND " + " AND ".join(clauses)) if clauses else ""
    return where, params


@app.route("/")
def index():
    candidates = [
        os.path.join(BASE_DIR, "templates", "index.html"),
        os.path.join(BASE_DIR, "index.html"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return send_file(path)
    return "index.html topilmadi: " + str(os.listdir(BASE_DIR)), 404


@app.route("/api/filters")
def filters():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT region FROM inventory.excess_analysis WHERE region IS NOT NULL ORDER BY 1")
    region = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT mfu FROM inventory.excess_analysis WHERE mfu IS NOT NULL ORDER BY 1")
    mfu = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT supplier FROM inventory.excess_analysis WHERE supplier IS NOT NULL ORDER BY 1")
    supplier = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify({"region": region, "mfu": mfu, "supplier": supplier})


@app.route("/api/summary")
def summary():
    where, params = build_filter(request.args)
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(f"""
        SELECT
            COALESCE(SUM(tot_stk_usd), 0)    AS total_inventory_usd,
            COALESCE(SUM(excess_stk_usd), 0) AS excess_usd,
            COALESCE(SUM(excess_stk_qty), 0) AS excess_qty,
            COUNT(*)                          AS total_items,
            COUNT(*) FILTER (WHERE with_req = 'EXCESS') AS excess_items
        FROM inventory.excess_analysis WHERE 1=1 {where}
    """, params)
    kpi = cur.fetchone()

    cur.execute(f"""
        SELECT region AS name, SUM(excess_stk_usd) AS value
        FROM inventory.excess_analysis WHERE with_req = 'EXCESS' {where}
        GROUP BY region ORDER BY value DESC
    """, params)
    region = cur.fetchall()

    cur.execute(f"""
        SELECT
          CASE
            WHEN covered_days IS NULL THEN 'Noma''lum'
            WHEN covered_days <= 30 THEN '0-30'
            WHEN covered_days <= 60 THEN '31-60'
            WHEN covered_days <= 90 THEN '61-90'
            WHEN covered_days <= 120 THEN '91-120'
            ELSE '>120'
          END AS name,
          SUM(excess_stk_usd) AS value
        FROM inventory.excess_analysis WHERE with_req = 'EXCESS' {where}
        GROUP BY 1
    """, params)
    age = cur.fetchall()

    cur.execute(f"""
        SELECT mfu AS name, SUM(excess_stk_usd) AS value, SUM(excess_stk_qty) AS qty
        FROM inventory.excess_analysis WHERE with_req = 'EXCESS' {where}
        GROUP BY mfu ORDER BY value DESC LIMIT 8
    """, params)
    mfu = cur.fetchall()

    cur.execute(f"""
        SELECT from_country AS name, SUM(excess_stk_usd) AS value, SUM(excess_stk_qty) AS qty
        FROM inventory.excess_analysis WHERE with_req = 'EXCESS' {where}
        GROUP BY from_country ORDER BY value DESC LIMIT 10
    """, params)
    country = cur.fetchall()

    cur.execute(f"""
        SELECT supplier AS name, SUM(excess_stk_usd) AS value
        FROM inventory.excess_analysis WHERE with_req = 'EXCESS' {where}
        GROUP BY supplier ORDER BY value DESC LIMIT 10
    """, params)
    supplier = cur.fetchall()

    cur.execute(f"""
        SELECT pr_model AS name, SUM(excess_stk_usd) AS value
        FROM inventory.excess_analysis WHERE with_req = 'EXCESS' {where}
        GROUP BY pr_model ORDER BY value DESC LIMIT 8
    """, params)
    model = cur.fetchall()

    cur.execute(f"""
        SELECT part_number AS part, part_name AS name, supplier,
               from_country AS country, mfu,
               excess_stk_qty AS qty, excess_stk_usd AS usd,
               excess_wks, last_order_date, last_shipment, avg_daily_req
        FROM inventory.excess_analysis WHERE with_req = 'EXCESS' {where}
        ORDER BY excess_stk_usd DESC LIMIT 10
    """, params)
    top_parts = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify({
        "kpi": kpi, "region": region, "ageBuckets": age, "mfu": mfu,
        "country": country, "supplier": supplier, "model": model,
        "topParts": top_parts,
    })


@app.route("/api/inventory")
def inventory():
    where, params = build_filter(request.args)
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(f"""
        SELECT
            COALESCE(SUM(plt_stk_usd), 0)       AS plt_stk_usd,
            COALESCE(SUM(intr_stk_usd), 0)      AS intr_stk_usd,
            COALESCE(SUM(tot_stk_usd), 0)       AS tot_stk_usd,
            COALESCE(SUM(plt_stk_bnch_usd), 0)  AS plt_stk_bnch_usd,
            COALESCE(SUM(tot_stk_bnch_usd), 0)  AS tot_stk_bnch_usd,
            COUNT(*)                             AS total_items
        FROM inventory.excess_analysis WHERE 1=1 {where}
    """, params)
    kpi = cur.fetchone()

    cur.execute(f"""
        SELECT from_country AS name, SUM(tot_stk_usd) AS value
        FROM inventory.excess_analysis WHERE 1=1 {where}
        GROUP BY from_country ORDER BY value DESC LIMIT 10
    """, params)
    country = cur.fetchall()

    cur.execute(f"""
        SELECT supplier AS name, SUM(tot_stk_usd) AS value
        FROM inventory.excess_analysis WHERE 1=1 {where}
        GROUP BY supplier ORDER BY value DESC LIMIT 10
    """, params)
    supplier = cur.fetchall()

    cur.execute(f"""
        SELECT pr_model AS name, SUM(tot_stk_usd) AS value
        FROM inventory.excess_analysis WHERE 1=1 {where}
        GROUP BY pr_model ORDER BY value DESC LIMIT 8
    """, params)
    model = cur.fetchall()

    cur.execute(f"""
        SELECT mfu AS name, SUM(tot_stk_usd) AS value
        FROM inventory.excess_analysis WHERE 1=1 {where}
        GROUP BY mfu ORDER BY value DESC LIMIT 8
    """, params)
    mfu = cur.fetchall()

    cur.execute(f"""
        SELECT part_number AS part, part_name AS name, supplier,
               from_country AS country, mfu, tot_stk_qty AS qty, tot_stk_usd AS usd
        FROM inventory.excess_analysis WHERE 1=1 {where}
        ORDER BY tot_stk_usd DESC LIMIT 10
    """, params)
    top_parts = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify({
        "kpi": kpi, "country": country, "supplier": supplier,
        "model": model, "mfu": mfu, "topParts": top_parts,
    })


@app.route("/api/trend")
def trend():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT week_start, total_inventory_usd, excess_usd, excess_items, total_items
        FROM inventory.weekly_trend
        ORDER BY week_start ASC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({"weeks": rows})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
