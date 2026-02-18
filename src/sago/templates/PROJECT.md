# sago MASTER TEMPLATE

> **sago Framework**  
> A comprehensive project management template that forces AI into "Atomic Task" mode using structured documentation.

---

## 📋 PROJECT.md

### Project Vision
We are making a better, faster version of GSD in python

### Tech Stack & Constraints
* **Language:** Python 3.11+ (Type hints required)
* **Framework:** FastAPI (Backend), Typer (CLI)
* **Database:** SQLite (Dev), PostgreSQL (Prod)
* **Testing:** Pytest (Must achieve 80% coverage)
* **Style:** Black formatter, ruff linter

### Core Architecture
* **Modular Monolith:** Logic must be separated into `src/modules/`
* **No Circular Imports:** Strictly enforced
* **Config:** 12-factor app pattern using `.env`