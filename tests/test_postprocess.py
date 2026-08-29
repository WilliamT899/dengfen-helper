"""分数/姓名/学号后处理单元测试。"""
import pytest

from app.ocr import postprocess


class TestParseScore:
    def test_plain(self):
        assert postprocess.parse_score("98").value == 98
        assert not postprocess.parse_score("98").warning

    def test_decimal(self):
        assert postprocess.parse_score("98.5").value == 98.5

    def test_missing_dot_heuristic(self):
        r = postprocess.parse_score("985")
        assert r.value == 98.5
        assert r.warning

    def test_missing_dot_other(self):
        assert postprocess.parse_score("987").value == 98.7

    def test_hundred(self):
        assert postprocess.parse_score("100").value == 100

    def test_over_range(self):
        r = postprocess.parse_score("105")
        assert r.value == 105
        assert r.warning

    def test_garbage(self):
        assert postprocess.parse_score("S8S").value is None
        assert postprocess.parse_score("").value is None
        assert postprocess.parse_score("2026.7").value is None  # 日期

    def test_two_digit_1005(self):
        # 100.5 超出合法范围（满分 100），合法候选中选 10.05
        assert postprocess.parse_score("1005").value == 10.05


class TestNormalize:
    def test_name(self):
        assert postprocess.normalize_name(" 姓名：陈曦 ") == "陈曦"
        assert postprocess.normalize_name("Le0 邢子洋") == "邢子洋"

    def test_student_id(self):
        assert postprocess.normalize_student_id("学号：14") == "14"
        assert postprocess.normalize_student_id("07号") == "07"
