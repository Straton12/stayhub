<div align="center">

# 🏢 StayHub
### *Enterprise-Grade Hospitality, Booking & Multi-Service Marketplace Ecosystem*

[![Django](https://img.shields.io/badge/Django-5.0+-092E20?style=for-the-badge&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Database](https://img.shields.io/badge/Database-SQLite%20%2F%20PostgreSQL-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![M-Pesa](https://img.shields.io/badge/Gateway-M--Pesa%20Daraja-green?style=for-the-badge)](https://developer.safaricom.co.ke/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

</div>

---

## 📖 Table of Contents
1. [Overview](#-overview)
2. [Architecture & Modular Directory Structure](#-architecture--modular-directory-structure)
3. [Detailed Application Breakdown](#-detailed-application-breakdown)
4. [Tech Stack & Dependencies](#-tech-stack--dependencies)
5. [Local Installation & Setup Guide](#-local-installation--setup-guide)
6. [Environment Variables Reference](#-environment-variables-reference)
7. [Database Management & Migrations](#-database-management--migrations)
8. [Payment Gateway Integration (M-Pesa Daraja)](#-payment-gateway-integration-m-pesa-daraja)
9. [Notification Engine (Email & SMS)](#-notification-engine-email--sms)
10. [Running Tests & Development Workflow](#-running-tests--development-workflow)
11. [Production Deployment Guide](#-production-deployment-guide)
12. [Contributing Guidelines](#-contributing-guidelines)
13. [License](#-license)

---

## 📖 Overview

**StayHub** is an all-in-one, highly scalable web platform built with **Django**. It is designed to bridge the gap between hospitality management, multi-vendor services, and consumer marketplaces. 

By unifying short-stay accommodations (BnB), tour bookings, restaurant dining, garment care services, e-commerce storefronts, and Safaricom M-Pesa mobile money processing into a single integrated platform, StayHub delivers a complete operational solution for modern service enterprises.

---

## 🏗️ Architecture & Modular Directory Structure

StayHub uses a modular Django design pattern, isolating business domains into standalone applications within `stayhub_project/`:

```text
stayhub_project/
├── accounts/                  # User authentication & permissions (Custom User model)
├── bnb/                       # Short-stay rental listings and room reservations
├── guestaccount/              # Guest profiles & automated session middleware
├── laundry/                   # Garment service ordering and status tracking
├── marketplace/               # Public e-commerce storefront, carts & wishlists
├── network/                   # Provider network directory & business listings
├── notifications/             # Multi-channel notification pipeline (Console/Email/SMS)
├── payments/                  # M-Pesa Daraja STK push payment integration engine
├── restaurant/                # Dining menus, online ordering & table bookings
├── stayhub_project/           # Core Django settings, WSGI/ASGI, and routing configs
├── tours/                     # Tour itineraries, excursion scheduling & bookings
├── static/                    # Global frontend static assets (CSS, JS, Images)
├── media/                     # User-uploaded files, profile pictures, and assets
├── db.sqlite3                 # Local SQLite database instance
├── manage.py                  # Django administrative script CLI
├── requirements.txt           # Python package dependency manifest
├── .env                       # Local private environment variables
└── .env.example               # Template environment configuration file