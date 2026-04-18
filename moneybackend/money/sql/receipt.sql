-- SQLite
CREATE TEMPORARY TABLE TEMP_TABLE1 AS
SELECT  
strftime('%Y-%m',money_receipt.date) AS MONTH, 
money_wallet.name,
SUM(amount) AS amount
FROM money_receipt
LEFT JOIN money_wallet ON
money_receipt.wallet_id = money_wallet.id
WHERE not money_wallet.deleted 
GROUP BY
money_wallet.name,
MONTH
ORDER BY
MONTH 
;
SELECT SUM(amount)
FROM TEMP_TABLE1;

SELECT name,SUM(amount)
FROM TEMP_TABLE1
GROUP BY name;