/*
Q2: Is Olist's delivery promise actually holding up against
	customer expectations? Where are the biggest gaps between
	estimated and actual delivery, and which regions should
	operations fix first?
*/

WITH base AS (
    SELECT
        o.order_id,
        CAST(o.order_purchase_timestamp AS DATE) AS order_purchase_date,
        CAST(o.order_estimated_delivery_date AS DATE) AS estimated_delivery_date,
        CAST(o.order_delivered_customer_date AS DATE) AS delivered_date,
        customer_geo.geolocation_state AS customer_state,
        seller_geo.geolocation_state AS seller_state,
        DATEDIFF(day, o.order_estimated_delivery_date, o.order_delivered_customer_date) AS days_diff,
        CASE
            WHEN o.order_delivered_customer_date
                 > o.order_estimated_delivery_date THEN 1
            ELSE 0
        END AS is_late,

		-- lat/lang distance
        ROUND(
            6371 * ACOS(
                CASE
                    WHEN COS(RADIANS(customer_geo.gelocation_lat))
                         * COS(RADIANS(seller_geo.gelocation_lat))
                         * COS(RADIANS(seller_geo.geolcation_lng) - RADIANS(customer_geo.geolcation_lng))
                         + SIN(RADIANS(customer_geo.gelocation_lat))
                         * SIN(RADIANS(seller_geo.gelocation_lat))
                         > 1  THEN 1.0
                    WHEN COS(RADIANS(customer_geo.gelocation_lat))
                         * COS(RADIANS(seller_geo.gelocation_lat))
                         * COS(RADIANS(seller_geo.geolcation_lng) - RADIANS(customer_geo.geolcation_lng))
                         + SIN(RADIANS(customer_geo.gelocation_lat))
                         * SIN(RADIANS(seller_geo.gelocation_lat))
                         < -1 THEN -1.0
                    ELSE
                         COS(RADIANS(customer_geo.gelocation_lat))
                         * COS(RADIANS(seller_geo.gelocation_lat))
                         * COS(RADIANS(seller_geo.geolcation_lng) - RADIANS(customer_geo.geolcation_lng))
                         + SIN(RADIANS(customer_geo.gelocation_lat))
                         * SIN(RADIANS(seller_geo.gelocation_lat))
                END
            ),
        1) AS distance_km,
        ROW_NUMBER() OVER ( PARTITION BY o.order_id ORDER BY oi.order_item_id) AS rn
    FROM orders o
    JOIN customers c
		ON o.customer_id = c.customer_id
    JOIN order_status os
		ON o.order_status_id = os.order_status_id
    JOIN order_items oi
		ON o.order_id = oi.order_id
    JOIN sellers s ON oi.seller_id = s.seller_id
    CROSS APPLY (
        SELECT TOP 1 g.geolocation_state, g.gelocation_lat, g.geolcation_lng
        FROM geolocation g
        WHERE g.geolocation_zip_code_prefix = c.customer_zip_code_prefix
    ) customer_geo
    CROSS APPLY (
        SELECT TOP 1 g.geolocation_state, g.gelocation_lat, g.geolcation_lng
        FROM geolocation g
        WHERE g.geolocation_zip_code_prefix = s.seller_zip_code_prefix
    ) seller_geo
    WHERE
        os.order_status = 'delivered'
        AND o.order_delivered_customer_date IS NOT NULL
        AND o.order_estimated_delivery_date IS NOT NULL
        AND o.order_purchase_timestamp      IS NOT NULL
)
SELECT
    order_id,
    order_purchase_date,
    estimated_delivery_date,
    delivered_date,
    CASE customer_state
        WHEN 'AC' THEN 'Acre'
        WHEN 'AL' THEN 'Alagoas'
        WHEN 'AM' THEN 'Amazonas'
        WHEN 'AP' THEN 'Amapa'
        WHEN 'BA' THEN 'Bahia'
        WHEN 'CE' THEN 'Ceara'
        WHEN 'DF' THEN 'Distrito Federal'
        WHEN 'ES' THEN 'Espirito Santo'
        WHEN 'GO' THEN 'Goias'
        WHEN 'MA' THEN 'Maranhao'
        WHEN 'MG' THEN 'Minas Gerais'
        WHEN 'MS' THEN 'Mato Grosso do Sul'
        WHEN 'MT' THEN 'Mato Grosso'
        WHEN 'PA' THEN 'Para'
        WHEN 'PB' THEN 'Paraiba'
        WHEN 'PE' THEN 'Pernambuco'
        WHEN 'PI' THEN 'Piaui'
        WHEN 'PR' THEN 'Parana'
        WHEN 'RJ' THEN 'Rio de Janeiro'
        WHEN 'RN' THEN 'Rio Grande do Norte'
        WHEN 'RO' THEN 'Rondonia'
        WHEN 'RR' THEN 'Roraima'
        WHEN 'RS' THEN 'Rio Grande do Sul'
        WHEN 'SC' THEN 'Santa Catarina'
        WHEN 'SE' THEN 'Sergipe'
        WHEN 'SP' THEN 'Sao Paulo'
        WHEN 'TO' THEN 'Tocantins'
    END AS customer_state_name,
    CASE seller_state
         WHEN 'AC' THEN 'Acre'
        WHEN 'AL' THEN 'Alagoas'
        WHEN 'AM' THEN 'Amazonas'
        WHEN 'AP' THEN 'Amapa'
        WHEN 'BA' THEN 'Bahia'
        WHEN 'CE' THEN 'Ceara'
        WHEN 'DF' THEN 'Distrito Federal'
        WHEN 'ES' THEN 'Espirito Santo'
        WHEN 'GO' THEN 'Goias'
        WHEN 'MA' THEN 'Maranhao'
        WHEN 'MG' THEN 'Minas Gerais'
        WHEN 'MS' THEN 'Mato Grosso do Sul'
        WHEN 'MT' THEN 'Mato Grosso'
        WHEN 'PA' THEN 'Para'
        WHEN 'PB' THEN 'Paraiba'
        WHEN 'PE' THEN 'Pernambuco'
        WHEN 'PI' THEN 'Piaui'
        WHEN 'PR' THEN 'Parana'
        WHEN 'RJ' THEN 'Rio de Janeiro'
        WHEN 'RN' THEN 'Rio Grande do Norte'
        WHEN 'RO' THEN 'Rondonia'
        WHEN 'RR' THEN 'Roraima'
        WHEN 'RS' THEN 'Rio Grande do Sul'
        WHEN 'SC' THEN 'Santa Catarina'
        WHEN 'SE' THEN 'Sergipe'
        WHEN 'SP' THEN 'Sao Paulo'
        WHEN 'TO' THEN 'Tocantins'
    END AS seller_state_name,
    days_diff,
    is_late,
    distance_km
FROM base
WHERE rn = 1
ORDER BY
    order_purchase_date,
    customer_state;