"""
UzAuto Motors Inventory Excess Analysis — jonli dashboard backend.

Bu Flask ilovasi Neon Postgres bazasidan (inventory.excess_analysis va
inventory.pareto_summary jadvallaridan) real vaqtda ma'lumot o'qiydi
va /api/summary endpoint orqali JSON qaytaradi. Frontend (index.html)
sahifa ochilganda shu endpointga so'rov yuboradi.

Excel yangilanganda faqat etl_excess_analysis.py skriptini qayta ishga
tushirasiz — sayt hech narsa qilmasdan avtomatik yangi ma'lumotni
ko'rsatadi, chunki u har safar bazadan jonli o'qiydi.
"""
import os
import psycopg2
import psycopg2.extras
from flask import Flask, jsonify, render_template

app = Flask(__name__, static_folder="static", template_folder="templates")

DB_URL = os.environ.get("DATABASE_URL")


def get_conn():
    return psycopg2.connect(DB_URL)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/summary")
def summary():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT
            COALESCE(SUM(tot_stk_usd), 0)    AS total_inventory_usd,
            COALESCE(SUM(excess_stk_usd), 0) AS excess_usd,
            COALESCE(SUM(excess_stk_qty), 0) AS excess_qty,
            COUNT(*)                          AS total_items,
            COUNT(*) FILTER (WHERE with_req = 'EXCESS') AS excess_items
        FROM inventory.excess_analysis
    """)
    kpi = cur.fetchone()

    cur.execute("""
        SELECT region AS name, SUM(excess_stk_usd) AS value
        FROM inventory.excess_analysis
        WHERE with_req = 'EXCESS'
        GROUP BY region ORDER BY value DESC
    """)
    region = cur.fetchall()

    cur.execute("""
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
        FROM inventory.excess_analysis
        WHERE with_req = 'EXCESS'
        GROUP BY 1
    """)
    age = cur.fetchall()

    cur.execute("""
        SELECT mfu AS name, SUM(excess_stk_usd) AS value
        FROM inventory.excess_analysis
        WHERE with_req = 'EXCESS'
        GROUP BY mfu ORDER BY value DESC LIMIT 8
    """)
    mfu = cur.fetchall()

    cur.execute("""
        SELECT from_country AS name, SUM(excess_stk_usd) AS value
        FROM inventory.excess_analysis
        WHERE with_req = 'EXCESS'
        GROUP BY from_country ORDER BY value DESC LIMIT 10
    """)
    country = cur.fetchall()

    cur.execute("""
        SELECT supplier AS name, SUM(excess_stk_usd) AS value
        FROM inventory.excess_analysis
        WHERE with_req = 'EXCESS'
        GROUP BY supplier ORDER BY value DESC LIMIT 10
    """)
    supplier = cur.fetchall()

    cur.execute("""
        SELECT pr_model AS name, SUM(excess_stk_usd) AS value
        FROM inventory.excess_analysis
        WHERE with_req = 'EXCESS'
        GROUP BY pr_model ORDER BY value DESC LIMIT 8
    """)
    model = cur.fetchall()

    cur.execute("""
        SELECT part_number AS part, part_name AS name, supplier,
               from_country AS country, mfu,
               excess_stk_qty AS qty, excess_stk_usd AS usd
        FROM inventory.excess_analysis
        WHERE with_req = 'EXCESS'
        ORDER BY excess_stk_usd DESC LIMIT 10
    """)
    top_parts = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify({
        "kpi": kpi,
        "region": region,
        "ageBuckets": age,
        "mfu": mfu,
        "country": country,
        "supplier": supplier,
        "model": model,
        "topParts": top_parts,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
