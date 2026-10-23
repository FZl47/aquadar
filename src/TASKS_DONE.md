

## 55. Review follow-up fixes for Experiments / ai_assistant (2026-10-22)

- **`apps/ai_assistant/services.py`** — `run_experiment_analysis` catches any exception (logged with traceback) so an analysis can never stay stuck on "analyzing"; regression test added.
- **`apps/public/models.py`** — experiment uploads now stored under random `uuid4` filenames (`experiments/<soil|leaf|water>/<32hex>.<ext>`) so media URLs are not guessable. No schema change (`makemigrations --check` clean).
- **`apps/public/models.py`** — `Experiment.save()` now deletes replaced files only after the new row saved successfully (a failed save no longer loses the old file).
- **`apps/public/signals.py`** — `post_delete` receiver `experiment_delete_files` removes stored files; replaces the `Experiment.delete()` override so bulk/admin/queryset/cascade deletes no longer leave orphans.
- **`apps/__init__.py`** — added so `python manage.py test apps` discovers tests (previously failed on the namespace package).
- **Tests** — random filename, bulk-delete cleanup, replace-file cleanup, unexpected-exception handling.
- **Not changed** — `apps/notification/tests.py` is an empty stub from before; left as is.

**Verification:** `python manage.py test apps` → 36 tests OK; `makemigrations --check` → no changes.
