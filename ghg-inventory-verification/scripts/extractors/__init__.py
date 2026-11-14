# -*- coding: utf-8 -*-
"""Stage 1 voucher extractors (M4)."""
from .base import BaseExtractor, ExtractorResult, RawRecord
from .pdf_invoice import PdfInvoiceExtractor
from .excel_ledger import ExcelLedgerExtractor
from .zip_bundle import ZipBundleExtractor
from .image_voucher import ImageVoucherExtractor

EXTRACTORS = (
    PdfInvoiceExtractor,
    ExcelLedgerExtractor,
    ZipBundleExtractor,
    ImageVoucherExtractor,
)

__all__ = [
    "BaseExtractor", "ExtractorResult", "RawRecord", "EXTRACTORS",
    "PdfInvoiceExtractor", "ExcelLedgerExtractor",
    "ZipBundleExtractor", "ImageVoucherExtractor",
]
