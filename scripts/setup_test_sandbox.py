import struct
import zlib
from pathlib import Path

import pymupdf


def make_png(width=100, height=100):
    raw_data = b"".join(b"\x00" + b"\x10\xb9\x81" * width for _ in range(height))
    compressed = zlib.compress(raw_data)
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")

def create_sandbox():
    sandbox = Path("test_workspace/messy_inbox")
    sandbox.mkdir(parents=True, exist_ok=True)

    # 1. Text receipt
    (sandbox / "uber_receipt_october.txt").write_text(
        "Uber Technologies Inc.\nTrip Date: October 18, 2026\nDriver: Carlos\nFrom: SFO Airport\nTo: Downtown Hotel\nTotal: $42.50\nPayment Method: Visa ending in 4021",
        encoding="utf-8"
    )

    # 2. Markdown meeting notes
    (sandbox / "q4_strategy_notes.md").write_text(
        "# Q4 Engineering Strategy\nDate: 2026-10-15\n\nGoals:\n1. Deliver local-first AI file tidier (slothd)\n2. Air-gapped privacy with Gemma 3\n3. Tiger Data pgvector semantic search\n\nAttendees: Dhruv, Engineering Team",
        encoding="utf-8"
    )

    # 3. Python script
    (sandbox / "benchmark_latency.py").write_text(
        "import time\n\ndef measure_inference(model: str):\n    t0 = time.perf_counter()\n    return time.perf_counter() - t0\n\nif __name__ == '__main__':\n    print('Latency:', measure_inference('gemma3'))\n",
        encoding="utf-8"
    )

    # 4. Config YAML
    (sandbox / "docker-compose.yml").write_text(
        "version: '3.8'\nservices:\n  dashboard:\n    build: .\n    ports:\n      - '8000:8000'\n    environment:\n      - SENTRY_DSN=${SENTRY_DSN}\n",
        encoding="utf-8"
    )

    # 5. PDF invoice using pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 72), "INVOICE: INV-2026-9041\nVendor: AWS Cloud Services\nDate: October 1, 2026\nAmount Due: $156.40\nService: GPU compute instance (gemma3 testing)", fontsize=12)
    pdf_path = sandbox / "aws_invoice_oct2026.pdf"
    doc.save(str(pdf_path))
    doc.close()

    # 6. Exact Duplicate PDF (to test SHA-256 deduplication!)
    (sandbox / "aws_invoice_oct2026 (copy).pdf").write_bytes(pdf_path.read_bytes())

    # 7. Real PNG image
    (sandbox / "architecture_diagram.png").write_bytes(make_png(200, 150))

    # 8. Hidden junk file (to test filtering)
    (sandbox / ".DS_Store").write_text("dummy_metadata")

    files = list(sandbox.iterdir())
    print(f"Created sandbox with {len(files)} files in {sandbox.resolve()}")
    for f in files:
        print(f"  - {f.name} ({f.stat().st_size} bytes)")

if __name__ == "__main__":
    create_sandbox()
