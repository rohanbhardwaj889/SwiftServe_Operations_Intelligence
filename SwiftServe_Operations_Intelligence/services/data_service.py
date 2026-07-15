import pandas as pd
from pathlib import Path
from services.database import connect_database, USE_SQL_SERVER

# Path to CSV folder
DATA_FOLDER = Path(__file__).parent.parent / "data"


# -----------------------------------------------------
# WORK ORDERS
# -----------------------------------------------------
def get_work_orders():

    if USE_SQL_SERVER:
        connection = connect_database()

        query = """
        SELECT *
        FROM swiftserve_work_orders
        """

        df = pd.read_sql(query, connection)
        connection.close()
        return df

    return pd.read_csv(DATA_FOLDER / "swiftserve_work_orders.csv")


# -----------------------------------------------------
# TECHNICIANS
# -----------------------------------------------------
def get_technicians():

    if USE_SQL_SERVER:
        connection = connect_database()

        query = """
        SELECT *
        FROM swiftserve_technicians
        """

        df = pd.read_sql(query, connection)
        connection.close()
        return df

    return pd.read_csv(DATA_FOLDER / "swiftserve_technicians.csv")


# -----------------------------------------------------
# EQUIPMENT
# -----------------------------------------------------
def get_equipment():

    if USE_SQL_SERVER:
        connection = connect_database()

        query = """
        SELECT *
        FROM swiftserve_equipment
        """

        df = pd.read_sql(query, connection)
        connection.close()
        return df

    return pd.read_csv(DATA_FOLDER / "swiftserve_equipment.csv")


# -----------------------------------------------------
# DISPATCH LOGS
# -----------------------------------------------------
def get_dispatch_logs():

    if USE_SQL_SERVER:
        connection = connect_database()

        query = """
        SELECT *
        FROM swiftserve_dispatch_logs
        """

        df = pd.read_sql(query, connection)
        connection.close()
        return df

    return pd.read_csv(DATA_FOLDER / "swiftserve_dispatch_logs.csv")


# -----------------------------------------------------
# SLA METRICS
# -----------------------------------------------------
def get_sla_metrics():

    if USE_SQL_SERVER:
        connection = connect_database()

        query = """
        SELECT *
        FROM swiftserve_sla_metrics
        """

        df = pd.read_sql(query, connection)
        connection.close()
        return df

    return pd.read_csv(DATA_FOLDER / "swiftserve_sla_metrics.csv")


# -----------------------------------------------------
# TEST
# -----------------------------------------------------
if __name__ == "__main__":

    print("=" * 60)
    print("WORK ORDERS")
    print("=" * 60)
    print(get_work_orders().head())

    print("\n" + "=" * 60)
    print("TECHNICIANS")
    print("=" * 60)
    print(get_technicians().head())

    print("\n" + "=" * 60)
    print("EQUIPMENT")
    print("=" * 60)
    print(get_equipment().head())

    print("\n" + "=" * 60)
    print("DISPATCH LOGS")
    print("=" * 60)
    print(get_dispatch_logs().head())

    print("\n" + "=" * 60)
    print("SLA METRICS")
    print("=" * 60)
    print(get_sla_metrics().head())