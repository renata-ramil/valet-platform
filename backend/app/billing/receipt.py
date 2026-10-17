"""A minimal, dependency-free PDF writer for receipts.

No PDF library is in this project's dependencies, and pulling one in for a
single-page text receipt is more than the job needs. This builds a valid,
single-page PDF by hand: one Helvetica text stream plus a correct cross
reference table, which is all a receipt needs.
"""

FONT_SIZE = 11
LINE_HEIGHT = 16
TOP_MARGIN = 740
LEFT_MARGIN = 50


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(lines: list[str]) -> bytes:
    ops = ["BT", f"/F1 {FONT_SIZE} Tf", f"{LEFT_MARGIN} {TOP_MARGIN} Td"]
    for i, line in enumerate(lines):
        if i == 0:
            ops.append(f"({_escape(line)}) Tj")
        else:
            ops.append(f"0 -{LINE_HEIGHT} Td ({_escape(line)}) Tj")
    ops.append("ET")
    return "\n".join(ops).encode("latin-1", errors="replace")


def build_receipt_pdf(lines: list[str]) -> bytes:
    """Builds a single page PDF with one line of text per entry in `lines`."""
    stream_bytes = _content_stream(lines)

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(
        b"<< /Length "
        + str(len(stream_bytes)).encode("ascii")
        + b" >>\nstream\n"
        + stream_bytes
        + b"\nendstream"
    )

    out = bytearray()
    out += b"%PDF-1.4\n"
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode("ascii")
        out += body
        out += b"\nendobj\n"

    xref_offset = len(out)
    count = len(objects) + 1
    out += f"xref\n0 {count}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode(
        "ascii"
    )
    return bytes(out)


def invoice_receipt_lines(
    building_name: str,
    resident_name: str,
    invoice_id: str,
    period_start: str,
    period_end: str,
    status: str,
    total_cents: int,
    paid_cents: int,
    lines: list[tuple[str, int]],
) -> list[str]:
    """Formats the plain-text lines of an invoice receipt."""
    out = [
        f"{building_name}: valet billing receipt",
        f"Invoice {invoice_id}",
        f"Resident: {resident_name}",
        f"Billing period: {period_start} to {period_end}",
        f"Status: {status}",
        "",
        "Lines:",
    ]
    for description, amount_cents in lines:
        out.append(f"  {description}: ${amount_cents / 100:.2f}")
    out.append("")
    out.append(f"Total: ${total_cents / 100:.2f}")
    out.append(f"Paid: ${paid_cents / 100:.2f}")
    return out
