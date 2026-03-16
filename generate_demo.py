#!/usr/bin/env python3
"""Generate a demo explorer.html with sample Contoso Retail data for GitHub Pages."""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate import generate_html

SAMPLE_DATA = {
    "modelName": "Contoso Retail Analytics",
    "tables": [
        {
            "name": "Fact Sales", "type": "fact",
            "columns": [
                {"name": "OrderID", "dataType": "Int64"},
                {"name": "OrderDate", "dataType": "DateTime"},
                {"name": "CustomerID", "dataType": "Int64"},
                {"name": "ProductID", "dataType": "Int64"},
                {"name": "StoreID", "dataType": "Int64"},
                {"name": "Quantity", "dataType": "Int64"},
                {"name": "UnitPrice", "dataType": "Decimal"},
                {"name": "DiscountAmount", "dataType": "Decimal"},
                {"name": "TotalAmount", "dataType": "Decimal"},
                {"name": "CostAmount", "dataType": "Decimal"}
            ],
            "measures": []
        },
        {
            "name": "Fact Inventory", "type": "fact",
            "columns": [
                {"name": "ProductID", "dataType": "Int64"},
                {"name": "StoreID", "dataType": "Int64"},
                {"name": "SnapshotDate", "dataType": "DateTime"},
                {"name": "OnHandQuantity", "dataType": "Int64"},
                {"name": "OnOrderQuantity", "dataType": "Int64"},
                {"name": "SafetyStockLevel", "dataType": "Int64"}
            ],
            "measures": []
        },
        {
            "name": "Fact Returns", "type": "fact",
            "columns": [
                {"name": "ReturnID", "dataType": "Int64"},
                {"name": "OrderID", "dataType": "Int64"},
                {"name": "ReturnDate", "dataType": "DateTime"},
                {"name": "ProductID", "dataType": "Int64"},
                {"name": "ReturnQuantity", "dataType": "Int64"},
                {"name": "ReturnReason", "dataType": "String"}
            ],
            "measures": []
        },
        {
            "name": "Dim Customer", "type": "dimension",
            "columns": [
                {"name": "CustomerID", "dataType": "Int64"},
                {"name": "CustomerName", "dataType": "String"},
                {"name": "Email", "dataType": "String"},
                {"name": "City", "dataType": "String"},
                {"name": "State", "dataType": "String"},
                {"name": "Country", "dataType": "String"},
                {"name": "Segment", "dataType": "String"},
                {"name": "JoinDate", "dataType": "DateTime"}
            ],
            "measures": []
        },
        {
            "name": "Dim Product", "type": "dimension",
            "columns": [
                {"name": "ProductID", "dataType": "Int64"},
                {"name": "ProductName", "dataType": "String"},
                {"name": "Category", "dataType": "String"},
                {"name": "SubCategory", "dataType": "String"},
                {"name": "Brand", "dataType": "String"},
                {"name": "Color", "dataType": "String"},
                {"name": "UnitCost", "dataType": "Decimal"},
                {"name": "ListPrice", "dataType": "Decimal"}
            ],
            "measures": []
        },
        {
            "name": "Dim Store", "type": "dimension",
            "columns": [
                {"name": "StoreID", "dataType": "Int64"},
                {"name": "StoreName", "dataType": "String"},
                {"name": "StoreType", "dataType": "String"},
                {"name": "City", "dataType": "String"},
                {"name": "State", "dataType": "String"},
                {"name": "Country", "dataType": "String"},
                {"name": "SquareMeters", "dataType": "Int64"},
                {"name": "OpenDate", "dataType": "DateTime"}
            ],
            "measures": []
        },
        {
            "name": "Dim Date", "type": "dimension",
            "columns": [
                {"name": "Date", "dataType": "DateTime"},
                {"name": "Year", "dataType": "Int64"},
                {"name": "Quarter", "dataType": "String"},
                {"name": "Month", "dataType": "String"},
                {"name": "MonthNumber", "dataType": "Int64"},
                {"name": "WeekNumber", "dataType": "Int64"},
                {"name": "DayOfWeek", "dataType": "String"},
                {"name": "IsWeekend", "dataType": "Boolean"},
                {"name": "FiscalYear", "dataType": "Int64"},
                {"name": "FiscalQuarter", "dataType": "String"}
            ],
            "measures": []
        },
        {
            "name": "_Sales Measures", "type": "measure",
            "columns": [],
            "measures": [
                {"name": "Total Revenue", "expression": "SUM('Fact Sales'[TotalAmount])"},
                {"name": "Total Cost", "expression": "SUM('Fact Sales'[CostAmount])"},
                {"name": "Total Quantity", "expression": "SUM('Fact Sales'[Quantity])"},
                {"name": "Total Discount", "expression": "SUM('Fact Sales'[DiscountAmount])"},
                {"name": "Gross Profit", "expression": "[Total Revenue] - [Total Cost]"},
                {"name": "Gross Margin %", "expression": "DIVIDE([Gross Profit], [Total Revenue], 0)"},
                {"name": "Net Revenue", "expression": "[Total Revenue] - [Total Discount]"},
                {"name": "Average Order Value", "expression": "DIVIDE([Total Revenue], DISTINCTCOUNT('Fact Sales'[OrderID]), 0)"},
                {"name": "Revenue per Unit", "expression": "DIVIDE([Total Revenue], [Total Quantity], 0)"},
                {"name": "Discount Rate", "expression": "DIVIDE([Total Discount], [Total Revenue], 0)"},
                {"name": "Revenue YTD", "expression": "TOTALYTD([Total Revenue], 'Dim Date'[Date])"},
                {"name": "Revenue vs PY", "expression": "VAR _CurrentRevenue = [Total Revenue]\nVAR _PYRevenue = CALCULATE([Total Revenue], SAMEPERIODLASTYEAR('Dim Date'[Date]))\nRETURN\n    DIVIDE(_CurrentRevenue - _PYRevenue, _PYRevenue, 0)"},
                {"name": "Revenue PY", "expression": "CALCULATE([Total Revenue], SAMEPERIODLASTYEAR('Dim Date'[Date]))"},
                {"name": "Revenue Growth", "expression": "[Total Revenue] - [Revenue PY]"},
                {"name": "Revenue Rolling 3M", "expression": "CALCULATE([Total Revenue], DATESINPERIOD('Dim Date'[Date], MAX('Dim Date'[Date]), -3, MONTH))"}
            ]
        },
        {
            "name": "_Customer Measures", "type": "measure",
            "columns": [],
            "measures": [
                {"name": "Total Customers", "expression": "DISTINCTCOUNT('Fact Sales'[CustomerID])"},
                {"name": "New Customers", "expression": "VAR _CurrentPeriodCustomers = VALUES('Fact Sales'[CustomerID])\nVAR _PriorCustomers =\n    CALCULATETABLE(\n        VALUES('Fact Sales'[CustomerID]),\n        DATEADD('Dim Date'[Date], -1, YEAR)\n    )\nRETURN\n    COUNTROWS(EXCEPT(_CurrentPeriodCustomers, _PriorCustomers))"},
                {"name": "Returning Customers", "expression": "[Total Customers] - [New Customers]"},
                {"name": "Customer Retention Rate", "expression": "DIVIDE([Returning Customers], [Total Customers], 0)"},
                {"name": "Revenue per Customer", "expression": "DIVIDE([Total Revenue], [Total Customers], 0)"},
                {"name": "Avg Orders per Customer", "expression": "DIVIDE(DISTINCTCOUNT('Fact Sales'[OrderID]), [Total Customers], 0)"},
                {"name": "Customer Lifetime Value", "expression": "[Revenue per Customer] * [Avg Orders per Customer]"}
            ]
        },
        {
            "name": "_Inventory Measures", "type": "measure",
            "columns": [],
            "measures": [
                {"name": "Current Stock", "expression": "SUM('Fact Inventory'[OnHandQuantity])"},
                {"name": "On Order", "expression": "SUM('Fact Inventory'[OnOrderQuantity])"},
                {"name": "Safety Stock", "expression": "SUM('Fact Inventory'[SafetyStockLevel])"},
                {"name": "Stock Coverage Days", "expression": "VAR _DailyDemand = DIVIDE([Total Quantity], 365, 0)\nRETURN\n    DIVIDE([Current Stock], _DailyDemand, 0)"},
                {"name": "Below Safety Stock", "expression": "CALCULATE(\n    COUNTROWS('Fact Inventory'),\n    'Fact Inventory'[OnHandQuantity] < 'Fact Inventory'[SafetyStockLevel]\n)"},
                {"name": "Inventory Turnover", "expression": "DIVIDE([Total Cost], [Current Stock], 0)"}
            ]
        },
        {
            "name": "_Returns Measures", "type": "measure",
            "columns": [],
            "measures": [
                {"name": "Total Returns", "expression": "COUNTROWS('Fact Returns')"},
                {"name": "Return Quantity", "expression": "SUM('Fact Returns'[ReturnQuantity])"},
                {"name": "Return Rate", "expression": "DIVIDE([Return Quantity], [Total Quantity], 0)"},
                {"name": "Return Rate by Orders", "expression": "DIVIDE(\n    DISTINCTCOUNT('Fact Returns'[OrderID]),\n    DISTINCTCOUNT('Fact Sales'[OrderID]),\n    0\n)"}
            ]
        }
    ],
    "reports": [
        {
            "name": "Sales - Executive Dashboard",
            "domain": "Sales",
            "pages": [
                {
                    "name": "Overview",
                    "visuals": 8,
                    "visualTypes": {"card": 4, "lineChart": 1, "clusteredBarChart": 1, "pieChart": 1, "table": 1},
                    "measures": ["Total Revenue", "Gross Profit", "Gross Margin %", "Total Quantity", "Revenue YTD", "Revenue vs PY", "Average Order Value"],
                    "tables": ["Fact Sales", "Dim Date", "Dim Product"]
                },
                {
                    "name": "Revenue Trends",
                    "visuals": 5,
                    "visualTypes": {"lineChart": 2, "areaChart": 1, "clusteredBarChart": 1, "card": 1},
                    "measures": ["Total Revenue", "Revenue PY", "Revenue Growth", "Revenue Rolling 3M", "Revenue YTD"],
                    "tables": ["Fact Sales", "Dim Date"]
                },
                {
                    "name": "Profitability",
                    "visuals": 6,
                    "visualTypes": {"card": 2, "waterfallChart": 1, "clusteredBarChart": 2, "table": 1},
                    "measures": ["Total Revenue", "Total Cost", "Gross Profit", "Gross Margin %", "Net Revenue", "Total Discount", "Discount Rate"],
                    "tables": ["Fact Sales", "Dim Product", "Dim Store"]
                }
            ]
        },
        {
            "name": "Sales - Product Performance",
            "domain": "Sales",
            "pages": [
                {
                    "name": "Product Overview",
                    "visuals": 7,
                    "visualTypes": {"table": 1, "clusteredBarChart": 2, "treemap": 1, "card": 3},
                    "measures": ["Total Revenue", "Total Quantity", "Gross Margin %", "Revenue per Unit", "Average Order Value"],
                    "tables": ["Fact Sales", "Dim Product", "Dim Date"]
                },
                {
                    "name": "Category Analysis",
                    "visuals": 5,
                    "visualTypes": {"clusteredBarChart": 2, "pieChart": 1, "matrix": 1, "card": 1},
                    "measures": ["Total Revenue", "Gross Profit", "Total Quantity", "Gross Margin %"],
                    "tables": ["Fact Sales", "Dim Product"]
                }
            ]
        },
        {
            "name": "Sales - Store Analytics",
            "domain": "Sales",
            "pages": [
                {
                    "name": "Store Performance",
                    "visuals": 6,
                    "visualTypes": {"map": 1, "table": 1, "clusteredBarChart": 2, "card": 2},
                    "measures": ["Total Revenue", "Total Quantity", "Gross Profit", "Average Order Value", "Total Customers"],
                    "tables": ["Fact Sales", "Dim Store", "Dim Date"]
                }
            ]
        },
        {
            "name": "Customer - Segmentation",
            "domain": "Customer",
            "pages": [
                {
                    "name": "Customer Overview",
                    "visuals": 7,
                    "visualTypes": {"card": 3, "clusteredBarChart": 2, "donutChart": 1, "table": 1},
                    "measures": ["Total Customers", "New Customers", "Returning Customers", "Customer Retention Rate", "Revenue per Customer"],
                    "tables": ["Fact Sales", "Dim Customer", "Dim Date"]
                },
                {
                    "name": "Customer Value",
                    "visuals": 5,
                    "visualTypes": {"scatterChart": 1, "table": 1, "card": 2, "clusteredBarChart": 1},
                    "measures": ["Revenue per Customer", "Avg Orders per Customer", "Customer Lifetime Value", "Total Customers"],
                    "tables": ["Fact Sales", "Dim Customer"]
                }
            ]
        },
        {
            "name": "Inventory - Stock Management",
            "domain": "Inventory",
            "pages": [
                {
                    "name": "Stock Levels",
                    "visuals": 6,
                    "visualTypes": {"card": 3, "clusteredBarChart": 1, "table": 1, "gauge": 1},
                    "measures": ["Current Stock", "On Order", "Safety Stock", "Stock Coverage Days", "Below Safety Stock", "Inventory Turnover"],
                    "tables": ["Fact Inventory", "Dim Product", "Dim Store"]
                }
            ]
        },
        {
            "name": "Returns - Analysis",
            "domain": "Returns",
            "pages": [
                {
                    "name": "Returns Overview",
                    "visuals": 5,
                    "visualTypes": {"card": 2, "clusteredBarChart": 1, "pieChart": 1, "table": 1},
                    "measures": ["Total Returns", "Return Quantity", "Return Rate", "Return Rate by Orders", "Total Revenue"],
                    "tables": ["Fact Returns", "Fact Sales", "Dim Product", "Dim Date"]
                }
            ]
        }
    ],
    "domains": {
        "Sales": ["Sales - Executive Dashboard", "Sales - Product Performance", "Sales - Store Analytics"],
        "Customer": ["Customer - Segmentation"],
        "Inventory": ["Inventory - Stock Management"],
        "Returns": ["Returns - Analysis"]
    }
}

html = generate_html(SAMPLE_DATA)

out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs')
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, 'index.html')

with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"Generated demo: {out_path} ({len(html):,} bytes / {len(html)//1024} KB)")
