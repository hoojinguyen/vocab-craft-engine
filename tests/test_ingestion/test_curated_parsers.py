import json
from pathlib import Path
import pytest
from src.ingestion.cloth_parser import CLOTHParser
from src.ingestion.dailydialog_parser import DailyDialogParser
from src.ingestion.fvdp_parser import FVDPParser, normalize_vn_pos


def test_normalize_vn_pos():
    assert normalize_vn_pos("danh từ") == "noun"
    assert normalize_vn_pos("ngoại động từ") == "verb"
    assert normalize_vn_pos("nội động từ") == "verb"
    assert normalize_vn_pos("tính từ") == "adj"
    assert normalize_vn_pos("phó từ") == "adv"
    assert normalize_vn_pos("giới từ") == "prep"
    assert normalize_vn_pos("unknown_pos") == "noun"


def test_fvdp_parser_text_format(tmp_path):
    dict_file = tmp_path / "anhviet.txt"
    dict_file.write_text(
        "@abandon /ə'bændən/\n"
        "*  ngoại động từ\n"
        "- từ bỏ; buông thả\n"
        "=to abandon a habit+từ bỏ một thói quen\n"
        "*  danh từ\n"
        "- sự phóng túng, sự buông thả\n"
        "\n"
        "@ability /ə'biliti/\n"
        "*  danh từ\n"
        "- khả năng; năng lực\n"
        "=to the best of one's ability+với hết khả năng của mình\n",
        encoding="utf-8",
    )

    parser = FVDPParser(dict_file)
    entries = list(parser.parse_entries())

    assert len(entries) == 2
    assert entries[0]["lemma"] == "abandon"
    assert entries[0]["ipa"] == "/ə'bændən/"
    assert len(entries[0]["definitions"]) == 2
    assert entries[0]["definitions"][0]["pos"] == "verb"
    assert "từ bỏ" in entries[0]["definitions"][0]["definition_vi"]
    assert entries[0]["definitions"][0]["examples"][0]["text_en"] == "to abandon a habit"
    assert entries[0]["definitions"][0]["examples"][0]["text_vi"] == "từ bỏ một thói quen"

    assert entries[1]["lemma"] == "ability"
    assert entries[1]["ipa"] == "/ə'biliti/"


def test_dailydialog_parser_eou_and_json_formats(tmp_path):
    # 1. Text format
    txt_file = tmp_path / "dailydialog.txt"
    txt_file.write_text(
        "Hi! Welcome to our cafe. __eou__ I would like an espresso please. __eou__ Hot or iced? __eou__ Iced please. __eou__\n"
        "Excuse me, where is the library? __eou__ It is down the street on the left. __eou__ Thank you! __eou__\n",
        encoding="utf-8",
    )

    parser_txt = DailyDialogParser(txt_file)
    trees_txt = list(parser_txt.parse_trees())
    assert len(trees_txt) == 2
    assert len(trees_txt[0]["nodes"]) == 4
    assert trees_txt[0]["nodes"][0]["speaker_role"] == "A"
    assert trees_txt[0]["nodes"][1]["speaker_role"] == "B"
    assert trees_txt[0]["nodes"][1]["choice_label"] is not None
    assert trees_txt[0]["nodes"][0]["text_en"] == "Hi! Welcome to our cafe."

    # 2. JSON format
    json_file = tmp_path / "dailydialog.json"
    json_file.write_text(
        json.dumps([
            {
                "title": "Hotel Check-in",
                "topic": "Travel & Transportation",
                "cefr_level": "A2",
                "dialogue": ["Good evening, how can I help you?", "I have a reservation under Smith.", "Welcome Mr. Smith! Here is your room key."],
            }
        ]),
        encoding="utf-8",
    )

    parser_json = DailyDialogParser(json_file)
    trees_json = list(parser_json.parse_trees())
    assert len(trees_json) == 1
    assert trees_json[0]["title"] == "Hotel Check-in"
    assert trees_json[0]["topic"] == "Travel & Transportation"
    assert len(trees_json[0]["nodes"]) == 3


def test_cloth_parser_formats(tmp_path):
    # 1. Direct Cloze Drill JSON format
    direct_file = tmp_path / "cloth_direct.json"
    direct_file.write_text(
        json.dumps([
            {
                "prompt_text": "Fill in the blank: She decided to _______ the job offer.",
                "correct_answer": "accept",
                "distractors": ["swim", "run", "cry"],
                "target_time_ms": 2500,
            }
        ]),
        encoding="utf-8",
    )

    parser_direct = CLOTHParser(direct_file)
    drills_direct = list(parser_direct.parse_drills())
    assert len(drills_direct) == 1
    assert drills_direct[0]["correct_answer"] == "accept"
    distractors = json.loads(drills_direct[0]["distractors_json"])
    assert distractors == ["swim", "run", "cry"]

    # 2. Benchmark Multi-Blank Passage format
    bench_file = tmp_path / "cloth_bench.json"
    bench_file.write_text(
        json.dumps([
            {
                "article": "Tom wanted to _ his room before dinner. He also had to _ his homework.",
                "options": [
                    ["clean", "break", "burn", "fly"],
                    ["do", "kill", "forget", "tear"]
                ],
                "answers": ["A", "A"],
            }
        ]),
        encoding="utf-8",
    )

    parser_bench = CLOTHParser(bench_file)
    drills_bench = list(parser_bench.parse_drills())
    assert len(drills_bench) == 2
    assert drills_bench[0]["correct_answer"] == "clean"
    assert drills_bench[1]["correct_answer"] == "do"
