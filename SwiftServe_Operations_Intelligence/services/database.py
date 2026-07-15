import os
import pyodbc
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Database Configuration
SERVER = os.getenv("DB_SERVER")
DATABASE = os.getenv("DB_NAME")
DRIVER = os.getenv("DB_DRIVER")

# True = SQL Server (Local)
# False = CSV Files (Streamlit Cloud)
USE_SQL_SERVER = (
    os.getenv("USE_SQL_SERVER", "False").lower() == "true"
)


def connect_database():
    """
    Connect to SQL Server.
    Returns:
        pyodbc.Connection | None
    """

    # If SQL Server is disabled, return None.
    if not USE_SQL_SERVER:
        print("📂 CSV Mode Enabled")
        return None

    try:

        connection = pyodbc.connect(
            f"DRIVER={{{DRIVER}}};"
            f"SERVER={SERVER};"
            f"DATABASE={DATABASE};"
            "Trusted_Connection=yes;"
            "TrustServerCertificate=yes;"
        )

        print("✅ Connected to SQL Server successfully!")

        return connection

    except Exception as e:

        print("❌ Database Connection Failed")
        print(e)

        return None


# -----------------------------------------------------
# Test Connection
# -----------------------------------------------------

if __name__ == "__main__":

    if USE_SQL_SERVER:

        conn = connect_database()

        if conn:

            print("✅ Database is ready to use.")

            conn.close()

            print("🔒 Connection closed.")

    else:

        print("📂 Running in CSV Mode")