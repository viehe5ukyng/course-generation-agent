from pathlib import Path

from PIL import Image

from app.files.parser import DocumentParser


def test_parser_uses_ocr_for_images(tmp_path: Path):
    parser = DocumentParser()

    class StubOCR:
        def __call__(self, payload):
            return ([[None, "图片里的文字"]], None)

    parser._ocr_engine = StubOCR()  # type: ignore[attr-defined]

    image_path = tmp_path / "sample.png"
    Image.new("RGB", (32, 32), color="white").save(image_path)

    doc = parser.parse_file(image_path, "image/png")
    assert doc.extract_status == "parsed"
    assert any("图片里的文字" in chunk.text for chunk in doc.text_chunks)
