"""
DATA_Power_BI.xlsx faylidan Neon Postgres bazasiga to'liq yuklash.
(inventory.excess_analysis jadvali + haftalik trend)

O'rnatish:
    pip install pandas openpyxl psycopg2-binary --break-system-packages

Ishlatish:
    export DATABASE_URL="postgresql://...neon.tech/inventory?..."
    python3 etl_excess_analysis.py DATA_Power_BI.xlsx

Har kuni/3 kunda ishga tushirsangiz bo'ladi — barcha qism ma'lumotlari
har safar yangilanadi. Lekin HAFTALIK TREND uchun faqat shu haftaning
BIRINCHI yuklanishi saqlanadi (keyingi shu haftadagi qayta ishga
tushirishlar trend jadvaliga ta'sir qilmaydi) — shunday qilib trend
"hafta boshidagi" holatni ko'rsatadi.
"""
import os
import sys
import datetime
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    sys.exit("XATOLIK: DATABASE_URL environment o'zgaruvchisini o'rnating")


def to_date(v):
    if pd.isnull(v):
        return None
    try:
        return pd.Timestamp(v).date()
    except (TypeError, ValueError):
        return None


def main():
    if len(sys.argv) < 2:
        sys.exit("Ishlatish: python3 etl_excess_analysis.py DATA_Power_BI.xlsx")
    path = sys.argv[1]

    print("Excel faylni o'qish...")
    df = pd.read_excel(path, sheet_name="Sheet1")

    cols = ['PART', 'PART NAME', 'SUPPLIER', 'FROM COUNTRY', 'REGION', 'MFU',
            'PR_MODEL', 'USD PRICE', 'TOT STK', '$ TOT STK', 'EXCESS STK',
            '$ EXCESS STK2', 'Status', 'With Req?', 'TOT STK DOH',
            'EXCESS WKS', 'Last order date', 'Last Shipment', 'AVG DAILY REQ',
            '$ PLT STK', '$ PLT STK BNCH', '$ INTR STK', '$ TOT STK BNCH']
    sub = df[cols].copy()
    sub['Last order date'] = sub['Last order date'].apply(to_date)
    sub['Last Shipment'] = sub['Last Shipment'].apply(to_date)
    sub = sub.where(pd.notnull(sub), None)
    records = [tuple(r) for r in sub.itertuples(index=False, name=None)
               if r[0]]

    print(f"{len(records)} qator topildi. Bazaga yuklanmoqda...")

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    try:
        execute_values(cur, """
            INSERT INTO inventory.excess_analysis
            (part_number, part_name, supplier, from_country, region, mfu,
             pr_model, usd_price, tot_stk_qty, tot_stk_usd, excess_stk_qty,
             excess_stk_usd, status, with_req, covered_days,
             excess_wks, last_order_date, last_shipment, avg_daily_req,
             plt_stk_usd, plt_stk_bnch_usd, intr_stk_usd, tot_stk_bnch_usd)
            VALUES %s
            ON CONFLICT (part_number) DO UPDATE SET
                part_name = EXCLUDED.part_name,
                supplier = EXCLUDED.supplier,
                from_country = EXCLUDED.from_country,
                region = EXCLUDED.region,
                mfu = EXCLUDED.mfu,
                pr_model = EXCLUDED.pr_model,
                usd_price = EXCLUDED.usd_price,
                tot_stk_qty = EXCLUDED.tot_stk_qty,
                tot_stk_usd = EXCLUDED.tot_stk_usd,
                excess_stk_qty = EXCLUDED.excess_stk_qty,
                excess_stk_usd = EXCLUDED.excess_stk_usd,
                status = EXCLUDED.status,
                with_req = EXCLUDED.with_req,
                covered_days = EXCLUDED.covered_days,
                excess_wks = EXCLUDED.excess_wks,
                last_order_date = EXCLUDED.last_order_date,
                last_shipment = EXCLUDED.last_shipment,
                avg_daily_req = EXCLUDED.avg_daily_req,
                plt_stk_usd = EXCLUDED.plt_stk_usd,
                plt_stk_bnch_usd = EXCLUDED.plt_stk_bnch_usd,
                intr_stk_usd = EXCLUDED.intr_stk_usd,
                tot_stk_bnch_usd = EXCLUDED.tot_stk_bnch_usd,
                report_date = CURRENT_DATE,
                loaded_at = NOW()
        """, records)

        # ---- Haftalik trend: faqat shu haftaning birinchi yozuvi saqlanadi ----
        today = datetime.date.today()
        week_start = today - datetime.timedelta(days=today.weekday())  # Dushanba
        cur.execute("""
            INSERT INTO inventory.weekly_trend
                (week_start, total_inventory_usd, excess_usd, excess_items, total_items)
            SELECT %s,
                   COALESCE(SUM(tot_stk_usd), 0),
                   COALESCE(SUM(excess_stk_usd), 0),
                   COUNT(*) FILTER (WHERE with_req = 'EXCESS'),
                   COUNT(*)
            FROM inventory.excess_analysis
            ON CONFLICT (week_start) DO NOTHING
        """, (week_start,))

        conn.commit()
        print("Muvaffaqiyatli yuklandi:", len(records), "qator")
        print("Haftalik trend (agar bu haftaning birinchi yuklanishi bo'lsa) yozildi:", week_start)
    except Exception as e:
        conn.rollback()
        print("XATOLIK:", e)
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
