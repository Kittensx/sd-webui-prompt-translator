# Project Layout

```text
extension_root/
├── install.py
├── requirements.txt
├── docs/
├── models/              # top-level, excluded from release zips when needed
├── dictionaries/        # top-level user-managed dictionaries/glossaries
├── test_outputs/        # top-level generated reports
├── tests/               # top-level test and diagnostic scripts
└── language/            # importable language backend package
    ├── cache/
    ├── config/
    ├── providers/
    ├── paths.py
    └── constants.py
```

`language/paths.py` is the source of truth for runtime directories. Avoid raw `Path("models")`, `Path("dictionaries")`, or `Path("test_outputs")` references in backend code.
