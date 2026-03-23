import psycopg2
import random
from datetime import datetime, date, timedelta

DB_CONFIG = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "mysecretpassword", 
    "host": "localhost",
    "port": "5432"
}
def setup_disbursement_demo(num_records=100):
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        # STEP 1: Create Table
        print(">> TRACE: Initializing 'disbursements' table...")
        cur.execute("DROP TABLE IF EXISTS disbursements;")
        cur.execute("""
            CREATE TABLE disbursements (
                disbursement_id SERIAL PRIMARY KEY,
                product_type VARCHAR(50),
                customer_name VARCHAR(100),
                amount DECIMAL(15, 2),
                disbursement_date DATE,
                branch_region VARCHAR(50)
            );
        """)

        # STEP 2: Date Logic for "Previous Month" (Feb 2026)
        # Using date() requires the explicit import added above
        prev_month_start = date(2026, 2, 1)
        current_month_start = date(2026, 3, 1)

        # STEP 3: Generate Data
        products = ['Home Loan', 'Personal Loan', 'Car Loan', 'Gold Loan', 'Education Loan']
        regions = ['North', 'South', 'East', 'West', 'Central']
        data = []

        for i in range(num_records):
            product = random.choice(products)
            # 70% in Feb (Previous Month), 30% in March (Current Month)
            if i < 70:
                d_date = prev_month_start + timedelta(days=random.randint(0, 27))
            else:
                d_date = current_month_start + timedelta(days=random.randint(0, 18))

            amount = round(random.uniform(50000.0, 5000000.0), 2)
            region = random.choice(regions)
            cust = f"Customer_{i+1000}"
            
            data.append((product, cust, amount, d_date, region))

        # STEP 4: Bulk Ingest
        insert_query = """
            INSERT INTO disbursements (product_type, customer_name, amount, disbursement_date, branch_region)
            VALUES (%s, %s, %s, %s, %s)
        """
        cur.executemany(insert_query, data)
        conn.commit()
        print(f">> SUCCESS: 100 Disbursement records ingested for Feb/Mar 2026.")

    except Exception as e:
        print(f">> ERROR: {e}")
    finally:
        if 'conn' in locals() and conn:
            cur.close()
            conn.close()

if __name__ == "__main__":
    setup_disbursement_demo(100)