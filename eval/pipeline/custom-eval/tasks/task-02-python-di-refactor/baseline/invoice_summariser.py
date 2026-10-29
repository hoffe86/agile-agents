from __future__ import annotations

import json
import os
import sqlite3
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OpenAIClient:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def summarise(self, text: str) -> str:
        request = Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps({
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": f"Summarise this invoice:\n{text}"}],
            }).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload: Any = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError("OpenAI invoice summary request failed") from exc
        return str(payload["choices"][0]["message"]["content"])


class InvoiceRepository:
    def __init__(self, connection_string: str) -> None:
        self._database_path = connection_string.removeprefix("sqlite:///")

    def get(self, invoice_id: str) -> dict[str, str] | None:
        with sqlite3.connect(self._database_path) as connection:
            row = connection.execute(
                "SELECT invoice_id, text FROM invoices WHERE invoice_id = ?",
                (invoice_id,),
            ).fetchone()
        if row is None:
            return None
        return {"invoice_id": str(row[0]), "text": str(row[1])}


class InvoiceSummariser:
    def __init__(self) -> None:
        self._oai = OpenAIClient(api_key=os.environ["OPENAI_API_KEY"])
        self._repo = InvoiceRepository(connection_string=os.environ["DB_CONN"])

    def summarise(self, invoice_id: str) -> str:
        invoice = self._repo.get(invoice_id)
        if invoice is None:
            raise LookupError(f"Invoice {invoice_id!r} was not found")
        return self._oai.summarise(invoice["text"])
