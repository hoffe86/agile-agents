# Task 02 — Refactor a Python service to use dependency injection

## User story

As a maintainer of the **invoice-summariser** Python service, I want to refactor the
`InvoiceSummariser` class to take its collaborators via constructor injection instead of
instantiating them inline, so I can unit-test it without hitting OpenAI or the database.

## Context

Today `invoice_summariser.py` looks roughly like this:

```python
class InvoiceSummariser:
    def __init__(self):
        self._oai = OpenAIClient(api_key=os.environ["OPENAI_API_KEY"])
        self._repo = InvoiceRepository(connection_string=os.environ["DB_CONN"])

    def summarise(self, invoice_id: str) -> str:
        invoice = self._repo.get(invoice_id)
        return self._oai.summarise(invoice.text)
```

Tests currently monkeypatch module-level globals — fragile and slow.

## Requested change

1. Refactor `InvoiceSummariser.__init__` to accept `oai: OpenAIClient` and
   `repo: InvoiceRepository` as parameters.
2. Define `OpenAIClientProtocol` and `InvoiceRepositoryProtocol` (PEP 544 `Protocol`) so the
   class depends on interfaces, not concrete implementations.
3. Update the FastAPI startup wiring (in `app.py`) to construct the dependencies once and
   inject them.
4. Update the existing tests to pass fakes/mocks via the constructor — remove all
   monkeypatching of module globals.
5. Keep public method signatures unchanged — this is a pure refactor.
