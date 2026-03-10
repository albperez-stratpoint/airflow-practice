Below is a **clean Markdown specification** designed to be **LLM-friendly**. It defines the **scenario, schemas, constraints, data anomalies, and dataset requirements** so another model can generate the synthetic dataset.

---

# Master Data Management Synthetic Dataset Specification

## 1. Overview

This specification defines a synthetic dataset for practicing **Master Data Management (MDM)** concepts.
The dataset simulates a telecommunications company integrating customer data from multiple operational systems.

The goal is to create datasets that contain:

* Duplicate customer identities across systems
* Inconsistent attribute formats
* Missing values
* Conflicting attribute values

These datasets will be used to practice:

* Entity resolution
* Record linkage
* Golden record creation
* Survivorship rules
* Cross-system identity mapping

---

# 2. Business Scenario

A telecommunications company operates three independent systems:

| System  | Purpose                                     |
| ------- | ------------------------------------------- |
| CRM     | Customer acquisition and contact management |
| Billing | Subscription plans and payments             |
| Support | Customer service tickets                    |

Each system stores customer information differently.
Customers may appear **multiple times across systems** and even **multiple times within a system**.

The organization wants to build an **MDM system that produces a unified "Golden Customer Record".**

---

# 3. Source Systems

## 3.1 CRM System

Purpose: sales and marketing contact management.

### Table: `crm_contacts`

| column         | type   | description           |
| -------------- | ------ | --------------------- |
| crm_contact_id | string | unique CRM identifier |
| first_name     | string | customer first name   |
| last_name      | string | customer last name    |
| email          | string | primary email         |
| phone          | string | phone number          |
| address        | string | street address        |
| city           | string | city                  |
| country        | string | country               |
| created_date   | date   | contact creation date |

### Characteristics

* Names may include **nicknames**
* Addresses may be outdated
* Phone numbers may not include country code
* Duplicate contacts may exist

Example:

| crm_contact_id | first_name | last_name | email                                             |
| -------------- | ---------- | --------- | ------------------------------------------------- |
| CRM1001        | Jon        | Smith     | [jon.smith@gmail.com](mailto:jon.smith@gmail.com) |
| CRM2055        | Jonathan   | Smith     | [jsmith@gmail.com](mailto:jsmith@gmail.com)       |

---

## 3.2 Billing System

Purpose: subscription and payment management.

### Table: `billing_accounts`

| column              | type   | description               |
| ------------------- | ------ | ------------------------- |
| billing_customer_id | string | billing system identifier |
| account_name        | string | full customer name        |
| billing_email       | string | billing contact email     |
| phone               | string | phone number              |
| billing_address     | string | billing address           |
| city                | string | city                      |
| country             | string | country                   |
| plan_type           | string | subscription plan         |
| account_start_date  | date   | subscription start        |

### Characteristics

* Names may be abbreviated
* Email may be missing
* Phone numbers often include country codes
* Billing address may differ from residential address

Example:

| billing_customer_id | account_name   | phone         |
| ------------------- | -------------- | ------------- |
| B8801               | Jonathan Smith | +639171234567 |
| B9910               | J Smith        | 9171234567    |

---

## 3.3 Support System

Purpose: customer support ticket management.

### Table: `support_users`

| column          | type   | description               |
| --------------- | ------ | ------------------------- |
| support_user_id | string | support system identifier |
| name            | string | full name                 |
| email           | string | login email               |
| phone           | string | phone number              |
| signup_date     | date   | account creation          |

### Characteristics

* Customers may create **multiple support accounts**
* Emails may contain typos
* Phone numbers often missing

Example:

| support_user_id | name       | email                                               |
| --------------- | ---------- | --------------------------------------------------- |
| S5019           | John Smith | [john.smith@gmail.com](mailto:john.smith@gmail.com) |
| S8123           | John S.    | [jon.smith@gmail.com](mailto:jon.smith@gmail.com)   |

---

# 4. Target MDM Model

The MDM system generates **Golden Customer Records**.

### Table: `mdm_customers`

| column          | type   | description          |
| --------------- | ------ | -------------------- |
| mdm_customer_id | string | master customer ID   |
| golden_name     | string | unified name         |
| golden_email    | string | chosen email         |
| golden_phone    | string | standardized phone   |
| golden_address  | string | standardized address |
| golden_city     | string | city                 |
| golden_country  | string | country              |

---

### Table: `mdm_customer_crosswalk`

Maps source records to master customers.

| column           | type   | description           |
| ---------------- | ------ | --------------------- |
| mdm_customer_id  | string | master customer ID    |
| source_system    | string | CRM, BILLING, SUPPORT |
| source_record_id | string | source identifier     |

Example:

| mdm_customer_id | source_system | source_record_id |
| --------------- | ------------- | ---------------- |
| MDM1001         | CRM           | CRM1001          |
| MDM1001         | BILLING       | B8801            |
| MDM1001         | SUPPORT       | S5019            |

---

# 5. Data Anomalies to Simulate

Synthetic data should intentionally include inconsistencies.

## 5.1 Name Variations

Examples:

```
Jon Smith
John Smith
Jonathan Smith
J. Smith
```

---

## 5.2 Email Variations

Examples:

```
jon.smith@gmail.com
john.smith@gmail.com
jsmith@gmail.com
```

Also include:

* occasional typos
* missing emails

---

## 5.3 Phone Number Formatting

Possible formats:

```
09171234567
9171234567
+639171234567
+63 917 123 4567
```

---

## 5.4 Address Variations

Examples:

```
21 Palm St
21 Palm Street
21 Palm St., Manila
```

---

## 5.5 Missing Fields

Approximate frequency:

| field   | missing rate |
| ------- | ------------ |
| email   | 10–15%       |
| phone   | 10%          |
| address | 20%          |

---

# 6. Duplicate Record Simulation

The dataset should contain duplicates across systems.

### Duplicate rates

| category                | rate   |
| ----------------------- | ------ |
| cross-system duplicates | 30–40% |
| intra-system duplicates | 10–15% |

Example duplicate cluster:

```
CRM:
Jon Smith

Billing:
Jonathan Smith

Support:
John Smith
```

All represent the same individual.

---

# 7. Dataset Size

Recommended dataset scale:

| table            | rows   |
| ---------------- | ------ |
| crm_contacts     | 20,000 |
| billing_accounts | 15,000 |
| support_users    | 25,000 |

Expected unique customers after deduplication:

```
~18,000
```

---

# 8. Survivorship Rules (Reference Only)

These rules guide golden record generation.

| attribute | rule                |
| --------- | ------------------- |
| name      | choose longest name |
| email     | prioritize CRM      |
| phone     | prioritize Billing  |
| address   | most complete value |

---

# 9. Optional Advanced Scenarios

### Identity changes

Example:

```
old email: jon@gmail.com
new email: john.smith@gmail.com
```

Historical attributes may exist.

---

# 10. Data Generation Guidelines

Use realistic synthetic data:

* common names
* realistic email domains
* geographically consistent addresses

Include noise:

* typos
* inconsistent formatting
* abbreviations
* missing values

---
