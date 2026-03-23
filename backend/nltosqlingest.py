import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Ensure these match your Docker container settings
DB_CONFIG = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "mysecretpassword", 
    "host": "localhost",
    "port": "5432"
}

def ingest_sensitive_data():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        print("--- RESETTING SCHEMA ---")
        cur.execute("DROP TABLE IF EXISTS retail_leads;")

        # Create Table with PII Columns
        cur.execute("""
            CREATE TABLE IF NOT EXISTS branch_performance (
                branch_id SERIAL PRIMARY KEY,
                branch_name VARCHAR(100),
                region VARCHAR(50),
                savings_accounts_opened INT,
                current_accounts_opened INT,
                total_deposit_value DECIMAL(15, 2),
                opening_date DATE
                );
        """)

        # Sample Data with CLEAR PII (Emails and Indian Phone Formats)
        pii_data = [
            ('Chennai-Main', 'South', 1250, 450, 5000000.00, '2026-01-15'),
            ('Mumbai-Bandra', 'West', 1100, 600, 7500000.00, '2026-01-20'),
            ('Bangalore-ITPL', 'South', 980, 300, 4200000.00, '2026-02-05'),
            ('Delhi-Connaught', 'North', 850, 550, 6800000.00, '2026-01-10'),
            ('Hyderabad-Hitech', 'South', 790, 280, 3100000.00, '2026-02-12'),
            ('Kolkata-ParkStreet', 'East', 720, 200, 2500000.00, '2026-01-25'),
            ('Pune-Hinjewadi', 'West', 680, 320, 2900000.00, '2026-02-18'),
            ('Ahmedabad-GiftCity', 'West', 610, 150, 2100000.00, '2026-01-30'),
            ('Gurgaon-CyberHub', 'North', 590, 410, 5400000.00, '2026-02-02'),
            ('Chennai-OMR', 'South', 550, 190, 1800000.00, '2026-01-05')
        ]

        # Batch Insert
        insert_query = """
            INSERT INTO branch_performance (branch_name, region, savings_accounts_opened, current_accounts_opened, total_deposit_value, opening_date) 
            VALUES (%s, %s, %s, %s, %s, %s);
        """
        cur.executemany(insert_query, pii_data)

        conn.commit()
        print(f"✅ Ingested {len(pii_data)} records with PII successfully.")
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"❌ Ingestion Failed: {e}")

if __name__ == "__main__":
    ingest_sensitive_data()