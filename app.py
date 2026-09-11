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
import functools
import psycopg2
import psycopg2.extras
from flask import Flask, jsonify, request, send_file, session, redirect, url_for, render_template_string

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-fallback-key")

DB_URL = os.environ.get("DATABASE_URL")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOGIN_USER = os.environ.get("LOGIN_USER")
LOGIN_PASS = os.environ.get("LOGIN_PASS")

LOGIN_PAGE = """
<!DOCTYPE html><html lang="uz"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kirish — UzAuto Motors</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0;}
  body{
    background:linear-gradient(120deg,#0f2a4a,#1c3f6e);
    min-height:100vh; display:flex; align-items:center; justify-content:center;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
  }
  .box{background:#fff; border-radius:14px; padding:36px 32px; width:340px; box-shadow:0 20px 60px rgba(0,0,0,.25);}
  .logo{width:44px;height:44px;border-radius:10px;background:#eaf1ff;display:flex;align-items:center;
    justify-content:center;font-size:20px;margin-bottom:14px;}
  h1{font-size:18px; color:#1c2733; margin-bottom:4px;}
  p{font-size:12.5px; color:#6b7686; margin-bottom:22px;}
  label{font-size:12px; color:#6b7686; font-weight:600; display:block; margin-bottom:5px;}
  input{
    width:100%; padding:10px 12px; border:1px solid #e3e7ee; border-radius:8px;
    font-size:14px; margin-bottom:14px; color:#1c2733;
  }
  input:focus{outline:none; border-color:#2f6fed;}
  button{
    width:100%; padding:11px; background:#2f6fed; color:#fff; border:none; border-radius:8px;
    font-size:14px; font-weight:600; cursor:pointer;
  }
  button:hover{background:#255ed6;}
  .err{background:#fdecea; color:#c0392b; font-size:12.5px; padding:9px 12px; border-radius:7px; margin-bottom:14px;}
</style></head>
<body>
  <form class="box" method="POST" action="/login">
    <div class="logo">🏭</div>
    <h1>UzAuto Motors</h1>
    <p>Inventory Dashboard — faqat ruxsat etilgan foydalanuvchilar uchun</p>
    {% if error %}<div class="err">Login yoki parol xato</div>{% endif %}
    <label>Login</label>
    <input type="text" name="username" autocomplete="username" required>
    <label>Parol</label>
    <input type="password" name="password" autocomplete="current-password" required>
    <button type="submit">Kirish</button>
  </form>
</body></html>
"""


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template_string(LOGIN_PAGE, error=False)
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    if LOGIN_USER and LOGIN_PASS and username == LOGIN_USER and password == LOGIN_PASS:
        session["authenticated"] = True
        return redirect(url_for("index"))
    return render_template_string(LOGIN_PAGE, error=True)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
