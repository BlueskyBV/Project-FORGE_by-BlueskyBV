"""The one dispatch mechanism (forge_registry; V2-stage4b-0b.md, 3): total by construction, in its keys' order."""

from __future__ import annotations

import unittest

from forge_registry import NotYetError, Registry, RegistryError, reserved


class _Shape:
    key = ""

    def area(self) -> float:
        raise NotImplementedError

    @reserved("4b.0d")
    def roles(self) -> tuple[str, ...]:
        return ()


class _Square(_Shape):
    key = "square"

    def area(self) -> float:
        return 4.0


class _Disc(_Shape):
    key = "disc"

    def area(self) -> float:
        return 3.0

    def roles(self) -> tuple[str, ...]:
        return ("rim",)


class ARegistry(unittest.TestCase):
    def test_entries_come_in_the_keys_order_not_the_order_given(self) -> None:
        shapes = Registry("shapes", ["square", "disc"], [_Disc(), _Square()])
        self.assertEqual(shapes.keys(), ("square", "disc"))
        self.assertEqual([type(e) for e in shapes.values()], [_Square, _Disc])
        self.assertEqual(list(shapes), ["square", "disc"])
        self.assertEqual(len(shapes), 2)
        self.assertEqual([k for k, _ in shapes.items()], ["square", "disc"])

    def test_a_key_finds_its_entry_and_an_unknown_one_is_refused_by_name(self) -> None:
        shapes = Registry("shapes", ["square"], [_Square()])
        self.assertEqual(shapes["square"].area(), 4.0)
        self.assertIn("square", shapes)
        self.assertNotIn("disc", shapes)
        self.assertIsNone(shapes.get("disc"))
        with self.assertRaises(RegistryError) as raised:
            shapes["disc"]
        self.assertEqual(
            str(raised.exception), "the shapes registry has no entry for 'disc'"
        )
        self.assertIsInstance(raised.exception, KeyError)

    def test_it_is_total_by_construction(self) -> None:
        with self.assertRaisesRegex(RegistryError, r"no entry for \['disc'\]"):
            Registry("shapes", ["square", "disc"], [_Square()])
        with self.assertRaisesRegex(RegistryError, r"entries for no key \['disc'\]"):
            Registry("shapes", ["square"], [_Square(), _Disc()])
        with self.assertRaisesRegex(RegistryError, "two entries for 'square'"):
            Registry("shapes", ["square"], [_Square(), _Square()])
        with self.assertRaisesRegex(RegistryError, r"keys repeat: \['square'\]"):
            Registry("shapes", ["square", "square"], [_Square()])
        with self.assertRaisesRegex(RegistryError, "names no key"):
            Registry("shapes", ["square"], [_Shape()])

    def test_an_entry_is_of_its_protocol(self) -> None:
        Registry("shapes", ["square"], [_Square()], protocol=_Shape)
        with self.assertRaisesRegex(
            RegistryError, r"entries for \['square'\] aren't _Discs"
        ):
            Registry("shapes", ["square"], [_Square()], protocol=_Disc)

    def test_entries_may_be_given_by_key(self) -> None:
        shapes = Registry(
            "shapes", ["disc", "square"], {"square": _Square(), "disc": _Disc()}
        )
        self.assertEqual(shapes.keys(), ("disc", "square"))

    def test_a_reserved_method_is_named_owned_and_refused_until_filled(self) -> None:
        shapes = Registry("shapes", ["square", "disc"], [_Square(), _Disc()])
        self.assertEqual(shapes.reserved(), [("square", "roles", "4b.0d")])
        with self.assertRaisesRegex(
            NotYetError, r"_Square.roles is reserved, not yet filled: 4b.0d"
        ):
            shapes["square"].roles()
        self.assertEqual(shapes["disc"].roles(), ("rim",))


if __name__ == "__main__":
    unittest.main()
