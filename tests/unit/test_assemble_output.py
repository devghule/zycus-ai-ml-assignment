import json
from pathlib import Path

from pipeline.assemble_output import DocumentResult, write_result


def test_wrapper_shape_matches_contract():
    result = DocumentResult(file_name="X.pdf")
    wrapper = result.to_wrapper()
    assert set(wrapper.keys()) == {"file", "payables", "declined"}
    assert wrapper["file"] == "X.pdf"
    assert wrapper["payables"] == []
    assert wrapper["declined"] == []


def test_write_result_creates_deterministically_named_file(tmp_path: Path):
    result = DocumentResult(file_name="INV-01.pdf")
    out_path = write_result(result, output_dir=tmp_path)
    assert out_path == tmp_path / "INV-01.json"
    assert out_path.exists()


def test_write_result_output_is_valid_json_with_required_keys(tmp_path: Path):
    result = DocumentResult(file_name="HLD-01.pdf", payables=[], declined=[])
    out_path = write_result(result, output_dir=tmp_path)
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["file"] == "HLD-01.pdf"
    assert isinstance(data["payables"], list)
    assert isinstance(data["declined"], list)


def test_write_result_creates_output_dir_if_absent(tmp_path: Path):
    output_dir = tmp_path / "nested" / "output"
    assert not output_dir.exists()
    write_result(DocumentResult(file_name="A.pdf"), output_dir=output_dir)
    assert output_dir.exists()
