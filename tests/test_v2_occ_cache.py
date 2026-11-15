"""V2 stage 3: the copying cache (forge_occ.cache; docs/V2-stage3.md, section 10).

A hit and a miss; every part of the key, changed alone, a miss; every hit a
fresh copy that nothing done to an earlier one can reach; face order kept
through serialization; corrupt, truncated, altered and other-scheme entries
read as misses, in memory and on disk; and the byte bound held.
"""

from __future__ import annotations

import struct
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

from v2_occ import build, converted, needs_occ, zoo

try:
    from forge_occ import cache as cache_module
    from forge_occ.backend import BACKEND_IDENTITY, OccBackend
    from forge_occ.cache import SCHEME, StepCache, canonical, step_key
    from forge_occ.names import Name, named_by
    from forge_occ.occt import faces, from_bytes, to_bytes, vertices, volume
    from forge_occ.products import SolidProduct
    from forge_occ.view import face_facts
    from OCP.BRep import BRep_Builder, BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
except ImportError:  # no OpenCascade here: every class below is skipped
    pass


def key(**change: object) -> str:
    parts = {
        "identity": BACKEND_IDENTITY, "op": "box", "step": "plate", "role": "plate",
        "params": {"size": (40.0, 30.0, 6.0), "centered": False}, "references": {}, "inputs": ["a" * 64], "v1": None,
    }  # fmt: skip
    parts.update(change)
    return step_key(**parts)  # type: ignore[arg-type]


def box_product() -> SolidProduct:
    shape = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
    return SolidProduct(
        shape,
        named_by(shape, lambda _f: (Name("box", "side"),)),
        notes=("a note",),
        tolerance=1e-7,
    )


@needs_occ
class HitsAndMisses(unittest.TestCase):
    def test_a_second_build_is_all_hits_and_the_same_part(self) -> None:
        cache = StepCache()
        text = zoo()["golden_clevis"]
        first = build(text, cache=cache)
        second = build(text, cache=cache)
        self.assertTrue(all(t.reused for t in second.traces if t.volume is not None))
        self.assertFalse(any(t.reused for t in first.traces))
        self.assertEqual(first.names.table, second.names.table)
        self.assertAlmostEqual(volume(first.shape), volume(second.shape), delta=1e-9)
        self.assertFalse(first.shape.IsSame(second.shape))

    def test_a_changed_parameter_rebuilds_from_that_step(self) -> None:
        cache = StepCache()
        document = converted(zoo()["golden_clevis"])
        OccBackend().build(document, "clevis", cache=cache)
        again = OccBackend().build(
            document, "clevis", cache=cache, overrides=_override("ear_thickness", 7.0)
        )
        reused = {t.step for t in again.traces if t.reused}
        self.assertIn("base_plate", reused)
        self.assertNotIn("ear_left", reused)
        self.assertNotIn("pivot", reused)

    def test_a_bend_chain_comes_back_whole(self) -> None:
        cache = StepCache()
        text = zoo()["zoo_l_bracket_bent"]
        first = build(text, cache=cache)
        second = build(text, cache=cache)
        self.assertTrue(all(t.reused for t in second.traces if t.volume is not None))
        bend = [s for s, p in second.products.items() if getattr(p, "chain", ())]
        self.assertTrue(bend)
        a, b = first.products[bend[0]], second.products[bend[0]]
        self.assertEqual(a.chain, b.chain)
        self.assertEqual(a.flat.names.table, b.flat.names.table)


def _override(name: str, value: float) -> dict[str, Any]:
    from forge_units import Quantity

    return {name: Quantity.exact(value, "mm")}


@needs_occ
class EveryPartOfTheKey(unittest.TestCase):
    def test_each_part_changed_alone_is_another_key(self) -> None:
        base = key()
        changed = [
            key(identity="occt-7.9.3/forge-occ-other"),
            key(op="cylinder"),
            key(step="other"),
            key(role="other"),
            key(params={"size": (40.0, 30.0, 6.000000000000001), "centered": False}),
            key(params={"size": (40.0, 30.0, 6.0), "centered": True}),
            key(params={"size": (40.0, 30.0, 6.0)}),
            key(references={"edges": {"of": "x"}}),
            key(inputs=["b" * 64]),
            key(v1=[[0.0] * 6]),
        ]
        self.assertEqual(len({base, *changed}), len(changed) + 1)

    def test_the_backends_version_and_the_scheme_are_in_it(self) -> None:
        original = cache_module.SCHEME
        try:
            before = key()
            cache_module.SCHEME = original + 1
            self.assertNotEqual(before, key())
        finally:
            cache_module.SCHEME = original
        self.assertEqual(SCHEME, original)

    def test_a_number_is_written_exactly_and_kinds_apart(self) -> None:
        self.assertNotEqual(canonical(1), canonical(1.0))
        self.assertNotEqual(canonical(0.1), canonical(0.1 + 2**-56))
        self.assertNotEqual(canonical("1"), canonical(1))
        self.assertNotEqual(canonical((1.0,)), canonical(1.0))

    def test_what_it_cant_write_exactly_is_refused(self) -> None:
        for value in (object(), float("nan"), {1: 2.0}):
            with self.assertRaises(TypeError):
                canonical(value)


@needs_occ
class EveryHitIsAFreshCopy(unittest.TestCase):
    def test_face_order_survives_serialization(self) -> None:
        shape = build(zoo()["golden_clevis"]).shape
        again = from_bytes(to_bytes(shape))
        self.assertEqual([face_facts(TopoDS.Face(f)) for f in faces(shape)],
                         [face_facts(TopoDS.Face(f)) for f in faces(again)])  # fmt: skip

    def test_what_a_caller_does_to_a_hit_never_reaches_the_next(self) -> None:
        cache = StepCache()
        cache.put("0" * 64, box_product())
        first = cache.get("0" * 64)
        assert first is not None
        BRepMesh_IncrementalMesh(first.shape, 0.5)
        BRep_Builder().UpdateVertex(TopoDS.Vertex(vertices(first.shape)[0]), 0.25)
        first.shape.Move(TopLoc_Location(_shift()))
        second = cache.get("0" * 64)
        assert second is not None
        where = TopLoc_Location()
        self.assertIsNone(
            BRep_Tool.Triangulation_s(TopoDS.Face(faces(second.shape)[0]), where)
        )
        self.assertLess(
            BRep_Tool.Tolerance_s(TopoDS.Vertex(vertices(second.shape)[0])), 1e-6
        )
        self.assertTrue(second.shape.Location().IsIdentity())
        self.assertFalse(first.shape.IsSame(second.shape))
        self.assertEqual(second.notes, ("a note",))
        self.assertEqual(second.tolerance, 1e-7)

    def test_a_product_changed_after_it_was_stored_doesnt_change_the_entry(
        self,
    ) -> None:
        cache = StepCache()
        product = box_product()
        cache.put("1" * 64, product)
        BRepMesh_IncrementalMesh(product.shape, 0.5)
        found = cache.get("1" * 64)
        assert found is not None
        self.assertIsNone(
            BRep_Tool.Triangulation_s(
                TopoDS.Face(faces(found.shape)[0]), TopLoc_Location()
            )
        )


def _shift() -> Any:
    from OCP.gp import gp_Trsf, gp_Vec

    trsf = gp_Trsf()
    trsf.SetTranslation(gp_Vec(5.0, 0.0, 0.0))
    return trsf


@needs_occ
class CorruptEntriesAreMisses(unittest.TestCase):
    def corrupted(self, change: Callable[[bytes], bytes]) -> StepCache:
        cache = StepCache()
        cache.put("2" * 64, box_product())
        cache._entries["2" * 64] = change(cache._entries["2" * 64])
        return cache

    def test_truncated_altered_and_another_schemes(self) -> None:
        header = struct.Struct("<16sIQQ")

        def other_scheme(data: bytes) -> bytes:
            magic, scheme, a, b = header.unpack_from(data)
            return header.pack(magic, scheme + 1, a, b) + data[header.size :]

        for change in (lambda d: d[: len(d) // 2], lambda d: d[:-40] + bytes([d[-40] ^ 1]) + d[-39:],
                       other_scheme, lambda d: b"", lambda d: d + b"tail"):  # fmt: skip
            cache = self.corrupted(change)
            self.assertIsNone(cache.get("2" * 64))
            self.assertEqual(cache.stats.unreadable, 1)
            self.assertNotIn("2" * 64, cache._entries)

    def test_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            StepCache(directory=folder).put("3" * 64, box_product())
            fresh = StepCache(directory=folder)
            self.assertIsNotNone(fresh.get("3" * 64))
            path = next(Path(folder).rglob("*.step-cache"))
            path.write_bytes(path.read_bytes()[:100])
            again = StepCache(directory=folder)
            self.assertIsNone(again.get("3" * 64))
            self.assertEqual(again.stats.unreadable, 1)
            self.assertFalse(path.exists())

    def test_a_folder_that_cant_be_written_is_no_cache_not_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            blocked = Path(folder) / "file"
            blocked.write_text("not a folder")
            cache = StepCache(directory=blocked)
            cache.put("4" * 64, box_product())
            self.assertIsNotNone(cache.get("4" * 64))


@needs_occ
class TheByteBound(unittest.TestCase):
    def test_the_oldest_go_first_and_the_bound_holds(self) -> None:
        one = len(cache_module._encode(box_product()))
        cache = StepCache(max_bytes=3 * one)
        for i in range(5):
            cache.put(f"{i}" * 64, box_product())
        self.assertLessEqual(cache.bytes, 3 * one)
        self.assertEqual(len(cache), 3)
        self.assertEqual(cache.stats.evicted, 2)
        self.assertIsNone(cache.get("0" * 64))
        self.assertIsNotNone(cache.get("4" * 64))

    def test_an_entry_bigger_than_the_bound_is_not_kept(self) -> None:
        cache = StepCache(max_bytes=10)
        cache.put("5" * 64, box_product())
        self.assertEqual(len(cache), 0)
        with self.assertRaises(ValueError):
            StepCache(max_bytes=0)


if __name__ == "__main__":
    unittest.main()
