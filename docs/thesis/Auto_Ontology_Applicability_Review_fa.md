# بررسی قابلیت اعمال NVIDIA Auto Ontology در پروژهٔ NL2SQL

**هدف:** آیا این چارچوب می‌تواند «بررسی و رفع Semantic Error» (Future Work، اسلاید ۱۲ گزارش ۶ ماهه) را در پروژهٔ شما پوشش دهد؟

| | |
|---|---|
| تاریخ بررسی | 2026-11-19 |
| مخزن بررسی‌شده | `NVIDIA/auto-ontology` (HEAD `43fa2d3`، `pyproject.toml` نسخهٔ 1.3.0، مجوز Apache-2.0) و مخزن همراه `NVIDIA/auto-ontology-eval` |
| کد پروژهٔ شما | commit `9b09fd0` روی `main` |
| روش | خواندن مستقیم کد و مستندات (static) + تطبیق `execution-log.md` خودتان با gold رسمی Spider dev |
| آنچه اجرا نشد | خود Auto Ontology را اجرا نکردم (نیازمند Docker، Postgres/pgvector و کلید API است). همهٔ ادعاهای مربوط به آن از روی کد و مستندات است. |

---

## ۱. نتیجه در یک نگاه

1. **به‌عنوان چارچوب قابل‌جایگزینی یا افزودن به پروژهٔ شما: خیر.** یک پلتفرم سازمانی کامل است (Next.js + دو سرویس FastAPI + Postgres 17/pgvector + MCP)، با حلقهٔ ReAct مستقل که خودش retrieval و validation را کنترل می‌کند. وارد کردنش، همان زیرساختی را برمی‌گرداند که تازه از پروژه حذف کردید و فرضیهٔ «یک عامل در هر ردیف» در ablation شما (E0–E7) را نقض می‌کند.
2. **Critic/Judge برای Semantic Error ندارد.** مستندات خودش صریحاً می‌گوید: «There's no separate intent classifier, SQL judge, or repair model» (`docs/architecture.md`، بخش *Tools*). رویکردش **پیشگیری از طریق grounding** (توضیح ستون‌ها، مقادیر ذخیره‌شده، مسیر join تأییدشده با داده، تعریف metric) به‌علاوهٔ چک‌های قطعی روی نام‌هاست، نه تشخیص خطای معنایی پس از تولید SQL.
3. **به‌عنوان منبع ایده: بله، چهار الگوی مشخص و ارزان** (بخش ۵) که برای خطاهای واقعی لاگ خودتان کاربرد دارند و هیچ‌کدام نیازمند LLM دوم نیستند.
4. **یافتهٔ مهم‌تر از خود NVIDIA از لاگ شما درآمد:** در بخش مرور‌شدهٔ لاگ، ~۹۵٪ شکست‌ها اجرا شده‌اند و فقط نتیجهٔ اشتباه دارند (حلقهٔ بازخورد فعلی نابیناست)، و ~۳۲٪ «شکست‌ها» مربوط به scorer شما هستند، نه مدل (بخش ۴ و ۸). این دو باید قبل از هر کار Semantic Error روشن شوند.

---

## ۲. Auto Ontology واقعاً چیست

(ارجاع‌ها به مخزن NVIDIA)

| موضوع | آنچه در کد/مستند دیده شد | منبع |
|---|---|---|
| ماهیت | پلتفرم «ontology خودکار» برای داده‌های سازمانی: concept (term + synonyms)، mapping به ستون، relationship (join)، metric (SQL attribute)، lineage، certification | `README.md` جدول «How it works» |
| معماری | Next.js (۳۰۰۰) + FastAPI backend (۳۰۰۱) + سرویس ingestion (۳۰۰۲) + MCP server (۳۰۰۳) + Postgres 17 + pgvector | `README.md`، `docs/architecture.md` |
| نیازمندی | Python ≥3.12,<3.14؛ Docker Compose/Helm؛ مدل با structured output؛ پیش‌فرض Nemotron روی build.nvidia.com | `pyproject.toml`، `README.md` بخش Models |
| منابع داده | ۱۰ connector از جمله SQLite (`auto_ontology/connectors/sqlite.py`) | `README.md` |
| فاز Generate (offline) | ingest کاتالوگ؛ per-table: نمونه‌برداری حداکثر ۱٬۰۰۰ ردیف، distinct values ستون‌های کم‌کاردینالیتی، تشخیص ستون یکتا (`distinct_ratio ≥ 95٪`)، FK-candidate و junction-table با LLM، توضیح ستون (یک جمله از نام + نوع + نمونه‌مقدار)، نام‌گذاری term؛ cross-table: FK معنایی که **فقط با تأیید join روی داده** ذخیره می‌شود | `docs/architecture.md` ردیف‌های per-table و cross-table؛ `auto_ontology/semantic/deterministic.py` (`_DESCRIPTION_SYSTEM`) |
| فاز Answer (online) | حلقهٔ ReAct با ابزارهای `retrieve` / `run_sql` / `submit`؛ سقف ۲۴ tool-call و ۱۰ بار `run_sql` برای هر سؤال | `docs/architecture.md` بخش Limits |
| Retrieval | جست‌وجوی معنایی (pgvector) + جست‌وجوی substring روی نام‌ها. **BM25، RRF یا reranker هنگام پاسخ‌دهی نیست**؛ `RERANK` فقط برای انتخاب term مالک جدول‌های واسط در زمان compile استفاده می‌شود | `react/retrieve.py` docstring؛ `docs/architecture.md:177` |
| ادعای عملکرد | فقط دو badge در README (رتبهٔ ۱ BEAVER، رتبهٔ ۲ BIRD-Interact). **آن‌ها را راستی‌آزمایی نکردم.** در دو مخزن هیچ عدد Spider 1.0 منتشر نشده است؛ مخزن eval روی BIRD، BEAVER، FDABench-Lite، WideWorldImporters و BIRD-Interact است | `README.md`، `auto-ontology-eval/README.md` |

---

## ۳. برای Semantic Error چه دارد و چه ندارد

| مکانیزم | چه کاری می‌کند | نوع | به‌درد پروژهٔ شما؟ |
|---|---|---|---|
| بررسی نام جدول/ستون با پیشنهاد «did you mean» | `find_unknown_names` با sqlglot؛ نام‌های ناموجود را همراه نزدیک‌ترین نام واقعی (difflib) برمی‌گرداند و **اجرا نمی‌کند** | قطعی | **بله** (بخش ۵، ایدهٔ ۳) |
| «جدولی که retrieve نشان نداده» مجاز نیست | `tables_not_shown` | قطعی | کم (در Schema-RAG شما retrieval یک‌بار و ثابت است) |
| ابزار `run_sql` برای دیدن مقادیر ذخیره‌شده | مدل خودش `SELECT DISTINCT …` می‌زند؛ نتیجهٔ ۰ ردیف با متن «literal ها را با مقادیر ذخیره‌شده چک کن» برمی‌گردد | رفتار مدل + hint متنی | ایده بله؛ مکانیزم بدون ReAct هم ممکن است |
| `value_anchors` («VERIFIED DATABASE VALUES») | بلوک prompt: عبارت سؤال ← (جدول، ستون، املای ذخیره‌شده)، و فهرست عباراتی که «هیچ‌جا ذخیره نشده‌اند». **در مخزن اصلی ساخته نمی‌شود؛ فقط از `payload` گرفته می‌شود** (`text_to_sql/main.py:126`، `state.py:48-51`). سازندهٔ آن اسکریپت `scripts/extra_prompts/value_index.py` در مخزن eval و فقط برای BIRD Dev است | prompt + ایندکس بیرونی | **بله، مهم‌ترین ایده** (بخش ۵، ایدهٔ ۱) |
| `check_answerable` | استخراج entity با LLM، جست‌وجو در pgvector، نمرهٔ پوشش — **پیش از تولید SQL و دربارهٔ «پاسخ‌پذیر بودن»** است نه درستی SQL | LLM + قطعی | در Spider/BIRD کاربرد کم است (همهٔ سؤال‌ها پاسخ‌پذیرند) |
| `skills/nvidia-ontology-query/references/query-validation.md` | چک‌لیست **دستی** برای agent خارجی: grain، fan-out join، جایگزینی ratio با quantity، truncation، … | سند، نه کد | فقط به‌عنوان rubric برای طراحی Critic آینده |
| Critic / Judge / Repair LLM | **ندارد** | — | — |
| «Learn: certified corrections folded back» (README) | طبق `docs/architecture.md:190-191`، certify فقط برچسب UI است و «doesn't change how the agent retrieves»؛ فقط ویرایش‌های دستی دوباره embed می‌شوند | عمدتاً دستی | حلقهٔ یادگیری خودکار از خطا **وجود ندارد** |
| ماژول‌های literal-check / empty-result-repair | docstring مخزن eval به `db_probe/literal_check.py` و `empty_result_value_repair` اشاره می‌کند، اما در checkout فعلی مخزن اصلی **هیچ‌کدام نیستند** (grep بدون نتیجه؛ فقط `db_probe/executor.py` و `config.py` مانده) | حذف‌شده | — |

---

## ۴. خطاهای واقعی خودِ پروژهٔ شما (از `execution-log.md`)

> **توجه:** اعداد این بخش از لاگ ناقص ترمینال (۴۰۲ نمونه) بود و با اجرای کامل ۱۰۳۴ نمونه جایگزین شده است؛ برای گزارش از `Error_Analysis_Full_Run_fa.md` استفاده کنید.

**روش.** ۴۰۲ نمونهٔ ثبت‌شده در لاگ (شمارهٔ ۱۹۹ تا ۶۰۰ از ۶۰۰ سؤال اول `dev.json`) را با gold رسمی (`taoyds/spider`، `evaluation_examples/examples/dev.json`) تطبیق دادم؛ همهٔ ۴۰۲ ردیف از نظر `db_id` و متن سؤال کاملاً هم‌خوان بودند. ۷۴ نمونه‌ای که قبول نشدند (۷۲ `FAIL` + ۲ `EM`-بدون-EX) را با مقایسهٔ متن gold و pred دسته‌بندی کردم.

**هشدارهای روش‌شناختی (لطفاً در گزارش حفظ شوند):**
- دسته‌بندی **دستی و بر پایهٔ متن SQL** است؛ نتیجه‌ها را روی DB دوباره اجرا نکردم (دیتابیس‌های Spider در دسترس این محیط نبود).
- لاگ ترمینال است و **خلاصهٔ نهایی ندارد**؛ ۱۹۸ نمونهٔ اول (concert_singer، pets_1، car_1، ابتدای flight_2) در آن نیست. بنابراین EX بخش (81.6٪) با EX کل run یکی نیست.
- `--limit N` «N نمونهٔ اول فایل» را برمی‌دارد (`cli_spider_eval.py:20`) نه نمونهٔ تصادفی؛ ۶۰۰ سؤال اول فقط ~۱۲ از ۲۰ پایگاه‌داده‌ی dev را پوشش می‌دهد.

### جدول دسته‌بندی (۴۰۲ نمونه)

| دسته | تعداد | سهم از ۴۰۲ | توضیح |
|---|---:|---:|---|
| قبول (EX) | 328 | 81.6٪ | |
| **H — ضعف scorer شما** | **24** | **6.0٪** | ۲۲ مورد فقط ترتیب ستون‌ها فرق دارد؛ ۲ مورد خطای UTF-8 روی خود gold |
| **G — gold/ابهام** | **24** | **6.0٪** | ۴ مورد literal با حروف کوچک در gold؛ ۲۰ مورد gold یا سؤال مبهم است (مثلاً gold ستون خواسته‌شده را حذف کرده) |
| **M — خطای مدل‌محور** | **26** | **6.5٪** | جزئیات پایین |

**ریز M (۲۶ مورد):**

| نوع | تعداد | نمونه‌ها (شمارهٔ ردیف در dev.json) | مثال |
|---|---:|---|---|
| value mismatch (املای ذخیره‌شده با سؤال فرق دارد) | 11 | 215, 363, 404, 459, 486, 487, 532, 537, 550, 551, 577 | `hand = 'left'` (ذخیره‌شده `'L'`)؛ `'math'` (ذخیره‌شده `'Math'`)؛ `'Bachelors'` (ذخیره‌شده `'Bachelor'`)؛ `'North Carolina'` (ذخیره‌شده `'NorthCarolina'`) |
| ستون اشتباه یا hallucinate‌شده | 5 | 355, 488, 541, 576, 585 | `degree_summary_description` به‌جای `degree_summary_name`؛ `address_name` که اصلاً وجود ندارد |
| مسیر join / جمعیت / grain / شکل | 5 | 336, 428, 500, 531, 536 | `battle.id = death.caused_by_ship_id` (join روی FK اشتباه)؛ شمردن visitorها از جدول `visit` به‌جای `visitor` |
| منطق مجموعه‌ای / نقیض | 4 | 380, 381, 505, 506 | «هم Brazil و هم Ireland» با `AND` روی یک ستون به‌جای `INTERSECT` |
| دانش دامنه | 1 | 440 | «highest rank» یعنی کوچک‌ترین عدد (`MIN`) |

### سه یافتهٔ کلیدی از این داده

1. **حلقهٔ بازخورد فعلی نابیناست.** از ۷۴ نمونهٔ ردشده، ۷۰ تا بدون خطا اجرا شده‌اند (فقط نتیجهٔ اشتباه)؛ فقط ۲ مورد (576، 585) پس از ۴ تلاش هم خطای اجرا داشتند. حلقه فقط در ۷ از ۴۰۲ نمونه فعال شد و فقط ۲ تا از آن‌ها درست شد. این با یادداشت `Technical-dept.md` شما هم هم‌جهت است: روی ۵۵۰ نمونه single-pass برابر 72.73٪ و feedback برابر 72.55٪ بود. توجه: آن اعداد **پیش از** اصلاح حلقه در commit `4491a33` است و خلاصهٔ نهایی run جدید (با حلقهٔ اصلاح‌شده) در repo نیست؛ پس اثر فعلی حلقه را هنوز نمی‌توان از روی عدد کل گفت.
2. **سقف سودِ کل برنامهٔ Semantic Error در این بخش حدود ۶.۵ امتیاز است** (۲۶/۴۰۲)، اگر همهٔ خطاهای مدل‌محور کاملاً اصلاح شوند. اصلاح scorer به‌تنهایی حدود ۶.۰ امتیاز است (با فرض اینکه آن ردیف‌ها پس از اصلاح واقعاً منطبق شوند، که بدون اجرای مجدد تأیید‌نشده است).
3. **۱۱ از ۲۶ خطای مدل‌محور (۴۲٪) نتیجهٔ ۰ ردیف دارند** (404, 459, 537, 550, 551, 577, 363, 532, 380, 381, 506)، و ۸ از ۱۱ value-mismatch جزو آن‌هاست. یعنی یک سیگنال بدون‌هزینه و بدون gold برای بازخورد وجود دارد. محدودیت: پاسخ‌های «خالی»ِ درست هم در Spider هست؛ نرخ false-positive را باید روی نمونه‌های قبول‌شده سنجید (نیازمند اجرای مجدد).

---

## ۵. نگاشت: خطای لاگ شما ← ایدهٔ قابل اقتباس ← پیاده‌سازی در repo شما

همهٔ ایده‌های زیر قطعی‌اند (بدون LLM دوم)، لذا هر کدام می‌تواند یک ردیف مستقل ablation (E8، E9، …) باشد و کنترل‌شدگی طرح E0–E7 حفظ شود.

| # | ایده | الهام از | خطای هدف | چه چیزی در repo شما تغییر می‌کند |
|---|---|---|---|---|
| 1 | **Value grounding:** ایندکس معکوس مقدار ← (جدول، ستون)، روی ستون‌های متنی کم‌کاردینالیتی SQLite. اگر عبارت سؤال در هیچ ستونی نیست یا املایش فرق دارد، «مقدار ذخیره‌شده» (و فهرست «ذخیره‌نشده») را در prompt و در بازخورد بیاور | `value_anchors_section` (`react/prompts.py:246-343`)، `scripts/extra_prompts/value_index.py` | value mismatch (11) و بخشی از «ستون اشتباه» (id در برابر نام: 550، 551، 577) | `app/schema_manager.py` (استخراج distinct values) + `NL2SQLChain.build_user_prompt`؛ Spider کوچک است، ایندکس ارزان است |
| 2 | **محرک نتیجهٔ ۰ ردیف** در `SQLFeedbackLoop`، با متن «literal ها را با مقادیر ذخیره‌شدهٔ ستون X مقایسه کن» | `render_rows` (`react/run_sql.py:392-408`) | ۱۱ مورد با ۰ ردیف | `_check_sql` در `spider_runner.py` (که همین‌الان executor دارد)؛ **باید با false-positive سنجیده شود** |
| 3 | **did-you-mean + فهرست ستون‌های واقعی جدول** در پیام بازخورد خطای اجرا | `find_unknown_names` و `_suggest` (`react/run_sql.py:162-218`) | 576 و 585 (۴ بار تکرار همان ستون ناموجود) | `app/sql_validator.py` (`extract_error_feedback`) |
| 4 | **Lint معنایی قطعی:** (الف) JOIN روی ستون‌هایی که FK اعلام‌شده نیستند؛ (ب) مقایسهٔ ستون id/عددی با literal متنی؛ (ج) literal مقایسه‌ای که در distinct values ستون نیست | الهام از FK تأییدشده با داده (`semantic_fk.py`) و ایدهٔ ۱؛ **Auto Ontology این lintها را به‌صورت کد ندارد** | 500 (join روی FK اشتباه)، 550/551/577 (id در برابر رشته) | `app/sql_validator.py` — توسعهٔ `validate_schema_elements` |
| — | توضیح ستون با **نمونه‌مقدار به‌عنوان evidence** | `_DESCRIPTION_SYSTEM` (`semantic/deterministic.py`) | ستون اشتباه با نام مشابه (355، 541) و ستون‌های کدی مثل `hand ∈ {L,R,U}` | `enrich_schema.py` فعلی فقط کلیدواژهٔ فارسی از نام/نوع می‌سازد، نمونه‌مقدار نمی‌دهد و هیچ‌جا فراخوانی نمی‌شود (هنوز در harness Spider سیم‌کشی نشده) |

**Critic LLM** (۴ مورد منطق مجموعه‌ای + ۵ مورد grain/شکل + ۱ دانش دامنه ≈ ۱۰ مورد، یعنی ~۲.۵٪ بخش) را برای مرحلهٔ بعد بگذارید: سقف سودش در این بخش کوچک‌تر از ایدهٔ ۱ است و ریسک «تغییر پاسخ درست به غلط» دارد؛ rubric را می‌توان از `query-validation.md` گرفت، ولی آن سند برای سؤال‌های تحلیلی سازمانی نوشته شده نه Spider.

---

## ۶. چرا نه به‌صورت کامل (جدول عدم‌تطابق)

| محور | پروژهٔ شما | Auto Ontology | پیامد |
|---|---|---|---|
| زیرساخت | Python + ChromaDB + Ollama، یک CLI | Docker، Postgres 17/pgvector، ۲ FastAPI، Next.js، MCP | همان پیچیدگی‌ای که تازه حذف کردید برمی‌گردد |
| کنترل پژوهشی | یک عامل در هر ردیف ablation (K ثابت = 15) | agent خودش retrieval را تکرار می‌کند (تا ۲۴ tool-call) | E0–E7 دیگر قابل جداسازی نیست؛ هزینهٔ LLM چندبرابر |
| Retrieval | dense + (برنامه‌ریزی‌شده) BM25 + RRF + reranker | dense + substring؛ reranker فقط در compile | RQ3 شما را پوشش نمی‌دهد |
| LLM | Gemma 4 12B محلی روی Ollama | نیاز به tool-calling و structured output؛ پیش‌فرض Nemotron‑30B؛ نگه‌دارندگان مخزن eval با `claude-opus-5-5` آزمایش می‌کنند | روی Gemma 4 12B ثابت‌نشده |
| Semantic Error | می‌خواهید تشخیص دهید | ندارد (no SQL judge) | نیاز اصلی شما را برآورده نمی‌کند |
| رژیم داده | Spider: DBهای کوچک، تمیز، FK اعلام‌شده | README خودش: «With one well-modeled source and a fixed set of questions, direct SQL may be enough» | سود ontology روی Spider کم است |
| شواهد | — | عدد Spider 1.0 ندارد | قابل ارجاع در تز نیست |

**جایی که به‌دردتان می‌خورد:** آیتم «Validation on BIRD» در همان اسلاید ۱۲. مخزن `auto-ontology-eval` یک harness آمادهٔ BIRD (Dev 1٬534 و Mini-Dev 500) با مقایسهٔ control در برابر treatment روی یک مدل و scoring قطعی بدون LLM-judge دارد (Apache-2.0). برای اسکریپت‌های seed و روش ارزیابی BIRD می‌توانید از آن الگو بگیرید. همان README هشدار می‌دهد نتیجهٔ ساخته‌شده با `value_anchors`/exemplars را جدا گزارش کنید.

---

## ۷. پیشنهاد اجرایی (به ترتیب سود/هزینه)

0. **اصلاح scorer (پیش‌نیاز).** در `SpiderSQLiteExecutor.compare` (`app/spider_eval/spider_sqlite_executor.py:111-152`) تطبیق تا حد جایگشت ستون‌ها (مشابه `result_eq` در `taoyds/test-suite-sql-eval/exec_eval.py`) و `conn.text_factory` با decode بدون خطا (مشکل `wta_1`). همچنین خطای decode نباید یک retry LLM بسوزاند (در ۴۵۶ و ۴۵۷ هر کدام ۳ بازتولید اضافه روی یک خطای دادهٔ SQLite انجام شد). **تا الان پیش‌بینی‌های per-sample ذخیره نمی‌شود** (grep روی `json.dump`/`jsonl`/`open(…,"w")` در CLI و `spider_eval/` نتیجه‌ای نداد)، لذا بازامتیازدهی نیاز به ذخیرهٔ JSONL دارد.
1. ایده‌های ۲ و ۳ (کم‌هزینه‌ترین)، سپس ایدهٔ ۱ (بیشترین سود).
2. ایدهٔ ۴ و سپس توضیح ستون با نمونه‌مقدار (`enrich_schema.py` را وارد harness کنید).
3. Critic LLM، فقط پس از اینکه سقف باقی‌مانده با scorer اصلاح‌شده اندازه‌گیری شد.

**در متن تز/اسلاید:** «Auto Ontology (NVIDIA, 2026) یک پلتفرم ontology سازمانی است؛ ما اصل grounding بر مقادیر ذخیره‌شده و چک‌های قطعی را اقتباس کردیم، نه پلتفرم را. این چارچوب Critic ندارد؛ لذا Semantic Error همچنان Future Work این پژوهش است.»

---

## ۸. موارد جانبی که باید بدانید

1. **ناسازگاری اسلایدها با repo.** اسلاید ۷ برای E2 (فقط dense، K=15) عدد 55.2٪ و برای E7 عدد 76.5٪ می‌دهد. اما `Technical-dept.md` در repo برای همان پیکربندی (single-pass، dense، K پیش‌فرض = 15، بدون enrichment/BM25/RRF/reranker) روی ۵۵۰ نمونه **72.73٪** ثبت کرده است. کد Python برای BM25/RRF/reranker/enrichment-در-Spider در `main` وجود ندارد (grep: فقط سند معماری `.md` این‌ها را ذکر می‌کند و `enrich_schema.py` هیچ فراخوانی‌ای ندارد). اگر E3–E7 از کدی خارج از repo آمده‌اند، آن را commit کنید؛ اگر تخمینی بوده‌اند، در اسلاید به‌عنوان «تخمینی» برچسب بزنید. این را به‌خاطر اینکه اسلاید ۱۲ خودش می‌گوید Future Work «اندازه‌گیری‌نشده» است، فقط یادآوری می‌کنم.
2. **اسلاید ۷/۸:** «1,034 Q / 20 DBs» در برابر «۶۰۰ query» با `--limit` = ۶۰۰ نمونهٔ اول (≈۱۲ DB).
3. **EM:** معیار EM شما (18.73٪) یک تطبیق متنی نرمال‌شده است، با EM رسمی Spider قابل مقایسه نیست.

---

## ۹. محدودیت‌های این بررسی

- Auto Ontology اجرا نشد؛ از ~۱۵ فایل کلیدی (از ~۴۸۰ فایل Python) مستقیم خواندم و بقیه را فقط با grep/فهرست دیدم.
- ادعاهای leaderboard در README راستی‌آزمایی نشد.
- دسته‌بندی ۷۴ شکست دستی است و روی DB دوباره اجرا نشد؛ شمارش‌ها «تقریبی» تلقی شوند.
- لاگ فقط ۴۰۲ نمونه (انتهای یک run ۶۰۰تایی در حالت feedback) را شامل می‌شود و نمونهٔ تصادفی نیست.

---

## پیوست: شناسهٔ نمونه‌ها (شمارهٔ ردیف ۱-مبنا در `dev.json`)

- **H، ترتیب ستون:** 264, 265, 268, 269, 288, 289, 418, 453, 460, 461, 468, 471, 472, 473, 474, 475, 480, 481, 482, 483, 490, 491
- **H، UTF-8 روی gold:** 456, 457
- **G، literal حروف‌کوچک در gold:** 388, 389, 555, 584
- **G، gold/ابهام:** 232, 233, 313, 346, 347, 362, 449, 494, 501, 527, 534, 535, 542, 543, 548, 549, 562, 579, 580, 581
- **M:** در جدول بخش ۴
