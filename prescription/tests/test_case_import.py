"""Intake checks use invented records and numbers, never clinical source rows."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from mingyirx.case_import import (
    CaseImportError, MAX_RECORDS, MAX_TEXT_BYTES, RECORD_FIELDS,
    prepare_import, recognize_text,
)
from mingyirx.inheritance import validate_bundle


SAMPLES = Path(__file__).resolve().parents[1] / "data/synthetic/case_import_samples"
SOURCE = hashlib.sha256(b"SYNTHETIC ONLY: invented intake text").hexdigest()


def candidate(**changes):
    row = {"subject_code": "SYN-S1", "episode_code": "E1", "physician_code": "SYN-D1",
           "visit_code": "V1", "date": "2025-01-01", "condition": "SYNTHETIC ONLY",
           "symptoms": "no dry mouth; simulated fatigue", "prescription": "HerbA 10g"}
    row.update(changes)
    return recognize_text(json.dumps([row]), SOURCE, "json")["records"][0]


class CaseImportTests(unittest.TestCase):
    def prepare(self, records):
        result = prepare_import(records, synthetic=True)
        self.assertNotEqual(result["gate"], "BLOCK", result["errors"])
        self.assertEqual(validate_bundle(result["bundle"])["errors"], [])
        return result

    def assert_block(self, records, code):
        result = prepare_import(records, synthetic=True)
        self.assertEqual(result["gate"], "BLOCK")
        self.assertIn(code, [issue["code"] for issue in result["errors"]])
        self.assertIsNone(result["bundle"])
        self.assertEqual(result["pairs"], [])
        self.assertTrue(all(set(issue) == {"code", "record", "field"} for issue in result["errors"]))
        return result

    def test_committed_samples_are_explicitly_synthetic_and_core_valid(self):
        expected = {"labeled.txt": (1, 2, 1), "same_day.csv": (1, 2, 1), "coded_records.json": (2, 2, 0)}
        for name, counts in expected.items():
            with self.subTest(name=name):
                data = (SAMPLES / name).read_bytes()
                recognized = recognize_text(data.decode("utf-8"), hashlib.sha256(data).hexdigest(), name.rsplit(".", 1)[1])
                result = self.prepare(recognized["records"])
                self.assertEqual(tuple(result["counts"][key] for key in ("cases", "visits", "pairs")), counts)
                self.assertTrue(result["bundle"]["synthetic"])
                self.assertTrue(all(row["condition"] == "SYNTHETIC ONLY" for row in recognized["records"]))

    def test_chinese_labels_negation_missing_clinical_fields_and_real_herb_names(self):
        text = ("\u60a3\u8005\u7f16\u7801: SYN-CN\n\u533b\u6848\u7f16\u7801: E1\n"
                "\u533b\u5e08\u7f16\u7801: D1\n\u8bbf\u6b21\u7f16\u7801: V1\n"
                "\u65e5\u671f: 2025/1/2\n\u75c7\u72b6: \u65e0\u53e3\u5e72\n"
                "\u5904\u65b9: \u9ec4\u82aa 10g\n\u767d\u828d 6g\n")
        recognized = recognize_text(text, SOURCE, "txt")
        row = recognized["records"][0]
        self.assertEqual(set(row), set(RECORD_FIELDS))
        self.assertEqual(row["date"], "2025-01-02")
        self.assertEqual(row["symptoms"], "\u65e0\u53e3\u5e72")
        self.assertEqual(row["evidence"]["prescription"], [7, 8])
        self.assertEqual(row["syndrome"], "")
        result = self.prepare([row])
        pre = result["bundle"]["cases"][0]["visits"][0]["pre"]
        self.assertEqual(pre["syndrome_codes"], [])
        self.assertEqual(pre["principle_codes"], [])
        self.assertIsNone(pre["symptoms"][0]["severity"])
        self.assertEqual({item["label"] for item in result["bundle"]["vocabulary"]["medicines"]}, {"\u9ec4\u82aa", "\u767d\u828d"})

    def test_ocr_fixed_labels_without_colons_keep_uncertain_text_and_codes(self):
        text = ("subject_code SYN-OCR\nepisode code EI\nphysician code DI\nvisit code VI\n"
                "date 2025 \uff0e 01 \uff0e 01\ncondition SYNTHETIC ONLY\n"
                "symptoms NO d ry mouth\nprescription HerbA 10g")
        result = recognize_text(text, SOURCE, "ocr")
        row = result["records"][0]
        self.assertEqual(row["episode_code"], "EI")
        self.assertEqual(row["date"], "")
        self.assertEqual(row["symptoms"], "NO d ry mouth")
        self.assertIn("DATE_UNRESOLVED", [warning["code"] for warning in result["warnings"]])
        self.prepare([row])

    def test_negation_scope_keeps_commas_and_enumeration_in_one_literal_label(self):
        for symptoms in ("\u65e0\u53d1\u70ed\u3001\u76d7\u6c57", "No fever, night sweats"):
            result = self.prepare([candidate(symptoms=symptoms)])
            self.assertEqual([item["label"] for item in result["bundle"]["vocabulary"]["symptoms"]], [symptoms])

    def test_known_empty_label_accepts_only_immediately_following_value(self):
        text = ("subject_code:\nSYN-DOCX\nepisode_code\nE1\nphysician_code:\nD1\n"
                "visit_code:\nV1\nsymptoms:\nNo fever, night sweats\n"
                "syndrome:\n\nunknown prose after blank")
        result = recognize_text(text, SOURCE, "docx")
        row = result["records"][0]
        self.assertEqual(row["subject_code"], "SYN-DOCX")
        self.assertEqual(row["episode_code"], "E1")
        self.assertEqual(row["evidence"]["subject_code"], [1, 2])
        self.assertEqual(row["evidence"]["symptoms"], [9, 10])
        self.assertEqual(row["syndrome"], "")
        self.assertIn("UNRECOGNIZED_LINE", [w["code"] for w in result["warnings"]])

    def test_txt_context_is_local_and_does_not_cross_subjects(self):
        text = ("subject_code: SYN-A\nepisode_code: E1\nphysician_code: D1\nvisit_code: V1\n"
                "symptoms: no fatigue\nvisit_code: V2\nsymptoms: simulated fatigue\n"
                "subject_code: SYN-B\nvisit_code: V1\nsymptoms: no fatigue")
        rows = recognize_text(text, SOURCE, "txt")["records"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["subject_code"], "SYN-A")
        self.assertEqual(rows[1]["evidence"]["subject_code"], [1])
        self.assertEqual(rows[2]["episode_code"], "")
        self.assertEqual(rows[2]["physician_code"], "")

    def test_txt_new_physician_does_not_rewrite_previous_visit(self):
        text = ("subject_code: SYN-A\nepisode_code: E1\nphysician_code: D1\nvisit_code: V1\n"
                "symptoms: no fatigue\nphysician_code: D2\nvisit_code: V2\nsymptoms: no fatigue")
        rows = recognize_text(text, SOURCE, "txt")["records"]
        self.assertEqual([row["physician_code"] for row in rows], ["D1", "D2"])
        result = self.prepare(rows)
        self.assertEqual(result["counts"]["cases"], 2)
        self.assertEqual(result["pairs"], [])

    def test_evidence_uses_actual_json_key_lines_and_multiline_csv_rows(self):
        text = '[\n {"subject_code":"SYN-A",\n "symptoms":"quoted \\\"date\\\": 2025",\n "date":"2025-01-01"}\n]'
        row = recognize_text(text, SOURCE, "json")["records"][0]
        self.assertEqual(row["evidence"]["date"], [4])
        self.assertEqual(row["evidence"]["symptoms"], [3])
        row = recognize_text('subject_code,symptoms\nSYN-A,"no dry mouth\nno fatigue"\n', SOURCE, "csv")["records"][0]
        self.assertEqual(row["evidence"]["symptoms"], [2, 3])
        self.assertEqual(row["symptoms"], "no dry mouth\nno fatigue")

    def test_unrecognized_lines_and_headers_are_warned_without_echo(self):
        for text, extension in (("unrecognized sensitive fragment", "txt"), ('[{"unknown_column":"private fragment"}]', "json"), ("private_column\nprivate fragment", "csv")):
            result = recognize_text(text, SOURCE, extension)
            self.assertEqual(result["records"], [])
            self.assertNotIn("private", json.dumps(result))
            self.assertTrue(result["warnings"])

    def test_malformed_duplicate_nonfinite_and_alias_collisions_reject(self):
        inputs = [('{"subject_code":"S1"}', "json"), ('[{"date":1,"date":2}]', "json"),
                  ('[{"sequence":NaN}]', "json"), ('[{"sequence":Infinity}]', "json"),
                  ('[', "json"), ('[1]', "json"), ('[{"date":"x","visit_date":"x"}]', "json"),
                  ('date,visit_date\nx,x', "csv"), ('date,symptoms\nx,y,z', "csv"),
                  ('date\n"unterminated', "csv"), ('[{"symptoms":"\\ud800"}]', "json")]
        for text, extension in inputs:
            with self.subTest(text=text):
                with self.assertRaises(CaseImportError) as caught:
                    recognize_text(text, SOURCE, extension)
                self.assertRegex(str(caught.exception), r"^[A-Z_]+$")

    def test_recognition_bounds_encoding_hash_and_format(self):
        inputs = [("x" * (MAX_TEXT_BYTES + 1), SOURCE, "txt"), ("\ud800", SOURCE, "txt"),
                  ("\x00", SOURCE, "txt"), ("x", "bad", "txt"), ("x", SOURCE, "exe"),
                  (json.dumps([{}] * (MAX_RECORDS + 1)), SOURCE, "json")]
        for arguments in inputs:
            with self.subTest(size=len(arguments[0])):
                with self.assertRaises(CaseImportError):
                    recognize_text(*arguments)

    def test_candidate_is_deterministic_and_import_does_not_mutate_records(self):
        rows = [candidate(), candidate(visit_code="V2", date="2025-01-08")]
        before = copy.deepcopy(rows)
        first = self.prepare(rows)
        self.assertEqual(rows, before)
        self.assertEqual(first, self.prepare(rows))
        self.assertEqual(candidate()["record_id"], candidate()["record_id"])

    def test_exact_codes_and_record_shape_are_required(self):
        for key, value in (("subject_code", "a person"), ("episode_code", ""), ("physician_code", "\u67d0\u533b\u5e08"), ("visit_code", "x" * 49)):
            row = candidate()
            row[key] = value
            self.assert_block([row], "CODE_REQUIRED")
        row = candidate()
        row["name"] = "unaccepted identity field"
        result = self.assert_block([row], "EXACT_RECORD_KEYS_REQUIRED")
        self.assertNotIn("identity", json.dumps(result))
        self.assert_block([], "RECORD_ARRAY_REQUIRED")
        self.assert_block({}, "RECORD_ARRAY_REQUIRED")

    def test_direct_candidate_types_and_evidence_are_strict(self):
        for key, value, code in (("sequence", True, "SEQUENCE_INVALID"), ("sequence", 0, "SEQUENCE_INVALID"),
                                 ("date", "2025-02-30", "DATE_INVALID"), ("date", None, "DATE_INVALID"),
                                 ("symptoms", "\ud800", "TEXT_FIELD_INVALID"), ("prescription", [], "TEXT_FIELD_INVALID"),
                                 ("source_sha256", "bad", "SOURCE_SHA256_INVALID"),
                                 ("evidence", {"symptoms": [1, 1]}, "EVIDENCE_INVALID"),
                                 ("evidence", {"symptoms": [[1]]}, "EVIDENCE_INVALID"),
                                 ("evidence", {"name": [1]}, "EVIDENCE_INVALID")):
            with self.subTest(key=key, value_type=type(value).__name__):
                row = candidate()
                row[key] = value
                self.assert_block([row], code)

    def test_dates_sort_and_convert_to_offsets_without_source_dates_in_bundle(self):
        rows = [candidate(visit_code="V2", date="2025-01-08"), candidate(visit_code="V1", date="2025-01-01")]
        result = self.prepare(rows)
        visits = result["bundle"]["cases"][0]["visits"]
        self.assertEqual([v["visit_id"] for v in visits], ["V1", "V2"])
        self.assertEqual([v["offset_days"] for v in visits], [0, 7])
        self.assertNotIn("2025-", json.dumps(result["bundle"]))
        self.assertEqual(result["counts"]["eligible_pairs"], 1)

    def test_no_link_across_subject_episode_or_physician(self):
        rows = [candidate(), candidate(subject_code="SYN-S2"), candidate(episode_code="E2"), candidate(physician_code="SYN-D2")]
        result = self.prepare(rows)
        self.assertEqual(result["counts"]["cases"], 4)
        self.assertEqual(result["counts"]["subjects"], 2)
        self.assertEqual(result["pairs"], [])

    def test_duplicate_visit_ignores_metadata_but_keeps_source_hash_provenance(self):
        original = candidate()
        duplicate = copy.deepcopy(original)
        duplicate.update(record_id="OTHER-RECORD", source_sha256="a" * 64, evidence={"symptoms": "user-reviewed"})
        result = self.prepare([original, duplicate])
        self.assertEqual(result["counts"]["duplicates"], 1)
        self.assertEqual(result["counts"]["visits"], 1)
        self.assertIn("DUPLICATE_VISIT_IGNORED", [w["code"] for w in result["warnings"]])
        source_hash = hashlib.sha256(json.dumps(sorted([SOURCE, "a" * 64]), separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(result["bundle"]["sources"][0]["sha256"], source_hash)
        self.assertEqual(self.prepare([original, original])["bundle"], self.prepare([original])["bundle"])

    def test_duplicate_visit_clinical_conflict_blocks_instead_of_overwriting(self):
        self.assert_block([candidate(), candidate(symptoms="simulated different symptom")], "CONFLICTING_VISIT")
        self.assert_block([candidate(), candidate(date="2025-02-01")], "CONFLICTING_VISIT")

    def test_same_day_unknown_sequence_edges_are_unresolved_and_never_reconnected(self):
        rows = [candidate(visit_code="V1", date="2025-01-01"), candidate(visit_code="V2", date="2025-01-02"),
                candidate(visit_code="V3", date="2025-01-02", sequence=3), candidate(visit_code="V4", date="2025-01-03")]
        result = self.prepare(rows)
        self.assertEqual(result["counts"]["pairs"], 3)
        self.assertEqual(result["counts"]["unresolved_pairs"], 3)
        self.assertEqual(result["counts"]["eligible_pairs"], 0)
        self.assertFalse(any(p["from_visit_id"] == "V1" and p["to_visit_id"] == "V4" for p in result["pairs"]))

    def test_explicit_same_day_sequence_can_resolve_order(self):
        result = self.prepare([candidate(visit_code="V2", sequence=2), candidate(visit_code="V1", sequence=1)])
        self.assertEqual(result["counts"]["eligible_pairs"], 1)
        self.assertEqual([v["visit_id"] for v in result["bundle"]["cases"][0]["visits"]], ["V1", "V2"])

    def test_missing_dates_complete_sequence_stays_unknown_and_incomplete_blocks(self):
        result = self.prepare([candidate(visit_code="V1", date="", sequence=1), candidate(visit_code="V2", sequence=2)])
        visits = result["bundle"]["cases"][0]["visits"]
        self.assertEqual([v["offset_days"] for v in visits], [0, 0])
        self.assertTrue(all(not v["order_known"] for v in visits))
        self.assertEqual(result["counts"]["unresolved_pairs"], 1)
        self.assertIn("DATE_MISSING_INTERVAL_UNKNOWN", [w["code"] for w in result["warnings"]])
        self.assert_block([candidate(date=""), candidate(visit_code="V2")], "ORDER_INPUT_REQUIRED")

    def test_duplicate_and_date_conflicting_sequences_block(self):
        self.assert_block([candidate(sequence=1), candidate(visit_code="V2", sequence=1)], "DUPLICATE_SEQUENCE")
        self.assert_block([candidate(sequence=2), candidate(visit_code="V2", date="2025-01-08", sequence=1)], "DATE_SEQUENCE_CONFLICT")

    def test_condition_variation_is_not_unioned_into_earlier_pre_features(self):
        for changed in ("SYNTHETIC DIFFERENT", ""):
            self.assert_block([candidate(), candidate(visit_code="V2", date="2025-01-08", condition=changed)], "CONDITION_VARIATION_REQUIRES_REVIEW")
        result = self.prepare([candidate(condition=""), candidate(visit_code="V2", date="2025-01-08", condition="")])
        self.assertEqual(result["bundle"]["cases"][0]["condition_codes"], [])
        self.assertIn("UNCONFIRMED_ATTRIBUTION", [w["code"] for w in result["warnings"]])

    def test_doses_unknown_units_ranges_negative_and_basis_remain_conservative(self):
        result = self.prepare([candidate(prescription="HerbA 10g; HerbB 5\u5305; HerbC 10-15g; HerbD -5g; HerbE >10g; HerbF \u5242\u91cf\u4e0d\u8be6")])
        bundle = result["bundle"]
        labels = {item["code"]: item["label"] for item in bundle["vocabulary"]["medicines"]}
        drugs = {labels[d["medicine_code"]]: d for d in bundle["cases"][0]["visits"][0]["prescription"]}
        self.assertEqual(drugs["HerbA"]["dose"], 10)
        self.assertEqual(drugs["HerbB"]["dose"], 5)
        self.assertEqual(drugs["HerbB"]["unit"], "unknown")
        for label in ("HerbC", "HerbD", "HerbE", "HerbF"):
            self.assertIsNone(drugs[label]["dose"])
        self.assertTrue(all(d["basis"] == "unknown" and d["preparation"] == "unknown" for d in drugs.values()))
        self.assertIn("DOSE_UNRESOLVED", [w["code"] for w in result["warnings"]])

    def test_huge_dose_is_unknown_and_duplicate_medicine_blocks(self):
        row = candidate(prescription="HerbA " + "9" * 400 + "g")
        result = self.prepare([row])
        self.assertIsNone(result["bundle"]["cases"][0]["visits"][0]["prescription"][0]["dose"])
        self.assert_block([candidate(prescription="HerbA 10g; HerbA 12g")], "DUPLICATE_MEDICINE")

    def test_decimal_and_range_doses_do_not_move_punctuation_into_herb_name(self):
        for token, expected in (("0.5g", 0.5), (".5g", 0.5), ("2.5g", 2.5), ("0.50g", 0.5), ("12-15g", None), ("-.5g", None)):
            with self.subTest(token=token):
                result = self.prepare([candidate(prescription="\u9ec4\u82aa " + token)])
                self.assertEqual(result["bundle"]["vocabulary"]["medicines"][0]["label"], "\u9ec4\u82aa")
                self.assertEqual(result["bundle"]["cases"][0]["visits"][0]["prescription"][0]["dose"], expected)

    def test_prescription_separators_do_not_create_false_removed_medicines(self):
        for separator in (",", "\uff0c", "\u3001"):
            with self.subTest(separator=separator):
                result = self.prepare([candidate(prescription="HerbA 10g; HerbB 5g"),
                    candidate(visit_code="V2", date="2025-01-08", prescription="HerbA 10g" + separator + " HerbB 5g")])
                self.assertEqual(result["pairs"][0]["removed"], [])
                self.assertEqual(result["pairs"][0]["added"], [])
                self.assertEqual(len(result["pairs"][0]["retained"]), 2)
                self.assertEqual([d["dose"] for d in result["bundle"]["cases"][0]["visits"][1]["prescription"]], [10, 5])

    def test_ambiguous_prescription_tails_block_instead_of_discarding_text(self):
        for text in ("HerbA 10g HerbB 5g", "HerbA 10g HerbB", "HerbA 10g and HerbB",
                     "HerbA 10g\uff08\u672a\u7528\uff09", "HerbA 10-15g HerbB 5g", "HerbA 10g/day"):
            with self.subTest(text=text):
                self.assert_block([candidate(prescription=text)], "PRESCRIPTION_TOKEN_AMBIGUOUS")
        result = self.prepare([candidate(prescription="HerbA 10g\uff0cHerbB")])
        self.assertEqual([v["label"] for v in result["bundle"]["vocabulary"]["medicines"]], ["HerbA", "HerbB"])
        self.assertIsNone(result["bundle"]["cases"][0]["visits"][0]["prescription"][1]["dose"])

    def test_ranges_preserve_unknown_amount_without_swallowing_another_medicine(self):
        for amount in ("10-15g", "10g-15g", "10\u81f315g"):
            result = self.prepare([candidate(prescription="HerbA " + amount + ", HerbB 5g")])
            drugs = result["bundle"]["cases"][0]["visits"][0]["prescription"]
            self.assertEqual(len(drugs), 2)
            self.assertIsNone(drugs[0]["dose"])
            self.assertEqual(drugs[0]["unit"], "g")
            self.assertEqual(drugs[1]["dose"], 5)

    def test_only_complete_prescription_lines_extend_labeled_prescription(self):
        prefix = "subject_code: SYN-REVIEW\nepisode_code: E1\nphysician_code: D1\nvisit_code: V1\n"
        text = prefix + "prescription: HerbA 10g\nFollow up in 7 days\nHerbB 5g"
        recognized = recognize_text(text, SOURCE, "txt")
        row = recognized["records"][0]
        self.assertEqual(row["prescription"], "HerbA 10g")
        self.assertEqual(row["evidence"]["prescription"], [5])
        self.assertEqual([w["line"] for w in recognized["warnings"] if w["code"] == "UNRECOGNIZED_LINE"], [6, 7])
        for line in ("HerbB 5mg", "\u767d\u828d 5\u514b", "\u767d\u828d 5\u6beb\u514b", "HerbB .5ml"):
            recognized = recognize_text(prefix + "prescription: HerbA 10g\n" + line, SOURCE, "txt")
            row = recognized["records"][0]
            self.assertEqual(row["prescription"], "HerbA 10g\n" + line)
            self.assertEqual(row["evidence"]["prescription"], [5, 6])
            self.prepare([row])
        row = recognize_text(prefix + "prescription:\nFollow up in 7 days", SOURCE, "txt")["records"][0]
        self.assertEqual(row["prescription"], "")

    def test_attribution_and_operator_edits_remain_draft_algorithm_declarations(self):
        row = candidate()
        row["evidence"]["symptoms"] = "user-reviewed"
        result = self.prepare([row])
        bundle = result["bundle"]
        self.assertTrue(all(s["review_status"] == "pending" and s["reviewer_id"] is None for s in bundle["sources"] + bundle["physicians"]))
        self.assertEqual(bundle["annotations"][0]["origin"], "algorithm")
        self.assertEqual(bundle["annotations"][0]["status"], "draft")
        self.assertIn("operator", bundle["annotations"][0]["statement"])
        self.assertEqual(bundle["experiences"], [])
        self.assertEqual(bundle["cases"][0]["visits"][0]["outcome_codes"], [])
        self.assertFalse(prepare_import([row])["bundle"]["synthetic"])
        self.assertEqual(prepare_import([row], synthetic="yes")["gate"], "BLOCK")

    def test_dynamic_labels_are_still_checked_by_inheritance_privacy_rules(self):
        for value in ("https://example.test", "private@example.test", "<script>", "2025-01-01", "a" * 81):
            result = self.assert_block([candidate(symptoms=value)], "BUNDLE_TEXT_UNSAFE_OR_INVALID")
            self.assertNotIn(value, json.dumps(result))


if __name__ == "__main__":
    unittest.main()
