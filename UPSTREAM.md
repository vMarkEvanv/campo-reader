# Extraction provenance

Extracted from the current local Orange Pi BLOG Campo Reader module on 2026-10-15.
The Orange Pi application is retained and not modified by this project.

Copied business modules: campo.py, campo_courses.py, campo_documents.py,
campo_workspace.py, campo_source/core.py, campo_source/scripts.py.
The only engine portability change is replacing the hardcoded Linux Chromium
path with the bundled Playwright browser launcher.

The HTML/JS/CSS are retained with the same workspace, calendar, grade,
course-management, progress, and document features. Device-console/navigation
links are replaced with the local data-folder action. The device console error
type is retained as a standalone exception class; no SSH, Codex, or device-control
modules are included.

No live database, credential, token, certificate, browser storage, PDF, personal
classification or account record is copied into this repository or package.
