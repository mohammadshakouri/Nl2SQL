# Example SQL queries and their natural language equivalents
# These demonstrate the expected behavior of the NL2SQL system

## Example 1: Simple customer query
**Question (FA):** کدام مشتریان در ماه گذشته بیش از ۵ میلیون تومان خرید کرده‌اند؟
**Expected SQL:**
```sql
SELECT c.Name, SUM(p.PurchaseAmount) as TotalPurchase
FROM Customers c
JOIN Purchases p ON p.CustomerID = c.CustomerID
WHERE p.PurchaseDate >= DATEADD(month, -1, GETDATE())
GROUP BY c.Name
HAVING SUM(p.PurchaseAmount) > 5000000;
```

## Example 2: Product sales analysis
**Question (FA):** محبوب‌ترین محصولات از نظر تعداد فروش کدامند؟
**Expected SQL:**
```sql
SELECT pr.ProductName, COUNT(p.PurchaseID) as SalesCount
FROM Products pr
JOIN Purchases p ON p.ProductID = pr.ProductID
GROUP BY pr.ProductName
ORDER BY SalesCount DESC
LIMIT 10;
```

## Example 3: Customer geographic distribution
**Question (FA):** چند مشتری در هر شهر داریم؟
**Expected SQL:**
```sql
SELECT City, COUNT(CustomerID) as CustomerCount
FROM Customers
GROUP BY City
ORDER BY CustomerCount DESC;
```

## Example 4: Average purchase amount
**Question (FA):** میانگین مبلغ خرید در سه ماه گذشته چقدر بوده است؟
**Expected SQL:**
```sql
SELECT AVG(PurchaseAmount) as AveragePurchase
FROM Purchases
WHERE PurchaseDate >= DATEADD(month, -3, GETDATE());
```

## Example 5: Top customers by purchase count
**Question (FA):** ۱۰ مشتری برتر از نظر تعداد خرید چه کسانی هستند؟
**Expected SQL:**
```sql
SELECT c.Name, COUNT(p.PurchaseID) as PurchaseCount
FROM Customers c
JOIN Purchases p ON p.CustomerID = c.CustomerID
GROUP BY c.Name
ORDER BY PurchaseCount DESC
LIMIT 10;
```

## Example 6: Category-wise sales
**Question (FA):** هر دسته از محصولات چقدر فروش داشته؟
**Expected SQL:**
```sql
SELECT pr.Category, SUM(p.PurchaseAmount) as TotalSales
FROM Products pr
JOIN Purchases p ON p.ProductID = pr.ProductID
GROUP BY pr.Category
ORDER BY TotalSales DESC;
```

## Example 7: Recent orders by status
**Question (FA):** سفارشات در انتظار ارسال از یک هفته گذشته تا الان چند تا هستند؟
**Expected SQL:**
```sql
SELECT COUNT(OrderID) as PendingOrders
FROM Orders
WHERE Status = 'در انتظار'
AND OrderDate >= DATEADD(day, -7, GETDATE());
```

## Example 8: Customer lifetime value
**Question (FA):** مجموع خرید هر مشتری از ابتدای عضویت چقدر بوده؟
**Expected SQL:**
```sql
SELECT c.Name, SUM(p.PurchaseAmount) as LifetimeValue
FROM Customers c
JOIN Purchases p ON p.CustomerID = c.CustomerID
GROUP BY c.Name
ORDER BY LifetimeValue DESC;
```

## Example 9: Products never purchased
**Question (FA):** کدام محصولات هنوز فروش نداشته‌اند؟
**Expected SQL:**
```sql
SELECT ProductName
FROM Products
WHERE ProductID NOT IN (SELECT DISTINCT ProductID FROM Purchases);
```

## Example 10: Monthly sales trend
**Question (FA):** روند فروش ماهانه در سال جاری چگونه بوده؟
**Expected SQL:**
```sql
SELECT MONTH(PurchaseDate) as Month, SUM(PurchaseAmount) as MonthlySales
FROM Purchases
WHERE YEAR(PurchaseDate) = YEAR(GETDATE())
GROUP BY MONTH(PurchaseDate)
ORDER BY Month;
```
