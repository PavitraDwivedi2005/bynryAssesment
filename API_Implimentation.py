from flask import Blueprint, jsonify, g
from sqlalchemy import text
from datetime import datetime, timedelta
from functools import wraps

alerts_bp = Blueprint('alerts', __name__)

# --- Config constants (easy to change without touching logic) ---
RECENT_SALES_WINDOW_DAYS = 30
BUNDLE_THRESHOLD_MULTIPLIER = 1.5   # bundles need higher buffer since they depend on components
DEFAULT_REORDER_LEVEL = 10          # fallback if reorder_level isn't set on inventory row
MAX_ALERTS_PER_RESPONSE = 500       # safety cap — don't return 10k rows accidentally


def require_company_access(f):
    """
    Placeholder auth decorator.
    In a real app this would verify the requesting user
    actually belongs to this company. Skipping full auth
    implementation here but flagging it as necessary.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # TODO: check g.current_user.company_id == company_id
        return f(*args, **kwargs)
    return decorated


@alerts_bp.route('/api/companies/<int:company_id>/alerts/low-stock', methods=['GET'])
@require_company_access
def get_low_stock_alerts(company_id):
    """
    Returns low-stock alerts for all warehouses belonging to a company.
    Only includes products with recent sales activity (last 30 days).
    Calculates days until stockout based on avg daily sales velocity.
    """

    # First, make sure the company actually exists
    # Avoids leaking info — return 404 rather than an empty alerts list
    company = Company.query.get(company_id)
    if not company:
        return jsonify({"error": "Company not found"}), 404

    sales_window_start = datetime.utcnow() - timedelta(days=RECENT_SALES_WINDOW_DAYS)

    try:
        # Single query to pull everything we need.
        # I'm using raw SQL here because this is a read-heavy analytics query
        # with multiple joins and aggregations — SQLAlchemy ORM would make this
        # significantly harder to read and optimize.
        query = text("""
            WITH recent_sales AS (
                -- Aggregate sales per product per warehouse over the window
                -- quantity_change is negative for sales, so we flip it with ABS()
                SELECT
                    il.product_id,
                    il.warehouse_id,
                    SUM(ABS(il.quantity_change))                        AS total_sold,
                    COUNT(DISTINCT DATE(il.changed_at))                 AS active_days,
                    -- Daily velocity: total sold / days in window (not just active days)
                    -- Using full window length avoids inflating velocity for bursty products
                    ROUND(
                        SUM(ABS(il.quantity_change))::NUMERIC / :window_days,
                        2
                    )                                                   AS avg_daily_sales
                FROM inventory_logs il
                WHERE
                    il.change_type = 'sale'
                    AND il.changed_at >= :sales_window_start
                GROUP BY il.product_id, il.warehouse_id
            )

            SELECT
                p.id                                AS product_id,
                p.name                              AS product_name,
                p.sku,
                p.is_bundle,
                w.id                                AS warehouse_id,
                w.name                              AS warehouse_name,
                inv.quantity                        AS current_stock,
                inv.reorder_level,
                rs.avg_daily_sales,
                rs.total_sold,
                s.id                                AS supplier_id,
                s.name                              AS supplier_name,
                s.contact_email                     AS supplier_email

            FROM inventory inv

            -- Only warehouses that belong to this company
            JOIN warehouses w
                ON inv.warehouse_id = w.id
                AND w.company_id = :company_id
                AND w.is_active = TRUE

            JOIN products p
                ON inv.product_id = p.id
                AND p.is_active = TRUE

            -- Inner join: this filters out products with NO recent sales (business rule)
            JOIN recent_sales rs
                ON rs.product_id = inv.product_id
                AND rs.warehouse_id = inv.warehouse_id

            -- Supplier info for reordering — LEFT JOIN because supplier might not be set
            LEFT JOIN suppliers s
                ON p.supplier_id = s.id

            WHERE
                -- Only return rows where stock is actually below threshold
                -- Threshold check happens here to avoid fetching everything into Python
                inv.quantity <= CASE
                    WHEN p.is_bundle = TRUE
                        THEN COALESCE(inv.reorder_level, :default_reorder) * :bundle_multiplier
                    ELSE
                        COALESCE(inv.reorder_level, :default_reorder)
                END

            ORDER BY
                -- Most urgent first: lowest stock relative to threshold
                (inv.quantity::FLOAT / NULLIF(
                    CASE
                        WHEN p.is_bundle THEN COALESCE(inv.reorder_level, :default_reorder) * :bundle_multiplier
                        ELSE COALESCE(inv.reorder_level, :default_reorder)
                    END,
                0)) ASC

            LIMIT :max_alerts
        """)

        results = db.session.execute(query, {
            "company_id":           company_id,
            "sales_window_start":   sales_window_start,
            "window_days":          RECENT_SALES_WINDOW_DAYS,
            "default_reorder":      DEFAULT_REORDER_LEVEL,
            "bundle_multiplier":    BUNDLE_THRESHOLD_MULTIPLIER,
            "max_alerts":           MAX_ALERTS_PER_RESPONSE,
        }).fetchall()

    except Exception as e:
        # Log the real error internally, return a clean message to the client
        app.logger.error(f"Low stock query failed for company {company_id}: {str(e)}")
        return jsonify({"error": "Failed to fetch alerts"}), 500

    alerts = []
    for row in results:
        # Calculate days until stockout
        # If avg_daily_sales is somehow 0 (edge case — shouldn't happen due to
        # the JOIN filter but being safe), we skip or set to None
        if row.avg_daily_sales and row.avg_daily_sales > 0:
            days_until_stockout = round(row.current_stock / row.avg_daily_sales)
        else:
            days_until_stockout = None

        # Recalculate threshold cleanly in Python for the response field
        base_threshold = row.reorder_level if row.reorder_level else DEFAULT_REORDER_LEVEL
        threshold = int(base_threshold * BUNDLE_THRESHOLD_MULTIPLIER) if row.is_bundle else base_threshold

        alerts.append({
            "product_id":           row.product_id,
            "product_name":         row.product_name,
            "sku":                  row.sku,
            "warehouse_id":         row.warehouse_id,
            "warehouse_name":       row.warehouse_name,
            "current_stock":        row.current_stock,
            "threshold":            threshold,
            "days_until_stockout":  days_until_stockout,
            "supplier": {
                "id":               row.supplier_id,
                "name":             row.supplier_name,
                "contact_email":    row.supplier_email,
            } if row.supplier_id else None   # don't return empty supplier object
        })

    return jsonify({
        "alerts":       alerts,
        "total_alerts": len(alerts),
    }), 200
