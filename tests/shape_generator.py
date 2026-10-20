"""Correct parts made at random -- plates, discs, bent strips, open boxes,
collars, L-brackets, counterbored plates, tubes -- each with a brief phrased
one of several ways a person writes one, and the requirements a careful
record would carry. Every one is a right answer: Forge must pass it.

Used by `test_shape_zoo`; run directly, it designs and checks a range of
seeds and prints every one held back.
"""
import json
import random
import sys
import time

NO_LOAD = " It carries no load, so there is no load case."


def mm(v): return {"magnitude": v, "unit": "mm"}
def ex(e): return {"expression": e, "unit": "mm"}
def vec(*c): return {"vector": list(c), "unit": "mm"}
def P(name, value, unit="mm"): return {"id": name, "value": {"magnitude": value, "unit": unit}}
def R(ident, measurement, comparison, magnitude, unit="mm"):
    return {"id": ident, "statement": ident, "measurement": measurement,
            "comparison": comparison, "threshold": {"magnitude": magnitude, "unit": unit}}


def g(x):
    return f"{x:g}"


def make(rnd):
    material = rnd.choice(["steel", "aluminium", "PLA", "stainless steel", "6061 aluminium",
                           "3D-printed PLA", "CNC-machined aluminium", "laser-cut steel",
                           "mild steel", "6061-T6 aluminium", "PLA (FDM printed)"])
    shape = rnd.choice(SHAPES)
    if shape in MORE:
        return MORE[shape](rnd, material)
    params, feats, reqs, words = [], [], [], []
    last = None

    def hole_feature(ident, x, y, d_expr, extra=None):
        nonlocal last
        f = {"id": ident, "kind": "hole", "inputs": [last], "parameters": {
            "diameter": ex(d_expr), "position": vec(x, y, 0), "axis": [0, 0, 1]}}
        if extra:
            f["parameters"].update(extra)
        feats.append(f)
        last = ident

    if shape in ("plate", "strip"):
        if shape == "plate":
            L = rnd.choice([40, 60, 80, 100, 120, 150, 200, 300, 500, 800])
            W = rnd.choice([w for w in [30, 40, 50, 60, 80, 100, 150, 200, 400] if w <= L])
            T = rnd.choice([2, 3, 4, 5, 6, 8, 10, 12])
        else:
            L = rnd.choice([60, 80, 100, 120, 150])
            W = rnd.choice([20, 25, 30, 40])
            T = rnd.choice([2, 3, 4])
        params += [P("length", L), P("width", W), P("thickness", T)]
        box = {"id": "plate", "kind": "box", "parameters": {
            "size": {"vector": ["length", "width", "thickness"], "unit": "mm"},
            "centered": True, "origin": vec(0, 0, "thickness / 2")}}
        if shape == "plate" and rnd.random() < 0.35:
            r = rnd.choice([2, 3, 5, 8])
            if r < min(L, W) / 4:
                params.append(P("corner_radius", r))
                box["parameters"]["edges"] = "vertical"
                box["parameters"]["edge_radius"] = ex("corner_radius")
                words.append(rnd.choice([f"corners rounded to {r} mm",
                                         f"{r} mm radius corners",
                                         f"its corners rounded with a {r} mm radius"]))
        feats.append(box)
        last = "plate"
        size_said = rnd.choice([
            f"{g(L)} x {g(W)} x {g(T)} mm",
            f"{g(L)} mm long, {g(W)} mm wide and {g(T)} mm thick",
            f"{g(L)} by {g(W)} mm, {g(T)} mm thick",
            f"{g(T)} mm thick, {g(L)} mm long and {g(W)} mm wide",
        ])
        if shape == "plate":
            reqs.append(R("REQ_LENGTH", "bounding_box_x", "equals", L))
        noun = "strip" if shape == "strip" else rnd.choice(["plate", "mounting plate", "base plate", "bracket plate"])
        brief = f"A {material} {noun} {size_said}"
        if shape == "plate":
            kind = rnd.choice(["corners", "centre", "centreline", "slot", "boss", "corners+centre", "none"])
            if kind in ("corners", "corners+centre"):
                d = rnd.choice([3, 4, 5, 6, 8])
                e = rnd.choice([x for x in [5, 6, 8, 10, 12, 15, 20] if x < min(L, W) / 3 and x > d])
                if True:
                    params += [P("hole", d), P("inset", e)]
                    for i, (sx, sy) in enumerate([(-1, -1), (1, -1), (1, 1), (-1, 1)]):
                        hole_feature(f"h{i+1}", f"{'-' if sx < 0 else ''}(length / 2 - inset)",
                                     f"{'-' if sy < 0 else ''}(width / 2 - inset)", "hole")
                    words.append(rnd.choice([
                        f"four {d} mm holes, one in each corner, {e} mm in from each edge",
                        f"a {d} mm hole in each corner, centred {e} mm from both edges",
                        f"four {d} mm mounting holes {e} mm from the edges at the corners",
                        f"4 x {d} mm holes at the corners, {e} mm in from the sides",
                        f"four \u00d8{d} mm holes, one in each corner, {e} mm in from each edge",
                        f"four {d}-mm holes, one in each corner, {e}mm from the edges",
                        f"a {d}mm hole in each corner, {e} mm in from both edges",
                    ]))
                    reqs.append(R("REQ_HOLES", f"holes_of_diameter:{d}", "equals", 4, ""))
            if kind in ("centre", "corners+centre"):
                d2 = rnd.choice([x for x in [6, 8, 10, 12, 16, 20, 25, 30] if x < W / 2.5
                                 and x != dict((p["id"], p["value"]["magnitude"]) for p in params).get("hole")])
                params.append(P("centre_hole", d2))
                hole_feature("bore", 0, 0, "centre_hole")
                words.append(rnd.choice([
                    f"a {d2} mm hole in the centre",
                    f"a {d2} mm hole through the middle",
                    f"a central {d2} mm hole",
                    f"one {d2} mm hole at the centre of the plate",
                    f"a \u00d8{d2} mm hole in the middle",
                    f"a {d2}-mm hole in the centre",
                ]))
                reqs.append(R("REQ_CENTRE", f"holes_of_diameter:{d2}", "equals", 1, ""))
            if kind == "centreline":
                d = rnd.choice([4, 5, 6, 8, 10])
                s = rnd.choice([x for x in [20, 30, 40, 50, 60, 80, 100] if x < L - 2 * d - 10])
                params += [P("hole", d), P("spacing", s)]
                hole_feature("h1", "-spacing / 2", 0, "hole")
                hole_feature("h2", "spacing / 2", 0, "hole")
                words.append(rnd.choice([
                    f"two {d} mm holes on the centreline, {s} mm apart",
                    f"two {d} mm holes {s} mm apart along its length, centred",
                    f"a pair of {d} mm holes at {s} mm centres on the long centreline",
                ]))
                reqs.append(R("REQ_HOLES", f"holes_of_diameter:{d}", "equals", 2, ""))
            if kind == "slot":
                sl = rnd.choice([x for x in [20, 30, 40, 50] if x < L / 2])
                sw = rnd.choice([x for x in [5, 6, 8, 10] if x < W / 3 and x < sl / 2])
                params += [P("slot_length", sl), P("slot_width", sw)]
                feats.append({"id": "slot_tool", "kind": "box", "parameters": {
                    "size": {"vector": ["slot_length", "slot_width", "thickness + 2"], "unit": "mm"},
                    "centered": True, "origin": vec(0, 0, "thickness / 2"),
                    "edges": "vertical", "edge_radius": ex("slot_width / 2")}})
                feats.append({"id": "slotted", "kind": "subtract", "inputs": [last, "slot_tool"]})
                last = "slotted"
                words.append(rnd.choice([
                    f"a {sl} x {sw} mm slot in the middle",
                    f"a {sl} mm long, {sw} mm wide slot through its centre",
                    f"one {sl} by {sw} mm slot, centred",
                ]))
                reqs.append(R("REQ_SLOT", f"openings_of_size:{sl}x{sw}", "equals", 1, ""))
            if kind == "boss":
                bd = rnd.choice([x for x in [10, 12, 16, 20, 25, 30] if x < W / 2])
                bh = rnd.choice([4, 6, 8, 10, 15])
                params += [P("boss_diameter", bd), P("boss_height", bh)]
                feats.append({"id": "boss", "kind": "cylinder", "parameters": {
                    "diameter": ex("boss_diameter"), "height": ex("boss_height"),
                    "origin": vec(0, 0, "thickness")}})
                feats.append({"id": "body", "kind": "union", "inputs": [last, "boss"]})
                last = "body"
                words.append(rnd.choice([
                    f"a {bd} mm boss standing {bh} mm proud in the centre",
                    f"a round boss {bd} mm across and {bh} mm tall on top, in the middle",
                    f"a central boss, {bd} mm in diameter, rising {bh} mm above the top face",
                ]))
                if rnd.random() < 0.5:
                    bore = rnd.choice([x for x in [4, 5, 6, 8] if x < bd / 2])
                    params.append(P("bore", bore))
                    hole_feature("bore_hole", 0, 0, "bore")
                    words.append(rnd.choice([
                        f"a {bore} mm bore through the boss and the plate",
                        f"a {bore} mm hole right through the boss",
                    ]))
        else:  # strip, bent
            angle = rnd.choice([30, 45, 60, 90, 120])
            params.append(P("angle", angle, "deg"))
            where = rnd.choice(["middle", "end"])
            d = rnd.choice([4, 5, 6])
            e = rnd.choice([x for x in [8, 10, 12, 15] if x < L / 4])
            params += [P("hole", d), P("hole_from_end", e)]
            hole_feature("h1", "-length / 2 + hole_from_end", 0, "hole")
            hole_feature("h2", "length / 2 - hole_from_end", 0, "hole")
            if where == "middle":
                pos = 0
                bend_words = rnd.choice([f"bent {angle}\u00b0 in the middle",
                                         f"bent {angle} degrees in the middle",
                                         f"with a {angle} degree bend halfway along",
                                         f"folded {angle} degrees at its centre"])
            else:
                f_end = rnd.choice([x for x in [25, 30, 40] if x < L / 2 - 5])
                params.append(P("bend_from_end", f_end))
                pos = "-length / 2 + bend_from_end"
                bend_words = rnd.choice([f"bent {angle} degrees {f_end} mm from one end",
                                         f"with a {angle} degree bend {f_end} mm from one end"])
            feats.append({"id": "bent", "kind": "bend", "inputs": [last], "parameters": {
                "angle": {"expression": "angle", "unit": "deg"},
                "position": vec(pos, 0, "thickness / 2"),
                "along": [1, 0, 0], "toward": [0, 0, 1]}})
            last = "bent"
            hole_words = rnd.choice([f"a {d} mm hole {e} mm from each end",
                                     f"two {d} mm holes, one {e} mm from each end",
                                     f"{d} mm holes {e} mm in from both ends"])
            order = rnd.random() < 0.5
            words += [bend_words, hole_words] if order else [hole_words, bend_words]
            reqs.append(R("REQ_ANGLE", "bend_angle", "equals", angle, "deg"))
    else:  # disc
        D = rnd.choice([40, 50, 60, 80, 100, 120, 160, 200])
        T = rnd.choice([3, 4, 5, 6, 8, 10, 15])
        params += [P("diameter", D), P("thickness", T)]
        feats.append({"id": "disc", "kind": "cylinder", "parameters": {
            "diameter": ex("diameter"), "height": ex("thickness"), "origin": vec(0, 0, 0)}})
        last = "disc"
        reqs.append(R("REQ_DIAMETER", "bounding_box_x", "equals", D))
        brief = f"A {material} " + rnd.choice([f"disc {D} mm in diameter and {T} mm thick",
                                               f"flange {D} mm across, {T} mm thick",
                                               f"round plate, {D} mm diameter, {T} mm thick"])
        n = rnd.choice([3, 4, 6, 8])
        d = rnd.choice([4, 5, 6, 8])
        C = rnd.choice([c for c in [0.5 * D, 0.6 * D, 0.7 * D, 0.75 * D] if c + d + 4 < D and c > d * 3])
        C = round(C)
        params += [P("hole", d), P("bolt_circle", C)]
        feats.append({"id": "h1", "kind": "hole", "inputs": [last], "parameters": {
            "diameter": ex("hole"), "position": vec("bolt_circle / 2", 0, 0), "axis": [0, 0, 1]}})
        feats.append({"id": "holes", "kind": "pattern_circular", "inputs": ["h1"], "parameters": {
            "count": {"magnitude": n, "unit": ""}, "axis_origin": vec(0, 0, 0),
            "axis_direction": [0, 0, 1]}})
        params.append(P("count", n, ""))
        last = "holes"
        words.append(rnd.choice([
            f"{n} {d} mm holes equally spaced on a {C} mm bolt circle",
            f"{n} x {d} mm holes on a {C} mm PCD",
            f"{n} holes of {d} mm diameter evenly spaced on a {C} mm circle",
        ]))
        reqs.append(R("REQ_HOLES", f"holes_of_diameter:{d}", "equals", n, ""))
        if rnd.random() < 0.5:
            d2 = rnd.choice([x for x in [10, 12, 16, 20] if x < C - d - 4])
            params.append(P("centre_hole", d2))
            feats.append({"id": "bore", "kind": "hole", "inputs": [last], "parameters": {
                "diameter": ex("centre_hole"), "position": vec(0, 0, 0), "axis": [0, 0, 1]}})
            last = "bore"
            words.append(rnd.choice([f"a {d2} mm hole in the centre", f"a central {d2} mm bore"]))
    if words:
        joiner = rnd.choice(["with", "having"])
        if len(words) == 1:
            brief += f", {joiner} " + words[0] + "."
        else:
            style = rnd.random()
            if style < 0.5:
                brief += f", {joiner} " + ", ".join(words[:-1]) + " and " + words[-1] + "."
            else:
                brief += ". It has " + words[0] + ". " + " ".join(
                    w[0].upper() + w[1:] + "." for w in words[1:])
    else:
        brief += "."
    have = {r["measurement"] for r in reqs}
    for p in params:
        v = p.get("value") or {}
        if v.get("unit") in ("mm", "deg") and f"parameter:{p['id']}" not in have:
            reqs.append(R("REQ_P_" + p["id"].upper(), f"parameter:{p['id']}", "equals",
                          v["magnitude"], v["unit"]))
    component = {"id": "part", "parameters": params, "features": feats}
    return {"brief": brief + NO_LOAD,
            "intent": {"summary": brief, "part_kind": shape, "stated": [], "implied": [], "unstated": []},
            "requirements": {"risk_class": "low", "requirements": reqs, "assumptions": [], "unknowns": []},
            "answer": {"rationale": "", "document": {"name": "zoo3", "components": [component]}}}


def _finish(rnd, brief, params, feats, reqs, kind):
    have = {r["measurement"] for r in reqs}
    for p in params:
        v = p.get("value") or {}
        if v.get("unit") in ("mm", "deg") and f"parameter:{p['id']}" not in have:
            reqs.append(R("REQ_P_" + p["id"].upper(), f"parameter:{p['id']}", "equals",
                          v["magnitude"], v["unit"]))
    component = {"id": "part", "parameters": params, "features": feats}
    return {"brief": brief + NO_LOAD,
            "intent": {"summary": brief, "part_kind": kind, "stated": [], "implied": [], "unstated": []},
            "requirements": {"risk_class": "low", "requirements": reqs, "assumptions": [], "unknowns": []},
            "answer": {"rationale": "", "document": {"name": "zoo3", "components": [component]}}}


def make_box(rnd, material):
    L = rnd.choice([40, 60, 80, 100, 120, 200])
    W = rnd.choice([w for w in [30, 40, 50, 60, 80, 100] if w <= L])
    H = rnd.choice([15, 20, 25, 30, 40, 60])
    t = rnd.choice([1.5, 2, 2.5, 3])
    params = [P("length", L), P("width", W), P("height", H), P("wall", t)]
    feats = [{"id": "outer", "kind": "box", "parameters": {
                 "size": {"vector": ["length", "width", "height"], "unit": "mm"},
                 "centered": True, "origin": vec(0, 0, "height / 2")}},
             {"id": "inner", "kind": "box", "parameters": {
                 "size": {"vector": ["length - 2 * wall", "width - 2 * wall", "height"], "unit": "mm"},
                 "centered": True, "origin": vec(0, 0, "wall + height / 2")}},
             {"id": "box", "kind": "subtract", "inputs": ["outer", "inner"]}]
    reqs = [R("REQ_X", "bounding_box_x", "equals", L)]
    noun = rnd.choice(["box", "tray", "open box", "container"])
    brief = f"A {material} {noun} " + rnd.choice([
        f"{L} x {W} x {H} mm, open at the top, with {t:g} mm walls and floor",
        f"{L} mm long, {W} mm wide and {H} mm tall, open-topped, walls and floor {t:g} mm thick",
        f"{L} by {W} mm and {H} mm deep overall, open on top, with {t:g} mm thick walls and a {t:g} mm floor",
    ])
    if rnd.random() < 0.4:
        d = rnd.choice([3, 4, 5, 6, 8])
        params.append(P("drain", d))
        feats.append({"id": "drain_hole", "kind": "hole", "inputs": ["box"], "parameters": {
            "diameter": ex("drain"), "position": vec(0, 0, "wall / 2"), "axis": [0, 0, 1]}})
        brief += rnd.choice([f", with a {d} mm drain hole in the middle of the floor",
                             f" and a {d} mm hole through the centre of its floor"])
    return _finish(rnd, brief + ".", params, feats, reqs, "box")


def make_collar(rnd, material):
    D = rnd.choice([16, 20, 25, 30, 40])
    d = rnd.choice([x for x in [6, 8, 10, 12, 15, 20] if x < D - 6])
    Lc = rnd.choice([8, 10, 12, 15, 20])
    params = [P("outer", D), P("bore", d), P("length", Lc)]
    feats = [{"id": "body", "kind": "cylinder", "parameters": {
                 "diameter": ex("outer"), "height": ex("length"), "origin": vec(0, 0, 0)}},
             {"id": "bore_hole", "kind": "hole", "inputs": ["body"], "parameters": {
                 "diameter": ex("bore"), "position": vec(0, 0, "length / 2"), "axis": [0, 0, 1]}}]
    reqs = [R("REQ_OD", "bounding_box_x", "equals", D), R("REQ_LEN", "bounding_box_z", "equals", Lc)]
    noun = rnd.choice(["shaft collar", "collar", "spacer ring", "bushing"])
    brief = f"A {material} {noun} " + rnd.choice([
        f"{D} mm outside diameter, {d} mm bore, {Lc} mm long",
        f"{D} mm across with a {d} mm bore through it, {Lc} mm long",
        f"{Lc} mm long, {D} mm OD and {d} mm ID",
    ])
    if rnd.random() < 0.5 and noun in ("shaft collar", "collar"):
        s = rnd.choice([3, 4, 5])
        params.append(P("screw", s))
        feats.append({"id": "set_screw", "kind": "hole", "inputs": ["bore_hole"], "parameters": {
            "diameter": ex("screw"), "position": vec(0, 0, "length / 2"), "axis": [1, 0, 0],
            "through": "first_wall"}})
        brief += rnd.choice([f", with one {s} mm set screw hole through the wall into the bore",
                             f" and a single {s} mm radial set screw hole"])
    return _finish(rnd, brief + ".", params, feats, reqs, "collar")


def make_lbracket(rnd, material):
    L = rnd.choice([40, 50, 60, 80, 100])
    W = rnd.choice([20, 25, 30, 40])
    H = rnd.choice([30, 40, 50, 60])
    T = rnd.choice([3, 4, 5, 6])
    d = rnd.choice([4, 5, 6])
    params = [P("base_length", L), P("width", W), P("height", H), P("thickness", T), P("hole", d)]
    feats = [{"id": "base", "kind": "box", "parameters": {
                 "size": {"vector": ["base_length", "width", "thickness"], "unit": "mm"},
                 "centered": True, "origin": vec(0, 0, "thickness / 2")}},
             {"id": "upright", "kind": "box", "parameters": {
                 "size": {"vector": ["thickness", "width", "height"], "unit": "mm"},
                 "centered": True, "origin": vec("-(base_length - thickness) / 2", 0, "height / 2")}},
             {"id": "body", "kind": "union", "inputs": ["base", "upright"]},
             {"id": "h_base", "kind": "hole", "inputs": ["body"], "parameters": {
                 "diameter": ex("hole"), "position": vec("base_length / 4", 0, 0), "axis": [0, 0, 1]}},
             {"id": "h_up", "kind": "hole", "inputs": ["h_base"], "parameters": {
                 "diameter": ex("hole"), "position": vec("-(base_length - thickness) / 2", 0, "height * 0.6"),
                 "axis": [1, 0, 0]}}]
    reqs = [R("REQ_HOLES", f"holes_of_diameter:{d}", "equals", 2, ""),
            R("REQ_Z", "bounding_box_z", "equals", H)]
    brief = f"A {material} " + rnd.choice([
        f"L-bracket: a base {L} x {W} x {T} mm and an upright {H} mm tall at one end, the same width and thickness, with one {d} mm hole in each leg",
        f"angle bracket with a {L} mm base and a {H} mm tall upright, {W} mm wide and {T} mm thick, a {d} mm hole through each leg",
    ])
    return _finish(rnd, brief + ".", params, feats, reqs, "bracket")


def make_counterbored(rnd, material):
    L = rnd.choice([60, 80, 100, 120])
    W = rnd.choice([40, 60, 80])
    T = rnd.choice([8, 10, 12])
    d, cd, cdep = rnd.choice([(5.5, 10, 5), (6.6, 11, 6), (4.5, 8, 4), (9, 15, 8)])
    if cdep >= T - 1:
        cdep = T - 3
    e = rnd.choice([x for x in [10, 12, 15] if W - 2 * x >= cd + 2 and x > cd / 2 + 1])
    params = [P("length", L), P("width", W), P("thickness", T), P("hole", d), P("cb", cd),
              P("cb_depth", cdep), P("inset", e)]
    feats = [{"id": "plate", "kind": "box", "parameters": {
        "size": {"vector": ["length", "width", "thickness"], "unit": "mm"},
        "centered": True, "origin": vec(0, 0, "thickness / 2")}}]
    last = "plate"
    for i, (sx, sy) in enumerate([(-1, -1), (1, -1), (1, 1), (-1, 1)]):
        feats.append({"id": f"h{i+1}", "kind": "hole", "inputs": [last], "parameters": {
            "diameter": ex("hole"),
            "position": vec(f"{'-' if sx < 0 else ''}(length / 2 - inset)",
                            f"{'-' if sy < 0 else ''}(width / 2 - inset)", "thickness / 2"),
            "axis": [0, 0, -1], "counterbore_diameter": ex("cb"), "counterbore_depth": ex("cb_depth")}})
        last = f"h{i+1}"
    reqs = [R("REQ_X", "bounding_box_x", "equals", L),
            R("REQ_HOLES", f"holes_of_diameter:{d:g}", "equals", 4, "")]
    brief = f"A {material} plate {L} x {W} x {T} mm with " + rnd.choice([
        f"four {d:g} mm holes, {e} mm in from each edge at the corners, counterbored {cd} mm diameter and {cdep} mm deep from the top",
        f"a {d:g} mm hole in each corner, {e} mm from both edges, each counterbored to {cd} mm, {cdep} mm deep, on the top face",
    ])
    return _finish(rnd, brief + ".", params, feats, reqs, "plate")


def make_tube(rnd, material):
    D = rnd.choice([20, 25, 30, 40, 50])
    t = rnd.choice([1.5, 2, 3])
    Lt = rnd.choice([50, 80, 100, 150])
    params = [P("outer", D), P("wall", t), P("length", Lt)]
    feats = [{"id": "outer_cyl", "kind": "cylinder", "parameters": {
                 "diameter": ex("outer"), "height": ex("length"), "origin": vec(0, 0, 0)}},
             {"id": "bore", "kind": "hole", "inputs": ["outer_cyl"], "parameters": {
                 "diameter": ex("outer - 2 * wall"), "position": vec(0, 0, "length / 2"), "axis": [0, 0, 1]}}]
    reqs = [R("REQ_OD", "bounding_box_x", "equals", D), R("REQ_L", "bounding_box_z", "equals", Lt)]
    brief = f"A {material} " + rnd.choice([
        f"tube {D} mm outside diameter with a {t:g} mm wall, {Lt} mm long",
        f"pipe {Lt} mm long, {D} mm OD, wall {t:g} mm thick",
        f"round tube, {D} mm across, {t:g} mm wall thickness, {Lt} mm long",
    ])
    return _finish(rnd, brief + ".", params, feats, reqs, "tube")


MORE = {"box": make_box, "collar": make_collar, "lbracket": make_lbracket,
        "counterbored": make_counterbored, "tube": make_tube}
SHAPES = ["plate", "plate", "plate", "disc", "strip", "box", "collar", "lbracket",
          "counterbored", "tube"]


def a_case(seed: int) -> dict:
    """The part made from `seed`: the same part every time."""
    rnd = random.Random(seed)
    for _ in range(50):
        try:
            return make(rnd)
        except IndexError:
            continue
    raise RuntimeError(f"no part could be made from seed {seed}")


if __name__ == "__main__":
    from test_real_answers import _design
    from forge_pipeline import verify_component
    seed0, count = int(sys.argv[1]), int(sys.argv[2])
    bad = 0
    for seed in range(seed0, seed0 + count):
        rnd = random.Random(seed)
        for _ in range(50):
            try:
                case = make(rnd)
                break
            except IndexError:
                continue
        t = time.time()
        try:
            draft = _design(case)
            rep = verify_component(draft.document, draft.document.components[0], measurement_depth=8)
            held = {r.gate.identifier: r.status.value for r in rep.gate_results
                    if (r.status.value in ("FAIL", "BLOCKED") and r.gate.critical)
                    or (r.status.value == "NOT_TESTED" and r.gate.identifier.startswith("REQ_"))}
        except Exception as error:
            held = {"ERROR": f"{type(error).__name__}: {str(error)[:300]} {getattr(error, 'problems', '')}"}
            rep = None
        dt = time.time() - t
        if held:
            bad += 1
            print(f"seed {seed} {dt:.1f}s HELD {held}\n   {case['brief']}", flush=True)
            if rep is not None:
                for r in rep.gate_results:
                    if r.gate.identifier in held:
                        print("     ", r.gate.identifier, str(r.evidence.result), json.dumps(r.evidence.detail, default=str)[:400], flush=True)
        else:
            print(f"seed {seed} {dt:.1f}s ok", flush=True)
    print("DONE bad", bad, "of", count)
