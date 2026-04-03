/*
Q1: Which product categories drive the most revenue, and which
	ones are quietly damaging the customer experience? When a high-revenue category
	consistently earns low ratings, what should Olist do about it?
*/

SELECT
	oi.order_id AS order_id,
	CAST(o.order_purchase_timestamp AS DATE) AS purchase_date,
	CAST(o.order_estimated_delivery_date AS DATE) AS estimated_delivery_date,
	CAST(o.order_delivered_customer_date AS DATE) AS actual_delivery_date,
	REPLACE(pcnt.product_category_name, '_', ' ') AS product_category,
	oi.price AS product_price,
	orev.review_score AS review_score,
	DATEDIFF(DAY, 
		o.order_estimated_delivery_date, 
        o.order_delivered_customer_date) AS delivery_delay_days
FROM order_items oi
JOIN products p
	ON oi.product_id = p.product_id
JOIN product_category_name_translation pcnt
	ON pcnt.product_category_id = p.product_category_id
JOIN orders o 
	ON o.order_id = oi.order_id
JOIN order_reviews orev
	ON o.order_id = orev.order_id
JOIN order_status os
	ON os.order_status_id = o.order_status_id
WHERE 
	o.order_delivered_customer_date IS NOT NULL
	AND os.order_status = 'delivered'
ORDER BY purchase_date
