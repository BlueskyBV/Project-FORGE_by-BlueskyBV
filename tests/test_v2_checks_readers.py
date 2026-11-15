"""V2 stage 2: reading STL and 3MF files (forge_checks.readers).

Every file here is written by the test itself, so what it holds is known:
binary and text STL (including a binary one whose header begins "solid"),
and 3MF packages with units, transforms, components and mirrors, and each
thing a 3MF reader must refuse.
"""

from __future__ import annotations

import io
import struct
import unittest
import zipfile

import numpy as np
from forge_checks.readers import MeshFileError, read_3mf, read_mesh_file, read_stl
from numpy.typing import NDArray
from v2_meshes import box_soup

Array = NDArray[np.float64]
BOX = box_soup((0, 0, 0), (10, 20, 30))


def binary_stl(soup: Array, header: bytes = b"forge test") -> bytes:
    out = [header.ljust(80, b" "), struct.pack("<I", len(soup))]
    for t in soup:
        out.append(struct.pack("<12fH", 0.0, 0.0, 0.0, *t.reshape(-1).tolist(), 0))
    return b"".join(out)


def text_stl(soup: Array, solids: int = 1, upper: bool = False) -> bytes:
    lines = []
    for part in np.array_split(soup, solids):
        lines.append("solid part one")
        for t in part:
            lines += ["  facet normal 0 0 0", "    outer loop"]
            lines += [f"      vertex {x!r} {y!r} {z!r}" for x, y, z in t.tolist()]
            lines += ["    endloop", "  endfacet"]
        lines.append("endsolid part one")
    text = "\n".join(lines) + "\n"
    return (text.upper() if upper else text).encode("ascii")


CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'
)


def mesh_xml(soup: Array, ident: str, kind: str = "model") -> str:
    corners = soup.reshape(-1, 3)
    vertices = "".join(
        f'<vertex x="{x!r}" y="{y!r}" z="{z!r}"/>' for x, y, z in corners.tolist()
    )
    triangles = "".join(
        f'<triangle v1="{3 * k}" v2="{3 * k + 1}" v3="{3 * k + 2}"/>'
        for k in range(len(soup))
    )
    return f'<object id="{ident}" type="{kind}"><mesh><vertices>{vertices}</vertices><triangles>{triangles}</triangles></mesh></object>'


def package(model: str, rels: str = RELS) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
    return buffer.getvalue()


def model(resources: str, build: str, unit: str = "millimeter", extra: str = "") -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><model unit="{unit}" xmlns="{CORE}" {extra}>'
        f"<resources>{resources}</resources><build>{build}</build></model>"
    )


class Stl(unittest.TestCase):
    def test_binary(self) -> None:
        read = read_stl(binary_stl(BOX))
        np.testing.assert_array_equal(read.triangles, BOX)
        self.assertEqual((read.kind, read.unit, read.solids), ("stl", "none", 1))
        self.assertTrue(read.view(0.0).topology().sound)

    def test_binary_whose_header_begins_solid(self) -> None:
        read = read_mesh_file(binary_stl(BOX, header=b"solid exported by someone"))
        np.testing.assert_array_equal(read.triangles, BOX)

    def test_float32_corners_are_kept_to_the_bit(self) -> None:
        soup = BOX + 0.1
        read = read_stl(binary_stl(soup))
        np.testing.assert_array_equal(
            read.triangles, soup.astype(np.float32).astype(np.float64)
        )

    def test_text_in_any_case_and_several_solids(self) -> None:
        for upper in (False, True):
            read = read_stl(text_stl(BOX, solids=3, upper=upper))
            np.testing.assert_array_equal(read.triangles, BOX)
            self.assertEqual(read.solids, 3)

    def test_not_a_number_is_kept(self) -> None:
        soup = BOX.copy()
        soup[2, 1, 0] = np.nan
        read = read_stl(text_stl(soup))
        self.assertTrue(np.isnan(read.triangles[2, 1, 0]))
        self.assertFalse(read.view(0.0).topology().sound)

    def test_refused(self) -> None:
        good = text_stl(BOX[:1]).decode()
        bad = {
            "four vertices": good.replace(
                "    endloop", "      vertex 1 2 3\n    endloop"
            ),
            "no endloop": good.replace("    endloop\n", ""),
            "words for numbers": good.replace("vertex 0.0", "vertex zero"),
            "unfinished": good.replace("endsolid part one", ""),
            "nothing": "solid empty\nendsolid empty\n",
            "not a facet": good.replace("facet normal 0 0 0", "facet 0 0 0"),
        }
        for why, text in bad.items():
            with self.assertRaises(MeshFileError, msg=why):
                read_stl(text.encode("ascii"))
        with self.assertRaises(MeshFileError):
            read_stl(binary_stl(BOX)[:-7])  # a binary STL cut short
        with self.assertRaises(MeshFileError):
            read_stl(b"\x00\x01 not an stl at all")
        with self.assertRaises(MeshFileError):
            read_stl(binary_stl(BOX[:0]))


class ThreeMf(unittest.TestCase):
    def test_a_box_in_millimetres(self) -> None:
        read = read_3mf(package(model(mesh_xml(BOX, "1"), '<item objectid="1"/>')))
        np.testing.assert_array_equal(read.triangles, BOX)
        self.assertEqual((read.kind, read.unit), ("3mf", "millimeter"))
        self.assertTrue(read.view(0.0).topology().sound)

    def test_units(self) -> None:
        for unit, scale in (
            ("inch", 25.4),
            ("micron", 0.001),
            ("centimeter", 10.0),
            ("meter", 1000.0),
        ):
            read = read_mesh_file(
                package(model(mesh_xml(BOX, "1"), '<item objectid="1"/>', unit=unit))
            )
            np.testing.assert_allclose(read.triangles, BOX * scale, rtol=1e-15)

    def test_transforms_and_components(self) -> None:
        resources = mesh_xml(BOX, "1") + (
            '<object id="2"><components>'
            '<component objectid="1" transform="1 0 0 0 1 0 0 0 1 100 0 0"/>'
            '<component objectid="1" transform="0 1 0 -1 0 0 0 0 1 0 0 50"/>'
            "</components></object>"
        )
        read = read_3mf(
            package(
                model(
                    resources,
                    '<item objectid="2" transform="1 0 0 0 1 0 0 0 1 0 0 5"/>',
                )
            )
        )
        first, second = read.triangles[:12], read.triangles[12:]
        np.testing.assert_allclose(first, BOX + np.array([100.0, 0.0, 5.0]))
        turned = BOX @ np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1.0]]) + np.array(
            [0.0, 0.0, 55.0]
        )
        np.testing.assert_allclose(second, turned)
        t = read.view(0.0).topology()
        self.assertTrue(t.sound)
        self.assertEqual(t.solids, 2)

    def test_a_mirrored_component_still_faces_outwards(self) -> None:
        resources = mesh_xml(BOX, "1") + (
            '<object id="2"><components><component objectid="1" transform="-1 0 0 0 1 0 0 0 1 0 0 0"/>'
            "</components></object>"
        )
        read = read_3mf(package(model(resources, '<item objectid="2"/>')))
        v = read.view(0.0)
        self.assertTrue(v.topology().sound)
        self.assertTrue(v.volume().contains(6000.0))

    def test_refused(self) -> None:
        box = mesh_xml(BOX, "1")
        bad = {
            "two objects": package(
                model(
                    box + mesh_xml(BOX + 50, "2"),
                    '<item objectid="1"/><item objectid="2"/>',
                )
            ),
            "a support": package(
                model(mesh_xml(BOX, "1", kind="support"), '<item objectid="1"/>')
            ),
            "an unknown unit": package(
                model(box, '<item objectid="1"/>', unit="furlong")
            ),
            "a flattening transform": package(
                model(box, '<item objectid="1" transform="1 0 0 0 1 0 0 0 0 0 0 0"/>')
            ),
            "a missing object": package(model(box, '<item objectid="9"/>')),
            "a component cycle": package(
                model(
                    '<object id="1"><components><component objectid="2"/></components></object>'
                    '<object id="2"><components><component objectid="1"/></components></object>',
                    '<item objectid="1"/>',
                )
            ),
            "a component in another part": package(
                model(
                    box + '<object id="2"><components><component objectid="1" '
                    'p:path="/3D/other.model"/></components></object>',
                    '<item objectid="2"/>',
                    extra='xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"',
                )
            ),
            "a required beam lattice": package(
                model(
                    box,
                    '<item objectid="1"/>',
                    extra='xmlns:b="http://schemas.microsoft.com/3dmanufacturing/beamlattice/2017/02" '
                    'requiredextensions="b"',
                )
            ),
            "a document type": package(
                model(box, '<item objectid="1"/>').replace(
                    "<model", '<!DOCTYPE model [<!ENTITY x "y">]><model'
                )
            ),
            "no start part": package(
                model(box, '<item objectid="1"/>'),
                rels=RELS.replace('3dmodel"/>', 'other"/>'),
            ),
            "a vertex that isn't there": package(
                model(box.replace('v3="2"', 'v3="999"'), '<item objectid="1"/>')
            ),
            "not a zip": b"PK\x03\x04 broken",
        }
        for why, data in bad.items():
            with self.assertRaises(MeshFileError, msg=why):
                read_mesh_file(data)

    def test_harmless_extensions_are_read(self) -> None:
        extra = (
            'xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02" '
            'requiredextensions="m"'
        )
        read = read_3mf(
            package(model(mesh_xml(BOX, "1"), '<item objectid="1"/>', extra=extra))
        )
        self.assertEqual(len(read.triangles), 12)


if __name__ == "__main__":
    unittest.main()
