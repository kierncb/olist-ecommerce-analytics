import pandas as pd
import pyodbc
from sqlalchemy import create_engine, text
import urllib
import os
import time
import unicodedata
import re
import logging
from datetime import datetime
from dotenv import load_dotenv


# CONFIGURATION
SERVER   = os.getenv("DB_SERVER", "localhost")
DATABASE = os.getenv("DB_NAME", "olist_ecommerce_db")
CSV_DIR  = os.getenv("CSV_DIR", "./data")

USE_WINDOWS_AUTH = True



# LOGGING SETUP
LOG_FILE = os.path.join(CSV_DIR, f"ingestion_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# QA Report
qa_report = []

def qa(table, stage, original, after, reason=""):
    dropped = original - after
    pct     = (dropped / original * 100) if original > 0 else 0
    entry   = {
        "table":    table,
        "stage":    stage,
        "original": original,
        "after":    after,
        "dropped":  dropped,
        "pct":      round(pct, 2),
        "reason":   reason,
    }
    qa_report.append(entry)
    if dropped > 0:
        log.warning(
            f"[QA] {table} | {stage}: dropped {dropped:,} rows ({pct:.1f}%) — {reason}"
        )
    return after


# CONNECTION
def get_engine():
    if USE_WINDOWS_AUTH:
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={SERVER};"
            f"DATABASE={DATABASE};"
            f"Trusted_Connection=yes;"
        )
    else:
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={SERVER};"
            f"DATABASE={DATABASE};"
        )
    params = urllib.parse.quote_plus(conn_str)
    engine = create_engine(f"mssql+pyodbc:///?odbc_connect={params}", fast_executemany=True)
    return engine

# HELPERS
def csv(filename):
    return os.path.join(CSV_DIR, filename)

def load(msg, df, table, engine, **kwargs):
    log.info(f"  Loading {msg}...")
    t = time.time()
    df.to_sql(table, engine, if_exists="append", index=False, schema="dbo", **kwargs)
    log.info(f"  → {len(df):,} rows inserted into [{table}] ({time.time()-t:.1f}s)")

def make_id_map(values):
    vals = sorted(set(v for v in values if pd.notna(v) and str(v).strip() != ""))
    return {v: i+1 for i, v in enumerate(vals)}

# DATA CLEANING HELPERS
def normalize_text(s: str) -> str:
    """Normalize unicode accents → ASCII, lowercase, collapse spaces."""
    if not isinstance(s, str):
        return s
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

def coerce_numeric(df, cols, table):
    """Convert columns to numeric; log how many values went NaN."""
    for col in cols:
        before_nulls = df[col].isna().sum()
        df[col] = pd.to_numeric(df[col], errors="coerce")
        new_nulls = df[col].isna().sum() - before_nulls
        if new_nulls > 0:
            log.warning(f"[TYPE] {table}.{col}: {new_nulls:,} values coerced to NaN")
    return df

def coerce_datetime(df, cols, table):
    """Convert columns to datetime; log how many values went NaT."""
    for col in cols:
        before_nulls = df[col].isna().sum()
        df[col] = pd.to_datetime(df[col], errors="coerce")
        new_nulls = df[col].isna().sum() - before_nulls
        if new_nulls > 0:
            log.warning(f"[TYPE] {table}.{col}: {new_nulls:,} values coerced to NaT")
    return df

def check_range(df, col, min_val, max_val, table):
    """Log and filter rows where col is outside [min_val, max_val]."""
    mask    = df[col].between(min_val, max_val) | df[col].isna()
    n_bad   = (~mask).sum()
    if n_bad > 0:
        log.warning(f"[RANGE] {table}.{col}: {n_bad:,} rows outside [{min_val}, {max_val}] — dropped")
        qa(table, f"range check {col}", len(df), len(df) - n_bad, f"{col} outside [{min_val},{max_val}]")
    return df[mask]

def check_non_negative(df, cols, table):
    """Drop rows where any of the listed numeric cols is negative."""
    for col in cols:
        mask  = (df[col] >= 0) | df[col].isna()
        n_bad = (~mask).sum()
        if n_bad > 0:
            log.warning(f"[RANGE] {table}.{col}: {n_bad:,} negative values — dropped")
            qa(table, f"non-negative {col}", len(df), len(df) - n_bad, f"negative {col}")
        df = df[mask]
    return df

# MAIN
def main():
    engine = get_engine()
    log.info(f"Connected to {SERVER} / {DATABASE}")

    # READ ALL CSVs
    log.info("Reading CSV files...")

    customers  = pd.read_csv(csv("olist_customers_dataset.csv"),      dtype=str).fillna("")
    geo        = pd.read_csv(csv("olist_geolocation_dataset.csv"),     dtype=str).fillna("")
    orders     = pd.read_csv(csv("olist_orders_dataset.csv"),          dtype=str).fillna("")
    items      = pd.read_csv(csv("olist_order_items_dataset.csv"),     dtype=str).fillna("")
    payments   = pd.read_csv(csv("olist_order_payments_dataset.csv"),  dtype=str).fillna("")
    reviews    = pd.read_csv(csv("olist_order_reviews_dataset.csv"),   dtype=str).fillna("")
    products   = pd.read_csv(csv("olist_products_dataset.csv"),        dtype=str).fillna("")
    sellers    = pd.read_csv(csv("olist_sellers_dataset.csv"),         dtype=str).fillna("")
    categories = pd.read_csv(csv("product_category_name_translation.csv"), dtype=str).fillna("")

    # Strip whitespace from all column names and string values
    for df in [customers, geo, orders, items, payments, reviews, products, sellers, categories]:
        df.columns = df.columns.str.strip()
        for col in df.select_dtypes("object").columns:
            df[col] = df[col].str.strip()

    # Rename mismatched column names from Kaggle CSVs
    products.rename(columns={
        "product_name_lenght":        "product_name_length",
        "product_description_lenght": "product_description_length",
    }, inplace=True)

    reviews.rename(columns={
        "review_comment_message": "review_comment_description",
    }, inplace=True)

    log.info("All CSVs loaded.")

    # 2. LOOKUP TABLES
    log.info("Building lookup tables...")

    # state
    all_states = set(
        geo["geolocation_state"].str.upper().unique().tolist() +
        customers["customer_state"].str.upper().unique().tolist() +
        sellers["seller_state"].str.upper().unique().tolist()
    )
    state_map = make_id_map(all_states)
    state_df  = pd.DataFrame([{"state_id": v, "state_name": k} for k, v in state_map.items()])
    load("state", state_df, "state", engine)

    # city — normalize unicode & accents in city names
    city_src = (
        geo[["geolocation_city", "geolocation_state"]]
        .rename(columns={"geolocation_city": "city_name", "geolocation_state": "state_name"})
        .assign(
            city_name  = lambda d: d["city_name"].apply(normalize_text),
            state_name = lambda d: d["state_name"].str.upper()
        )
        .drop_duplicates(subset=["city_name", "state_name"])
        .reset_index(drop=True)
    )
    city_src = city_src[city_src["city_name"] != ""]
    city_src["city_id"]  = range(1, len(city_src) + 1)
    city_src["state_id"] = city_src["state_name"].map(state_map)
    load("city", city_src[["city_id", "city_name", "state_id"]], "city", engine)

    # order_status
    status_map = make_id_map(orders["order_status"].str.lower().unique())
    status_df  = pd.DataFrame([{"order_status_id": v, "order_status": k} for k, v in status_map.items()])
    load("order_status", status_df, "order_status", engine)

    # payment_type
    payment_map = make_id_map(payments["payment_type"].str.lower().unique())
    payment_df  = pd.DataFrame([{"payment_id": v, "payment_type": k} for k, v in payment_map.items()])
    load("payment_type", payment_df, "payment_type", engine)

    # product_category_name_translation
    categories = (
        categories[
            (categories["product_category_name"] != "") &
            (categories["product_category_name_english"] != "")
        ]
        .drop_duplicates(subset=["product_category_name"])
        .reset_index(drop=True)
    )
    categories.insert(0, "product_category_id", range(1, len(categories) + 1))
    category_map = dict(zip(categories["product_category_name"], categories["product_category_id"]))
    load("product_category_name_translation", categories, "product_category_name_translation", engine)

    # 3. GEOLOCATION
    log.info("Loading geolocation...")
    n0 = len(geo)

    geo["geolocation_lat"] = pd.to_numeric(geo["geolocation_lat"], errors="coerce")
    geo["geolocation_lng"] = pd.to_numeric(geo["geolocation_lng"], errors="coerce")
    geo["geolocation_state"] = geo["geolocation_state"].str.upper()

    bad_lat = geo["geolocation_lat"].isna().sum()
    bad_lng = geo["geolocation_lng"].isna().sum()
    if bad_lat: log.warning(f"[TYPE] geolocation.lat: {bad_lat:,} values coerced to NaN")
    if bad_lng: log.warning(f"[TYPE] geolocation.lng: {bad_lng:,} values coerced to NaN")

    # Range validation: Brazil bounding box
    geo = check_range(geo, "geolocation_lat", -33.75, 5.27,   "geolocation")
    geo = check_range(geo, "geolocation_lng", -73.99, -34.79, "geolocation")
    geo = geo.dropna(subset=["geolocation_lat", "geolocation_lng"])

    # average lat/lng per zip prefix
    geo_deduped = (
        geo.groupby("geolocation_zip_code_prefix", as_index=False)
        .agg(
            gelocation_lat    = ("geolocation_lat",   "mean"),
            geolcation_lng    = ("geolocation_lng",   "mean"),
            geolocation_state = ("geolocation_state", lambda x: x.mode()[0])
        )
    )
    qa("geolocation", "dedup by zip prefix", n0, len(geo_deduped), "kept mean lat/lng per zip")
    load("geolocation", geo_deduped, "geolocation", engine)
    valid_zips = set(geo_deduped["geolocation_zip_code_prefix"])

    # 4. SELLERS
    log.info("Loading entity tables...")
    n0 = len(sellers)
    sellers_clean = sellers[sellers["seller_zip_code_prefix"].isin(valid_zips)].copy()
    qa("sellers", "FK zip check", n0, len(sellers_clean), "zip not in geolocation")
    sellers_clean = sellers_clean[["seller_id", "seller_zip_code_prefix"]].drop_duplicates(subset=["seller_id"])
    load("sellers", sellers_clean, "sellers", engine)
    valid_sellers = set(sellers_clean["seller_id"])

    # 5. CUSTOMERS
    n0 = len(customers)
    customers_clean = customers[customers["customer_zip_code_prefix"].isin(valid_zips)].copy()
    qa("customers", "FK zip check", n0, len(customers_clean), "zip not in geolocation")
    customers_clean = customers_clean[
        ["customer_id", "customer_unique_id", "customer_zip_code_prefix"]
    ].drop_duplicates(subset=["customer_id"])
    load("customers", customers_clean, "customers", engine)
    valid_customers = set(customers_clean["customer_id"])

    # 6. PRODUCTS
    int_cols = [
        "product_name_length", "product_description_length",
        "product_photos_qty", "product_weight_g",
        "product_length_cm", "product_height_cm", "product_width_cm"
    ]
    products_clean = products.copy()
    products_clean["product_category_id"] = (
        products_clean["product_category_name"].str.lower().map(category_map)
    )
    products_clean = coerce_numeric(products_clean, int_cols, "products")
    products_clean = check_non_negative(products_clean, ["product_weight_g", "product_photos_qty"], "products")
    products_clean = (
        products_clean
        [["product_id", "product_category_id"] + int_cols]
        .drop_duplicates(subset=["product_id"])
    )
    load("products", products_clean, "products", engine)
    valid_products = set(products_clean["product_id"])

    # 7. ORDERS
    log.info("Loading transactional tables...")
    dt_cols = [
        "order_purchase_timestamp", "order_approved_at",
        "order_delivered_carrier_date", "order_delivered_customer_date",
        "order_estimated_delivery_date"
    ]
    orders_clean = orders.copy()
    orders_clean = coerce_datetime(orders_clean, dt_cols, "orders")
    orders_clean["order_status_id"] = orders_clean["order_status"].str.lower().map(status_map)

    n0 = len(orders_clean)
    orders_clean = orders_clean[orders_clean["customer_id"].isin(valid_customers)]
    qa("orders", "FK customer_id", n0, len(orders_clean), "customer_id not in customers")

    n0 = len(orders_clean)
    orders_clean = orders_clean[orders_clean["order_status_id"].notna()]
    qa("orders", "unmapped order_status", n0, len(orders_clean), "order_status not in lookup")

    orders_clean = (
        orders_clean
        [["order_id", "customer_id", "order_status_id"] + dt_cols]
        .drop_duplicates(subset=["order_id"])
    )
    load("orders", orders_clean, "orders", engine)
    valid_orders = set(orders_clean["order_id"])

    # 8. ORDER ITEMS
    items_clean = items.copy()
    items_clean = coerce_numeric(items_clean, ["order_item_id", "price", "freight_value"], "order_items")
    items_clean = coerce_datetime(items_clean, ["shipping_limit_date"], "order_items")
    items_clean = check_non_negative(items_clean, ["price", "freight_value"], "order_items")

    n0 = len(items_clean)
    items_clean = items_clean[items_clean["order_id"].isin(valid_orders)]
    qa("order_items", "FK order_id", n0, len(items_clean), "order_id not in orders")

    n0 = len(items_clean)
    items_clean = items_clean[items_clean["product_id"].isin(valid_products)]
    qa("order_items", "FK product_id", n0, len(items_clean), "product_id not in products")

    n0 = len(items_clean)
    items_clean = items_clean[items_clean["seller_id"].isin(valid_sellers)]
    qa("order_items", "FK seller_id", n0, len(items_clean), "seller_id not in sellers")

    items_clean = items_clean[[
        "order_id", "order_item_id", "product_id", "seller_id",
        "shipping_limit_date", "price", "freight_value"
    ]]
    load("order_items", items_clean, "order_items", engine)

    # 9. ORDER PAYMENTS
    payments_clean = payments.copy()
    payments_clean = coerce_numeric(
        payments_clean,
        ["payment_sequential", "payment_installments", "payment_value"],
        "order_payments"
    )
    payments_clean["payment_id"] = payments_clean["payment_type"].str.lower().map(payment_map)
    payments_clean = check_non_negative(payments_clean, ["payment_value"], "order_payments")

    n0 = len(payments_clean)
    payments_clean = payments_clean[payments_clean["order_id"].isin(valid_orders)]
    qa("order_payments", "FK order_id", n0, len(payments_clean), "order_id not in orders")

    n0 = len(payments_clean)
    payments_clean = payments_clean[payments_clean["payment_id"].notna()]
    qa("order_payments", "unmapped payment_type", n0, len(payments_clean), "payment_type not in lookup")

    n0 = len(payments_clean)
    payments_clean = payments_clean.drop_duplicates(subset=["order_id", "payment_sequential"])
    qa("order_payments", "dedup composite PK", n0, len(payments_clean),
       "duplicate (order_id, payment_sequential) — kept first")

    payments_clean = payments_clean[[
        "order_id", "payment_sequential", "payment_id",
        "payment_installments", "payment_value"
    ]]
    load("order_payments", payments_clean, "order_payments", engine)

    # 10. ORDER REVIEWS
    reviews_clean = reviews.copy()
    reviews_clean = coerce_numeric(reviews_clean, ["review_score"], "order_reviews")
    reviews_clean = coerce_datetime(
        reviews_clean,
        ["review_creation_date", "review_answer_timestamp"],
        "order_reviews"
    )

    for col in ["review_comment_title", "review_comment_description"]:
        reviews_clean[col] = reviews_clean[col].replace("", None)

    reviews_clean = check_range(reviews_clean, "review_score", 1, 5, "order_reviews")

    n0 = len(reviews_clean)
    reviews_clean = reviews_clean[reviews_clean["order_id"].isin(valid_orders)]
    qa("order_reviews", "FK order_id", n0, len(reviews_clean), "order_id not in orders")

    n0 = len(reviews_clean)
    reviews_clean = (
        reviews_clean
        .sort_values("review_answer_timestamp", ascending=False)
        .drop_duplicates(subset=["review_id"])
    )
    qa("order_reviews", "dedup review_id (PK only)", n0, len(reviews_clean),
       "duplicate review_id — kept latest; multiple reviews per order preserved")

    reviews_clean = reviews_clean[[
        "review_id", "order_id", "review_score",
        "review_comment_title", "review_comment_description",
        "review_creation_date", "review_answer_timestamp"
    ]]
    load("order_reviews", reviews_clean, "order_reviews", engine)

    # POST-LOAD VERIFICATION
    log.info("Running post-load row count verification...")
    tables = [
        "state", "city", "geolocation", "payment_type", "order_status",
        "product_category_name_translation", "sellers", "customers",
        "products", "orders", "order_items", "order_payments", "order_reviews"
    ]
    with engine.connect() as conn:
        db_counts = {
            t: conn.execute(text(f"SELECT COUNT(*) FROM dbo.{t}")).scalar()
            for t in tables
        }

    # FINAL SUMMARY
    print("\n" + "="*65)
    print("  LOAD COMPLETE — Final Row Counts")
    print("="*65)
    for t in tables:
        print(f"  {t:<50} {db_counts[t]:>8,}")

    print("\n" + "="*65)
    print("  QA DROP REPORT")
    print("="*65)
    print(f"  {'Table':<22} {'Stage':<28} {'Dropped':>8} {'%':>6}  Reason")
    print("  " + "-"*61)
    any_drops = False
    for r in qa_report:
        if r["dropped"] > 0:
            any_drops = True
            print(
                f"  {r['table']:<22} {r['stage']:<28} "
                f"{r['dropped']:>8,} {r['pct']:>5.1f}%  {r['reason']}"
            )
    if not any_drops:
        print("  No rows dropped.")
    print("="*65)
    print(f"\n  Full log saved to: {LOG_FILE}")


if __name__ == "__main__":
    main()