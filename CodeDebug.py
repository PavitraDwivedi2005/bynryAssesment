from flask import request, jsonify
from sqlalchemy.exc import IntegrityError
from decimal import Decimal, InvalidOperation

@app.route('/api/products', methods=['POST'])
def create_product():
    data = request.get_json()

    # Basic check — make sure we even got JSON
    if not data:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    # Check required fields
    required_fields = ['name', 'sku', 'price', 'warehouse_id']
    missing = [f for f in required_fields if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    # Validate price is actually a number
    try:
        price = Decimal(str(data['price']))
        if price < 0:
            return jsonify({"error": "Price cannot be negative"}), 400
    except (InvalidOperation, TypeError):
        return jsonify({"error": "Price must be a valid number"}), 400

    # Check warehouse actually exists
    warehouse = Warehouse.query.get(data['warehouse_id'])
    if not warehouse:
        return jsonify({"error": "Warehouse not found"}), 404

    # Check SKU uniqueness before trying to insert
    existing = Product.query.filter_by(sku=data['sku']).first()
    if existing:
        return jsonify({"error": f"SKU '{data['sku']}' already exists"}), 409

    # Default initial_quantity to 0 if not provided
    initial_quantity = data.get('initial_quantity', 0)

    try:
        # Wrap both inserts in a single transaction
        product = Product(
            name=data['name'],
            sku=data['sku'],
            price=price,
            warehouse_id=data['warehouse_id']
        )
        db.session.add(product)
        db.session.flush()  # gets product.id without committing yet

        inventory = Inventory(
            product_id=product.id,
            warehouse_id=data['warehouse_id'],
            quantity=initial_quantity
        )
        db.session.add(inventory)

        db.session.commit()  # single commit — both succeed or neither does

    except IntegrityError:
        db.session.rollback()
        # Catches any race condition on SKU uniqueness at DB level
        return jsonify({"error": "Could not create product, possible duplicate SKU"}), 409
    except Exception as e:
        db.session.rollback()
        # Don't leak internal error details to the client
        app.logger.error(f"Product creation failed: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

    return jsonify({
        "message": "Product created successfully",
        "product_id": product.id,
        "sku": product.sku,
        "warehouse_id": data['warehouse_id']
    }), 201
