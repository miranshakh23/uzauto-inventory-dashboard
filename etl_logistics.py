"""
All.xlsx faylining "Containers" varag'idan Neon Postgres bazasiga yuklash.
(inventory.containers jadvali)

O'rnatish:
    pip install pandas openpyxl psycopg2-binary --break-system-packages

Ishlatish:
    export DATABASE_URL="postgresql://...neon.tech/inventory?..."
    python3 etl_logistics.py All.xlsx

Har bir konteyner uchun eng so'nggi (ACTUAL DATE bo'yicha) yozuv olinadi —
agar bir konteyner bir necha marta uchrasa, faqat oxirgi holati saqlanadi.
"""
import os
import sys
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    sys.exit("XATOLIK: DATABASE_URL environment o'zgaruvchisini o'rnating")


def main():
    if len(sys.argv) < 2:
        sys.exit("Ishlatish: python3 etl_logistics.py All.xlsx")
    path = sys.argv[1]

    print("Excel faylni o'qish (Containers varag'i)...")
    df = pd.read_excel(path, sheet_name="Containers")

    cols = ['CONTAINER NUMBER', 'CONSIGNEE', 'ROUTE', 'SUPPLIER NAME',
            'ACTUAL LOCATION', 'ACTUAL COUNTRY', 'ACTUAL DATE', 'COUNTRY', 'STATUS',
            'CONTAINER TYPE']
    sub = df[cols].copy()
    sub = sub[sub['CONTAINER NUMBER'].notna() & sub['ACTUAL LOCATION'].notna()]
    sub['ACTUAL DATE'] = pd.to_datetime(sub['ACTUAL DATE'], errors='coerce')

    # Har bir konteyner uchun eng so'nggi ACTUAL DATE'li qatorni olish
    sub = sub.sort_values('ACTUAL DATE').drop_duplicates('CONTAINER NUMBER', keep='last')
    sub['ACTUAL DATE'] = sub['ACTUAL DATE'].dt.date
    sub = sub.where(pd.notnull(sub), None)

    records = [tuple(r) for r in sub.itertuples(index=False, name=None)]
    print(f"{len(records)} ta noyob konteyner topildi. Bazaga yuklanmoqda...")

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    try:
        cur.execute("TRUNCATE inventory.containers")
        execute_values(cur, """
            INSERT INTO inventory.containers
            (container_number, consignee, route, supplier_name,
             actual_location, actual_country, actual_date, origin_country, status,
             container_type)
            VALUES %s
            ON CONFLICT (container_number) DO NOTHING
        """, records)
        conn.commit()
        print("Muvaffaqiyatli yuklandi:", len(records), "konteyner")
    except Exception as e:
        conn.rollback()
        print("XATOLIK:", e)
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
