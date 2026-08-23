# Testing

    uv run pytest                    # everything
    uv run pytest -k PressReview     # one area
    uv run pytest --create-db        # rebuild the test database

The suite is green. Keep it that way — it went a long time being unrunnable, and
roughly 50 tests silently never executed.

## Why it was broken, so it is not broken again

- `load_dotenv` lived only in `manage.py`, which pytest never invokes, so
  `DB_NAME` was unset and no test database could even be named. Settings now load
  `.env` themselves, without overriding real environment variables.
- Migration `0057` had an empty `operations` list, so a column added in `0006`
  was never dropped and `0058` failed on any database built from scratch.
- `conftest.py` seeds the language lookups after the test database is created.
  `CustomUser.preferred_language` defaults to id 94, which is hand-seeded
  reference data, so creating any user raised a ForeignKeyViolation.
- `conftest.py` also advances the lookup sequences past those explicit ids.
  Explicit ids do not move a Postgres sequence and sequences are not rolled back,
  so later inserts eventually collided — only ever in full-suite runs.
- `conftest.py` forces filesystem storage into a temp directory. Loading `.env`
  also switches on `USE_S3_MEDIA`, and tests saving an ImageField were uploading
  to the production media bucket.

## Guards worth knowing

`WebImportBoundaryTests` asserts that importing `reports.views`, `reports.urls`
and `reports.services` pulls in none of pandas, pyarrow, matplotlib, wordcloud,
sqlalchemy, anthropic, openai or feedparser. Each check runs in a **subprocess**,
because by the time the suite runs another test may already have imported pandas
and would mask the regression. Failures name the modules and their cost in MB.

## Writing tests here

- `SimpleTestCase` for pure logic — it runs even if the database is unavailable.
- The app redirects unprefixed URLs to `/en/...` (`LanguagePrefixMiddleware`), so
  `client.get(...)` needs `follow=True`. **POSTs cannot use it**: a 302 turns the
  POST into a GET and the form data is lost. Post to the prefixed URL instead.
- Migration `0184` seeds the Region and Topic lookup categories, so tests must
  `get_or_create` those rather than `create` by primary key.
- Constructing a processor with `__new__` skips `__init__`; stub the attributes
  the method under test reads.

## Not covered

No CI. The suite runs only when you run it. A GitHub Actions workflow running
the non-DB tests on push would catch most regressions before a deploy.
