# Acceptance criteria — task-02

1. **Constructor injection** — `InvoiceSummariser.__init__` takes `oai` and `repo`
   parameters; no `os.environ` reads inside the class.
2. **Protocols defined** — `OpenAIClientProtocol` and `InvoiceRepositoryProtocol` are
   `typing.Protocol` subclasses with the methods used by `InvoiceSummariser`.
3. **Tests pass without monkeypatching** — `pytest -q` is green, and `git grep monkeypatch`
   in the test file returns zero matches.
4. **Type-checks** — `mypy --strict invoice_summariser.py app.py` is clean.
5. **Public API unchanged** — `InvoiceSummariser.summarise(invoice_id)` keeps the same
   signature and return type.
