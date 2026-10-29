from __future__ import annotations

import invoice_summariser
from invoice_summariser import InvoiceSummariser


class FakeOpenAIClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def summarise(self, text: str) -> str:
        return f"summary:{text}"


class FakeInvoiceRepository:
    def __init__(self, connection_string: str) -> None:
        self.connection_string = connection_string

    def get(self, invoice_id: str) -> dict[str, str] | None:
        if invoice_id == "missing":
            return None
        return {"invoice_id": invoice_id, "text": "synthetic invoice"}


def test_summarise_reads_invoice_and_calls_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DB_CONN", "sqlite:///:memory:")
    monkeypatch.setattr(invoice_summariser, "OpenAIClient", FakeOpenAIClient)
    monkeypatch.setattr(invoice_summariser, "InvoiceRepository", FakeInvoiceRepository)

    summariser = InvoiceSummariser()

    assert summariser.summarise("inv-1") == "summary:synthetic invoice"


def test_summarise_reports_missing_invoice(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DB_CONN", "sqlite:///:memory:")
    monkeypatch.setattr(invoice_summariser, "OpenAIClient", FakeOpenAIClient)
    monkeypatch.setattr(invoice_summariser, "InvoiceRepository", FakeInvoiceRepository)

    summariser = InvoiceSummariser()

    try:
        summariser.summarise("missing")
    except LookupError as error:
        assert "missing" in str(error)
    else:
        raise AssertionError("missing invoices must raise LookupError")
