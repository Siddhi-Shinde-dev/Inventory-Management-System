Inventory Management System for Small Businesses
A robust, web-based retail and warehouse management tech solution designed to replace manual stock tracking (notebooks/Excel) with an automated, secure, and data-driven platform. This application effectively prevents stockouts, overstocking, and revenue leakage by providing complete inventory visibility and role-based controls.

Project Objective
The core objective is to build a production-ready Business CRUD application that optimizes daily inventory operations for small retail shops, pharmacies, or warehouses. It enables users to track products, manage supplier networks, record sales with automatic stock deduction, and visualize business health through a comprehensive dashboard.

Key Features
Role-Based Authentication (RBAC): Secure user management with JWT tokens differentiating Admin (full control, reports, user management) and Staff (view and update stock only).
Product Management (CRUD): Full capability to create, read, update, and delete products, seamlessly mapped under specific categories.
Automated Stock Deduction: Every sales transaction automatically triggers an instantaneous reduction in the respective product's stock quantity.
Real-time Low-Stock Alert System: Dynamic visual badges and notifications appear on the main dashboard instantly when any product falls below its predefined threshold level.
Interactive Data Visualization: A dynamic dashboard powered by Chart.js displaying current stock levels and seasonal sales trends at a glance.
Business Reporting: Built-in capability to aggregate data and export complete inventory reports into PDF (via ReportLab) or CSV formats.
Advanced Filters & Search: Fast product lookup utilizing search strings and category filters.
Tech Stack & Architecture
Backend: Python, Flask REST API (Object-Oriented Programming, Custom Decorators, Exception Handling)
Database: PostgreSQL (Hosted on Supabase), SQLAlchemy ORM (Relational tables: users, products, suppliers, sales, categories)
Frontend: HTML5, CSS3, Bootstrap, Chart.js
Security: JWT (JSON Web Tokens) for session authentication
Utilities: ReportLab for file I/O operations (PDF generation)
Deployment Platform: Render
Execution & Setup Steps
Follow these precise steps to clone, configure, and execute the project on your local machine:

1. Clone the Repository
git clone [https://github.com/Siddhi-Shinde-dev/Inventory-Management-System.git](https://github.com/Siddhi-Shinde-dev/Inventory-Management-System.git)
cd Inventory-Management-System