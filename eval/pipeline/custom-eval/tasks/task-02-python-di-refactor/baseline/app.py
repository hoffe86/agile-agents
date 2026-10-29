from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException

from invoice_summariser import InvoiceSummariser


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.summariser = InvoiceSummariser()
    yield


app = FastAPI(title="Invoice Summariser", lifespan=lifespan)


@app.get("/invoices/{invoice_id}/summary")
def summarise_invoice(invoice_id: str) -> dict[str, str]:
    try:
        summary = app.state.summariser.summarise(invoice_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Invoice not found") from exc
    return {"summary": summary}
