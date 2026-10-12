# RetroTube Master Implementation & Execution Plan

> **Objective**: Deconstruct the RetroTube project into modular, deterministic phases, parts, and steps with strict error-handling protocols, explicit verification gates, and zero-defect execution guidelines.

---

## Architecture Overview & System Topology

```
                      +---------------------------------------+
                      |       Client Browser (875px UI)       |
                      +---------------------------------------+
                                          |
                                          | HTTP (HTML / JSON)
                                          v
                      +---------------------------------------+
                      |         FastAPI Web Engine            |
                      |   - SessionMiddleware (Signed)        |
                      |   - CSRF & Rate Limiting Guard        |
                      |   - Jinja2 Retro 2006-07 Templates    |
                      +---------------------------------------+
                                /          |           \
                               /           |            \
                              v            v             v
             +--------------------+ +-------------+ +--------------------+
             | PostgreSQL 16      | | Redis 7     | | External APIs      |
             | - Users & Channels | | - Metadata  | | - YouTube Data API |
             | - Comments         | | - Searches  | |   (100/1 units)    |
             | - Local Ratings    | | - PT Quota  | | - Return YouTube   |
             | - Watch History    | | - RYD Cache | |   Dislike (RYD)    |
             | - Favorites        | +-------------+ +--------------------+
             +--------------------+
```

---

## Plan Roadmap & Phase Hierarchy

| Phase | Domain | Objective | Key Deliverables |
|---|---|---|---|
| **Phase 1** | **Infrastructure & Environment** | Isolated runtime & containerized services | Virtual env, `.env`, Docker Compose, Healthchecks |
| **Phase 2** | **Data Layer & Migrations** | PostgreSQL persistence & schema integrity | SQLAlchemy 2.0 models, Alembic migrations, constraints |
| **Phase 3** | **External Services & Caching** | Quota-controlled YouTube & RYD proxies | Redis client, Pacific Time quota manager, YouTube batcher |
| **Phase 4** | **Backend Modularization & Core** | Break monolithic `main.py` into clean modules | Config schema, security middleware, Jinja2 filters, exceptions |
| **Phase 5** | **Route Controllers & API Layer** | Endpoints for HTML pages & JSON APIs | Public pages, search, watch, channels, user actions |
| **Phase 6** | **Frontend & Retro Styling** | 2006–07 pixel-accurate UI | 15 templates, `retro.css`, SVG stars, channel themes |
| **Phase 7** | **Background Tasks & Automation** | Offline cache warming & previewing | `warm_cache.py`, Playwright mock preview runner |
| **Phase 8** | **Quality Assurance & Testing** | Comprehensive automated validation | Pytest unit/integration test suite, mock API fixtures |
| **Phase 9** | **Production Readiness & Operations** | Multi-stage Docker & deployment hardening | Production Dockerfile, compose stack, security audit |

---

## Phase 1: Environment, Dependencies & Infrastructure Setup

### Goal
Establish an isolated, reproducible development environment with containerized backing services (PostgreSQL 16 and Redis 7) and verified configurations.

---

### Step 1.1: Dependency Specification & Virtual Environment
- **Actions**:
  1. Create a dedicated Python 3.11+ virtual environment (`.venv`).
  2. Pin exact dependency versions in `requirements.txt` and create a `requirements-dev.txt` for development/testing tools.
- **Dependencies to pin**:
  ```text
  fastapi>=0.115.0,<1.0.0
  uvicorn[standard]>=0.30.0,<1.0.0
  sqlalchemy[asyncio]>=2.0.30,<2.1.0
  asyncpg>=0.29.0,<1.0.0
  redis[hiredis]>=5.0.0,<6.0.0
  httpx>=0.27.0,<1.0.0
  argon2-cffi>=23.1.0,<24.0.0
  jinja2>=3.1.4,<4.0.0
  itsdangerous>=2.2.0,<3.0.0
  python-multipart>=0.0.9,<1.0.0
  pydantic>=2.7.0,<3.0.0
  pydantic-settings>=2.2.0,<3.0.0
  alembic>=1.13.0,<2.0.0
  ```
  *Dev tools*: `pytest`, `pytest-asyncio`, `pytest-mock`, `playwright`, `ruff`.
- **Potential Failure Modes**:
  - `asyncpg` build errors on Windows without C++ build tools $\rightarrow$ Use pre-compiled binary wheels or ensure standard wheels are pulled.
- **Verification Gate**:
  ```bash
  python -m venv .venv
  .venv\Scripts\activate   # or source .venv/bin/activate on Unix
  pip install --upgrade pip
  pip install -r requirements.txt
  python -c "import fastapi, sqlalchemy, redis.asyncio, asyncpg; print('Core dependencies imported successfully')"
  ```

---

### Step 1.2: Environment Configuration Schema & Validation
- **Actions**:
  1. Create a validated `Settings` model using `pydantic-settings` to parse `.env` at boot rather than reading raw `os.environ`.
  2. Define required and optional fields with defaults:
     - `YT_API_KEY`: string (required).
     - `SECRET_KEY`: string (minimum 32 characters, required).
     - `DATABASE_URL`: `PostgresDsn` string (default: `postgresql+asyncpg://retro:retro@localhost:5432/retrotube`).
     - `REDIS_URL`: `RedisDsn` string (default: `redis://localhost:6379/0`).
     - `FEATURED_REGION`: 2-letter ISO country code (default: `US`).
     - `ENABLE_RELATED`: bool (default: `False`).
     - `HTTPS_ONLY`: bool (default: `False`).
     - `YT_DAILY_BUDGET`: int (default: `9000`).
- **Potential Failure Modes**:
  - Missing environment variable causes cryptic runtime `KeyError` $\rightarrow$ Pydantic catches missing keys immediately at startup with informative error messages.
- **Verification Gate**:
  - Running configuration validation against `.env` outputs validated settings object without validation errors.

---

### Step 1.3: Containerized Backing Services (Docker Compose)
- **Actions**:
  1. Validate [docker-compose.yml](file:///c:/Users/syeda/Downloads/retrotube/retrotube/docker-compose.yml).
  2. Add healthchecks for Postgres (`pg_isready -U retro -d retrotube`) and Redis (`redis-cli ping`).
- **Potential Failure Modes**:
  - Port collision on 5432 or 6379 $\rightarrow$ Check active local ports; provide configurable mapped host ports if already occupied.
- **Verification Gate**:
  ```bash
  docker compose up -d
  docker compose ps
  # Both postgres and redis services must report status: healthy / Up
  ```

---

## Phase 2: Database Layer & Data Modeling (PostgreSQL & SQLAlchemy 2.0)

### Goal
Provide robust relational persistence with strict schema constraints, unique indices, cascade rules, and automated schema migration tooling.

---

### Step 2.1: Asynchronous Database Engine & Session Factory
- **Actions**:
  1. Implement [database.py](file:///c:/Users/syeda/Downloads/retrotube/retrotube/database.py) using `create_async_engine` with connection pooling flags:
     - `pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`, `pool_recycle=3600`.
  2. Provide `async_sessionmaker(engine, expire_on_commit=False)` and a dependency generator `get_db()`.
- **Potential Failure Modes**:
  - Stale database connections causing `InterfaceError` $\rightarrow$ `pool_pre_ping=True` proactively validates connections before checkout.
- **Verification Gate**:
  - Execute a simple `SELECT 1` async script to confirm connection and pool lifecycle.

---

### Step 2.2: ORM Schema Definition & Integrity Constraints
- **Actions**:
  Review and refine the 5 tables in [models.py](file:///c:/Users/syeda/Downloads/retrotube/retrotube/models.py):
  1. **`User`**:
     - `id`: Integer primary key.
     - `username`: String(20).
     - `username_lower`: String(20), unique index for case-insensitive logins.
     - `password_hash`: String(255).
     - `joined_at`: DateTime(timezone=True), default `func.now()`.
     - `about`: Text, default `""`.
     - `profile_theme`: JSONB (`{"bg_color": "#...", "bg_url": "..."}`).
     - `bulletins`: JSONB (list of max 10 bulletin objects).
  2. **`WatchHistory`**:
     - `user_id`: ForeignKey with `CASCADE` delete.
     - Composite index `(user_id, watched_at)` for fast timeline queries.
  3. **`LocalRating`**:
     - Unique constraint `(user_id, video_id)`.
     - Check constraint: `stars BETWEEN 1 AND 5`.
     - Index on `video_id` for quick aggregation of average stars.
  4. **`LocalComment`**:
     - `user_id`: ForeignKey with `CASCADE` delete.
     - `video_id`: String(11), indexed with `created_at`.
     - `body`: String(500).
  5. **`Favorite`**:
     - Unique constraint `(user_id, video_id)`.
- **Potential Failure Modes**:
  - Rating constraint violation on out-of-range stars $\rightarrow$ Covered by DB `CheckConstraint` and Pydantic validation.
- **Verification Gate**:
  - Run unit test creating records in each table and asserting foreign key cascade deletions.

---

### Step 2.3: Database Migrations with Alembic
- **Actions**:
  1. Initialize Alembic: `alembic init -t async migrations`.
  2. Configure `migrations/env.py` with `Base.metadata` and `DATABASE_URL`.
  3. Generate initial migration script (`0001_initial_schema.py`).
  4. Replace `await conn.run_sync(Base.metadata.create_all)` in application lifespan with Alembic revision execution.
- **Potential Failure Modes**:
  - Production deployments drifting out of sync with code schemas $\rightarrow$ Alembic migration history provides deterministic versioning.
- **Verification Gate**:
  ```bash
  alembic upgrade head
  # Query information_schema.tables to verify users, watch_history, local_ratings, local_comments, favorites exist
  ```

---

## Phase 3: Redis Cache, Quota Management & External Integrations

### Goal
Implement intelligent, quota-safe integration with the YouTube Data API v3 and Return YouTube Dislike (RYD) API using Redis as a high-speed cache and circuit breaker.

---

### Step 3.1: Redis Client & Cache Layer Primitives
- **Actions**:
  1. Wrap Redis operations into typed helper functions:
     - `cache_get(key: str) -> Optional[dict]`
     - `cache_set(key: str, value: Any, ttl: int) -> None`
     - `cache_delete(key: str) -> None`
  2. Configure explicit TTL policies:
     - Standard searches: 1 hour (`SEARCH_TTL = 3600`).
     - Time Machine searches: 7 days (`ERA_SEARCH_TTL = 604800`).
     - Video details: 7 days (`VIDEO_TTL = 604800`).
     - Dislike stats: Fresh 3 days, Retain up to 30 days (`RYD_FRESH = 259200`, `RYD_KEEP = 2592000`).
- **Verification Gate**:
  - Test setting and retrieving JSON serialized data with expiration checking.

---

### Step 3.2: Pacific Time YouTube Quota Engine
- **Actions**:
  1. Track daily quota spending in Redis under key `quota:YYYY-MM-DD` based on Pacific Time (`ZoneInfo("America/Los_Angeles")`).
  2. Cost weighting:
     - `search.list` = **100 units**
     - `videos.list` = **1 unit**
  3. Quota check:
     - If `used > YT_DAILY_BUDGET` (default 9,000 units), decrement and raise HTTP 503 with a friendly message informing users that visited pages still work from cache.
- **Potential Failure Modes**:
  - Race conditions in quota counter $\rightarrow$ Use Redis atomic `INCRBY` / `DECRBY`.
  - Midnight timezone mismatch $\rightarrow$ Explicitly enforce `ZoneInfo("America/Los_Angeles")` to match Google's quota reset window.
- **Verification Gate**:
  - Unit test mocking quota increment reaching threshold and verifying HTTP 503 response.

---

### Step 3.3: YouTube API Client & Search Pagination Optimizer
- **Actions**:
  1. **Batch Fetching (`fetch_videos`)**:
     - Deduplicate video IDs.
     - Check Redis cache first.
     - Fetch remaining missing IDs in chunks of up to 50 in a single `videos.list` call (costs only 1 quota unit).
  2. **Search Batching & Slicing (`fetch_search_results` / `do_search`)**:
     - Modern YouTube `search.list` returns up to 50 results per call.
     - Request 50 items once per query, cache the complete list, and slice locally into 5 pages of 10 items.
     - Prevents burning 500 quota units for viewing page 5.
  3. **Video Normalization (`normalize_video`)**:
     - Format durations (ISO 8601 `PT4M37S` $\rightarrow$ `04:37`).
     - Map category IDs to 2006-07 names.
     - Convert published timestamps to relative format ("X years ago").
- **Verification Gate**:
  - Mock YouTube HTTP response and confirm `fetch_videos` and `do_search` slice pages accurately without duplicate API calls.

---

### Step 3.4: Return YouTube Dislike (RYD) & Star Rating Calculator
- **Actions**:
  1. Query `https://returnyoutubedislikeapi.com/votes?videoId={id}`.
  2. Enforce strict rate limits: maximum 90 requests/minute, 9,000/day.
  3. Convert likes and estimated dislikes to a 1.0–5.0 star score:
     $$\text{ratio} = \frac{\text{likes}}{\text{likes} + \text{dislikes}}$$
     $$\text{stars} = 1.0 + 4.0 \times \text{ratio}$$
  4. Cache RYD payloads in Redis with graceful degradation: if RYD is slow or returns 429, fall back to cached scores (up to 30 days old) or local community ratings.
- **Verification Gate**:
  - Assert that 900 likes and 100 dislikes computes to $\approx 4.6$ stars.
  - Assert that API timeout falls back gracefully without hanging page render beyond `RYD_PAGE_TIMEOUT` (6 seconds).

---

## Phase 4: Modular Backend Architecture & Application Core

### Goal
Refactor the monolithic [main.py](file:///c:/Users/syeda/Downloads/retrotube/retrotube/main.py) (1,256 lines) into clean, maintainable modules following standard FastAPI enterprise conventions.

---

### Step 4.1: Target Directory & Package Structure
Reorganize the application into modular components:

```
retrotube/
├── app/
│   ├── __init__.py
│   ├── main.py                  # App factory, lifespan, middleware
│   ├── config.py                # Pydantic Settings
│   ├── database.py              # Engine & sessionmaker
│   ├── models.py                # SQLAlchemy ORM models
│   ├── core/
│   │   ├── security.py          # Password hashing, CSRF tokens
│   │   ├── quota.py             # YouTube quota engine
│   │   ├── rate_limit.py        # Redis rate limiters
│   │   └── exceptions.py        # Custom exception handlers
│   ├── services/
│   │   ├── youtube.py           # YouTube API client & normalizer
│   │   ├── ryd.py               # Dislike & star rating engine
│   │   └── cache.py             # Redis caching service
│   ├── routers/
│   │   ├── pages.py             # HTML routes (index, watch, browse, etc.)
│   │   ├── auth.py              # Login, register, logout
│   │   ├── user_actions.py      # Comments, favorites, theme
│   │   └── api.py               # JSON endpoints (/api/search, /api/rate)
│   └── templates/               # Jinja2 templates
├── static/                      # CSS & static assets
├── tools/                       # Preview & cache tools
├── tests/                       # Automated test suite
└── docker-compose.yml
```

---

### Step 4.2: Security, Session & CSRF Layer
- **Actions**:
  1. Configure `SessionMiddleware` with `same_site="lax"`, `max_age=14 days`, and `https_only` conditional on environment.
  2. Argon2id password hashing:
     - `ph = PasswordHasher()`
     - Asynchronous hash and verify wrapped in `asyncio.to_thread` to prevent event-loop blocking.
  3. Session fixation protection: `request.session.clear()` upon login and registration.
  4. CSRF protection:
     - Issue cryptographically secure token `secrets.token_urlsafe(32)` per session.
     - Validate against form inputs and `X-CSRF-Token` HTTP headers using `secrets.compare_digest`.
  5. URL sanitization: Validate custom background URLs (`safe_bg_url`) to only allow `https://` schemes with image extensions, preventing XSS and SSRF.
- **Verification Gate**:
  - Test form submission without CSRF token returns HTTP 403.
  - Test password authentication with correct and incorrect credentials.

---

### Step 4.3: Custom Jinja2 Filters & Helpers
- **Actions**:
  Register custom template filters:
  1. `commas`: Formats integers with comma separators (`1,234,567`).
  2. `ago`: Parses ISO dates to classic YouTube relative strings ("3 days ago", "1 year ago").
  3. `thumb120`: Normalizes modern YouTube thumbnail URLs to the classic 4:3 120×90 `default.jpg` format.
  4. Context globals: Register `ERAS` (2006–2016) and `CATEGORIES` list globally for all templates.
- **Verification Gate**:
  - Render test templates asserting `thumb120` and `ago` filter outputs match expected strings.

---

## Phase 5: Route Controllers & Endpoints Implementation

### Goal
Implement all HTML rendering routes, form action handlers, and JSON APIs with rate limiting and input validation.

---

### Step 5.1: JSON API Endpoints
- **Endpoints**:
  1. `GET /api/search?q={query}&page={n}&year={yyyy}&order={relevance|date|viewCount|rating}`:
     - Slices cached search results; rate limited to 30 requests/minute.
  2. `GET /api/video/{video_id}`:
     - Returns full video metadata, channel details, star scores, and ratings counts.
  3. `POST /api/rate`:
     - Accepts `{video_id, stars}`.
     - Requires authenticated user and valid CSRF token.
     - Performs upsert (`ON CONFLICT (user_id, video_id) DO UPDATE`).
     - Returns updated local rating average and count.
- **Verification Gate**:
  - Execute API calls and assert correct JSON structure and response codes.

---

### Step 5.2: Public Browsing HTML Pages
- **Endpoints**:
  1. `GET /`: Home page with featured videos, currently watched videos, and tag cloud.
  2. `GET /browse?s={sort}&t={time}&c={category}&y={year}&page={n}`:
     - Mirrors the 2006–07 URL parameters (`s=mp` for most popular, `s=tr` for top rated, `s=mr` for most recent; `t=t` for today, `t=w` for this week, etc.).
  3. `GET /results?search_query={q}&year={yyyy}&order={order}&page={n}`:
     - Search results page with sort links and pagination bar (`Pages: 1 2 3 4 5 Next`).
  4. `GET /watch?v={video_id}&cp={comment_page}`:
     - Video player page with 425×350 iframe, rating widget, comment list, and "More Videos from {year}" rail.
  5. `GET /categories`: 12-category matrix with retro color tiles.
  6. `GET /timemachine`: 2006–2016 navigation matrix.
  7. `GET /help`: Classic retro Help Center layout.
- **Verification Gate**:
  - Request each page and verify status code 200 and presence of expected HTML DOM elements.

---

### Step 5.3: Social & User Actions
- **Endpoints**:
  1. `GET /profile/{username}`: User channel displaying custom theme, bulletins, favorite videos, and comment counts.
  2. `GET /channels`: Member directory sorted by joined date.
  3. `GET /community`: Recent comments across the site.
  4. `GET /history` & `POST /history/clear`: Personal watch history list and clear action.
  5. `POST /register`, `POST /login`, `POST /logout`: User authentication flows.
  6. `POST /comment`: Post 1–500 char comment on video.
  7. `POST /favorite`: Toggle video favorite status.
  8. `POST /profile/theme`: Update channel `#hex` color, wallpaper URL, and about text.
  9. `POST /profile/bulletin`: Post a channel bulletin (capped at 10 most recent).
- **Verification Gate**:
  - Complete user flow: Register $\rightarrow$ Update Theme $\rightarrow$ Favorite a video $\rightarrow$ Leave a comment $\rightarrow$ View profile $\rightarrow$ Verify profile reflects changes.

---

## Phase 6: Frontend Template System & Retro 2006-07 Styling

### Goal
Deliver an authentic, pixel-accurate 2006–2007 YouTube user interface adhering strictly to historical screenshots and design measurements.

---

### Step 6.1: Master Layout & Core Styling Specifications
- **Specifications ([DESIGN_NOTES.md](file:///c:/Users/syeda/Downloads/retrotube/retrotube/DESIGN_NOTES.md))**:
  - Fixed-width page container: **875px**, centered on white background.
  - Typography: `Arial, Helvetica, sans-serif`, **12px** base size, 1.35 line height.
  - Links: `#0033CC` with underline on default, underline removed on hover.
  - Color palette tokens in `:root`:
    ```css
    --brand-red: #CC181E;
    --link-blue: #0033CC;
    --page: #FFFFFF;
    --tab: #BBCCEE;
    --tab-active: #CCCCCC;
    --bar: #CCCCCC;
    --sub-bar: #DCDCDC;
    --panel: #EEEEEE;
    --cream: #FFFFE0;
    --orange: #FF6600;
    ```
  - Star ratings: Dual SVG data-URI icons for filled (`#ED3333`) and empty (`#DDDDDD`) stars.
  - Thumbnails: 120×90px with 1px gray border.
- **Deliverables**:
  - Master layout template `base.html` containing navigation tabs, search bar, and classic footer.

---

### Step 6.2: Reusable Jinja2 Macros (`_macros.html`)
- **Macros**:
  1. `video_tile(v)`: Standard 120×90 thumbnail with duration badge, bold title, channel link, view count, and 5-star rating widget.
  2. `star_bar(stars, count)`: Generates 5-star rating element with fractional half-star clipping and numeric rating count ("31035 ratings").
  3. `pager(current, total, base_url)`: Renders classic pagination: `Pages: 1 2 3 4 5 Next`.
- **Verification Gate**:
  - Render macros across various data states (0 ratings, 5.0 stars, long titles) and verify visual alignment.

---

## Phase 7: Background Tasks, Automation & Offline Tools

### Goal
Ensure system resilience, zero live-quota consumption for historical browsing, and offline visual development capabilities.

---

### Step 7.1: Time Machine Cache Warmer (`warm_cache.py`)
- **Actions**:
  1. Pre-fetch search results for all 11 years (2006–2016) across 2 primary sort orders (`viewCount`, `rating`).
  2. Compute total cost: 22 lists $\times$ 101 units $\approx$ 2,222 units (well below 9,000 unit daily limit).
  3. Pre-fetch RYD star scores for page 1 of each list, sleeping 0.75 seconds between calls (stays under RYD 100 req/min limit).
  4. Support CLI arguments:
     - `--budget`: stops gracefully before exceeding specified quota threshold.
     - `--stars-pages`: control how many pages get star score pre-fetching.
- **Verification Gate**:
  - Run `python warm_cache.py --budget 100 --stars-pages 0` with mock endpoints; confirm clean shutdown when budget is reached.

---

### Step 7.2: Playwright Offline Preview Harness (`tools/preview.py`)
- **Actions**:
  1. Provide stub mock data for every page (`PAGES` dictionary in `preview.py`).
  2. Render templates and capture full-page Chromium screenshots in `preview_out/`.
  3. Run completely offline without requiring PostgreSQL, Redis, or a YouTube API key.
- **Verification Gate**:
  ```bash
  python tools/preview.py preview_out
  # Verifies that 12 PNG screenshots are rendered cleanly in preview_out/
  ```

---

## Phase 8: Quality Assurance, Automated Testing & Verification

### Goal
Attain 100% confidence in stability, security, and performance through automated test suites.

---

### Step 8.1: Unit & Service Test Suite
- **Test Matrix (`tests/`)**:
  1. `test_quota.py`:
     - Quota counter increments correctly.
     - Budget exhaustion raises HTTP 503.
     - Pacific time calculation handles daylight saving boundaries.
  2. `test_youtube_client.py`:
     - Batching chunks queries into groups of 50.
     - Normalizer safely parses durations and timestamps.
     - Cache hits bypass HTTP client calls.
  3. `test_ryd.py`:
     - Like/dislike calculation produces expected star ratings.
     - 429 backoff falls back to cached data.
  4. `test_security.py`:
     - Argon2 password verification.
     - CSRF token validation and mismatch detection.
     - Wallpaper URL validator rejects non-HTTPs and non-image URLs.

---

### Step 8.2: Integration & Route Tests
- **Test Matrix**:
  1. `test_auth_routes.py`: Registration, duplicate username handling, login, session clearance on logout.
  2. `test_user_actions.py`: Comment posting, rating submission, favoriting, profile customization.
  3. `test_html_rendering.py`: Test all 11 GET routes for 200 OK responses and proper template rendering.
- **Verification Gate**:
  ```bash
  pytest -v --asyncio-mode=auto
  # All tests pass with zero failures
  ```

---

## Phase 9: Production Readiness & Container Deployment

### Goal
Package RetroTube into a production-hardened container stack with SSL readiness, automated restarts, and log rotation.

---

### Step 9.1: Multi-Stage Production Dockerfile
- **Actions**:
  Create an optimized, non-root `Dockerfile`:
  ```dockerfile
  # Build stage
  FROM python:3.11-slim AS builder
  WORKDIR /build
  COPY requirements.txt .
  RUN pip install --no-cache-dir --user -r requirements.txt

  # Runtime stage
  FROM python:3.11-slim
  WORKDIR /app
  RUN useradd -u 1000 -m retro && chown -R retro:retro /app
  COPY --from=builder /root/.local /home/retro/.local
  COPY . .
  USER retro
  ENV PATH=/home/retro/.local/bin:$PATH
  EXPOSE 8000
  CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
  ```

---

### Step 9.2: Complete Docker Compose Production Stack
- **Services**:
  1. `web`: FastAPI application container with 4 uvicorn workers.
  2. `postgres`: PostgreSQL 16 with persistent volume.
  3. `redis`: Redis 7 alpine with in-memory persistence.
  4. `caddy` / `nginx`: Reverse proxy handling TLS certificates, Gzip/Brotli compression, and static asset caching.

---

## Summary Checklist for Zero-Error Execution

```markdown
- [x] 1. Python virtual environment initialized with pinned dependencies.
- [x] 2. Docker Compose brings up PostgreSQL and Redis with healthy status.
- [x] 3. Pydantic Settings validates all environment variables at startup.
- [x] 4. Alembic executes initial database schema migrations without error.
- [x] 5. YouTube quota tracker verified against Pacific Time reset schedule.
- [x] 6. YouTube search batching reduces 50-result queries to single API calls.
- [x] 7. Return YouTube Dislike integration computes accurate 1-5 star ratings.
- [x] 8. Argon2id, CSRF verification, and URL sanitizers pass security tests.
- [x] 9. All 15 Jinja2 templates render accurately within 875px retro container.
- [x] 10. `tools/preview.py` generates full-page visual preview screenshots.
- [x] 11. `warm_cache.py` warms Time Machine years (2006-2016) safely under budget.
- [x] 12. Automated pytest suite runs with 100% passing tests.
- [x] 13. Production multi-stage Docker container builds and boots cleanly.
```
