-- Core company/org structure
CREATE TABLE companies (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255) UNIQUE,
    phone           VARCHAR(50),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE warehouses (
    id              SERIAL PRIMARY KEY,
    company_id      INT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
    name            VARCHAR(255) NOT NULL,
    address_line1   VARCHAR(255),
    address_line2   VARCHAR(255),
    city            VARCHAR(100),
    country         VARCHAR(100),
    postal_code     VARCHAR(20),
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Suppliers are separate from companies (a supplier might supply multiple companies)
CREATE TABLE suppliers (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    contact_email   VARCHAR(255),
    contact_phone   VARCHAR(50),
    address         TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Links which suppliers supply which companies (many-to-many)
CREATE TABLE company_suppliers (
    company_id      INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    supplier_id     INT NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    since           DATE,
    PRIMARY KEY (company_id, supplier_id)
);

-- Products catalog (what exists, not where or how many)
CREATE TABLE products (
    id              SERIAL PRIMARY KEY,
    sku             VARCHAR(100) UNIQUE NOT NULL,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    price           NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
    is_bundle       BOOLEAN DEFAULT FALSE,
    supplier_id     INT REFERENCES suppliers(id) ON DELETE SET NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bundle contents: which products make up a bundle
-- A bundle can contain other bundles (recursive), handled at app layer
CREATE TABLE bundle_items (
    bundle_id       INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    component_id    INT NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    quantity        INT NOT NULL DEFAULT 1 CHECK (quantity > 0),
    PRIMARY KEY (bundle_id, component_id),
    CHECK (bundle_id != component_id)   -- a product can't contain itself
);

-- Inventory: how much of a product is at each warehouse
CREATE TABLE inventory (
    id              SERIAL PRIMARY KEY,
    product_id      INT NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    warehouse_id    INT NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    quantity        INT NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    reorder_level   INT DEFAULT 0,      -- optional low-stock threshold
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (product_id, warehouse_id)   -- one record per product per warehouse
);

-- Audit log: every time inventory changes, we write a row here
CREATE TABLE inventory_logs (
    id              SERIAL PRIMARY KEY,
    inventory_id    INT NOT NULL REFERENCES inventory(id) ON DELETE RESTRICT,
    product_id      INT NOT NULL,
    warehouse_id    INT NOT NULL,
    change_type     VARCHAR(50) NOT NULL,   -- 'restock', 'sale', 'transfer', 'adjustment', etc.
    quantity_before INT NOT NULL,
    quantity_change INT NOT NULL,           -- positive = added, negative = removed
    quantity_after  INT NOT NULL,
    reason          TEXT,
    changed_by      INT,                    -- user_id if you have auth, NULL for now
    changed_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_inventory_product     ON inventory(product_id);
CREATE INDEX idx_inventory_warehouse   ON inventory(warehouse_id);
CREATE INDEX idx_inventory_logs_inv    ON inventory_logs(inventory_id);
CREATE INDEX idx_inventory_logs_time   ON inventory_logs(changed_at);
CREATE INDEX idx_products_sku          ON products(sku);
CREATE INDEX idx_products_supplier     ON products(supplier_id);
CREATE INDEX idx_warehouses_company    ON warehouses(company_id);
