# Forge V1 validation suite

92 tests. Each is graded automatically against the built part's real measurements (envelope, volume, open holes, every check) by `check-suite.py`.

What each expectation means:

- **pass**: COMPLETED, every check PASS, shape matches
- **held**: BLOCKED only by assumptions you approve (load, grade); every check PASS, shape matches
- **pass_or_held**: either of the above
- **honest**: must NOT come back COMPLETED
- **honest_fail**: must report the named check as FAIL, never PASS
- **inspect**: you and I look at it

How to run:

```
cd <your forge folder>
.\validation\run-suite.ps1 -Tier R        # start with the regression tier
.\validation\run-suite.ps1                # everything not yet run (resumable)
.\validation\run-suite.ps1 -Claude -Tier R  # the same on Claude (ANTHROPIC_API_KEY set)
python validation\check-suite.py          # grade whatever has run so far
```

## R — Regression: the prompts that built V1

**R01 — Oblong spacer block (plan 1)** · expect `pass`
> A 3D-printed PLA spacer block. The base is a 40 mm by 25 mm plate 5 mm thick. A 10 mm diameter post 8 mm tall stands in the middle of it, with a 1.5 mm fillet where the post meets the plate. A 4 mm hole runs all the way through the post and the plate. Two 3 mm mounting holes pass all the way through the plate, 30 mm apart. It must weigh no more than 10 g. It carries no load - it is a printed spacer, so there is no load case.
Expected: envelope [13, 25, 40], volume 5300–5550 mm³, open holes 3.

**R02 — Stainless collar, one set screw (plan 2)** · expect `pass`
> A stainless steel shaft collar. The outer diameter is 30 mm and it is 12 mm long. A 16 mm bore runs all the way through on the axis. One 5 mm set screw hole passes through the wall from the outside into the bore, halfway along the length. It carries no load - it is a locating collar, so there is no load case.
Expected: envelope [12, 30, 30], volume 5850–6060 mm³, open holes 2.

**R03 — Flange disc, two bolt holes (plan 3)** · expect `pass`
> A steel flange disc 60 mm across and 8 mm thick. A 20 mm bore runs all the way through the centre. Two 6 mm bolt holes pass all the way through the disc, 40 mm apart. It carries no load, so there is no load case.
Expected: envelope [8, 60, 60], volume 19654 mm³, open holes 3.

**R04 — Washer (plan 4)** · expect `pass`
> A stainless steel washer. The outside diameter is 24 mm, it is 2 mm thick, and a 10.5 mm hole runs through the centre. It carries no load, so there is no load case.
Expected: envelope [2, 24, 24], volume 732 mm³, open holes 1.

**R05 — Four-hole mounting plate (plan 5)** · expect `pass`
> An aluminium mounting plate 70 mm long, 50 mm wide and 4 mm thick. Four 4 mm holes pass through the plate, one near each corner, with their centres on a 56 mm by 36 mm rectangle. It carries no load, so there is no load case.
Expected: envelope [4, 50, 70], volume 13799 mm³, open holes 4.

**R06 — Pipe flange, bolt circle (plan 6)** · expect `pass`
> A steel pipe flange. It is a disc 80 mm across and 10 mm thick, with a 30 mm bore through the centre. Four 8 mm bolt holes pass all the way through the disc, equally spaced on a 60 mm bolt circle. It carries no load, so there is no load case.
Expected: envelope [10, 80, 80], volume 41186 mm³, open holes 5.

**R07 — Pulley hub (plan 7)** · expect `pass`
> An aluminium pulley hub. A flange disc 50 mm across and 6 mm thick, with a round hub 25 mm across and 15 mm tall standing on top of it, centred. A 10 mm bore runs through both the flange and the hub. Three 5 mm holes pass through the flange only, equally spaced on a 38 mm circle. It carries no load, so there is no load case.
Expected: envelope [21, 50, 50], volume 17141 mm³, open holes 4.

**R08 — Open-top box (plan 8)** · expect `pass`
> A PLA open-top box, 60 mm long, 40 mm wide and 30 mm tall on the outside, with 2 mm walls and a 2 mm thick floor. The top is completely open. It carries no load, so there is no load case.
Expected: envelope [30, 40, 60], volume 15552 mm³, open holes 0.

**R09 — L-bracket (plan 9)** · expect `pass`
> A PLA L-bracket 40 mm wide, made of 5 mm thick plate. The base leg is 50 mm long and lies flat; the upright leg stands on the back end of the base and is 40 mm tall overall. Two 5 mm holes pass through the base, 20 mm apart across its width, centred 25 mm from the front end. Two 5 mm holes pass through the upright, 20 mm apart across its width, centred 25 mm above the bottom. It carries no load, so there is no load case.
Expected: envelope [40, 40, 50], volume 16607 mm³, open holes 4.

**R10 — Loaded cantilever (plan 10)** · expect `held`
> An aluminium cantilever bracket: a 60 mm long, 20 mm wide, 6 mm thick bar fixed at one end by two 5 mm bolt holes 15 mm apart near that end. A load of 150 N pushes straight down on the free end. It must have a safety factor of at least 2.
Expected: envelope [6, 20, 60], volume 6964 mm³, open holes 2.

**R11 — Square spacer block** · expect `pass`
> A 3D-printed PLA spacer block. The base is a 30 mm square plate 4 mm thick. A 12 mm diameter post 10 mm tall stands in the middle of it, with a 2 mm fillet where the post meets the plate. A 5 mm hole runs all the way through the post and the plate. Two 3 mm mounting holes pass all the way through the plate, 20 mm apart. It must weigh no more than 8 g. It carries no load - it is a printed spacer, so there is no load case.
Expected: envelope [14, 30, 30], volume 4330–4560 mm³, open holes 3.

**R12 — Aluminium collar, two set screws 90 deg apart** · expect `pass`
> A machined aluminium shaft collar. The outer diameter is 25 mm and it is 15 mm long. A 12 mm bore runs all the way through on the axis. Two 4 mm set screw holes pass through the wall from the outside into the bore, 90 degrees apart, both halfway along the length. It carries no load - it is a locating collar, so there is no load case.
Expected: envelope [15, 25, 25], volume 5400–5600 mm³, open holes 3.

**R13 — Motor mount plate** · expect `pass`
> A 3D-printed motor mount plate in PLA. The base plate is 60 mm long, 40 mm wide and 6 mm thick. A cylindrical boss 18 mm in diameter and 25 mm tall stands in the middle of the plate, with a 2 mm fillet where the boss meets the plate. An 8 mm shaft bore runs all the way through the boss and the plate, on the boss axis. Four 4.5 mm mounting holes pass all the way through the plate on a 44 mm by 24 mm rectangular pattern centred on the plate. The finished part must stand no taller than 32 mm and weigh no more than 30 g. It carries no structural load - it is a printed fixture, so there is no load case.
Expected: envelope [31, 40, 60], volume 18500–19300 mm³, open holes 5.

**R14 — Standoff on a square base** · expect `pass`
> A cylindrical standoff 30 mm tall and 25 mm across, sitting on a 50 mm square base plate 5 mm thick, with an 8 mm hole down the middle of the standoff, in 6061-T6 aluminium.
Expected: envelope [35, 50, 50], volume 25300–25850 mm³, open holes 1.

## P — Single shapes

**P01 — Cube** · expect `pass`
> A 30 mm cube in PLA. It carries no load, so there is no load case.
Expected: envelope [30, 30, 30], volume 27000 mm³, open holes 0.

**P02 — Rectangular block** · expect `pass`
> A steel block 80 mm long, 40 mm wide and 25 mm tall. It carries no load, so there is no load case.
Expected: envelope [25, 40, 80], volume 80000 mm³, open holes 0.

**P03 — Rod / cylinder** · expect `pass`
> An aluminium rod 12 mm in diameter and 100 mm long. It carries no load, so there is no load case.
Expected: envelope [12, 12, 100], volume 11310 mm³, open holes 0.

**P04 — Sphere** · expect `pass`
> A PLA sphere 40 mm in diameter. It carries no load, so there is no load case.
Expected: envelope [40, 40, 40], volume 33510 mm³, open holes 0.

**P05 — Thin disc** · expect `pass`
> A stainless steel disc 50 mm across and 3 mm thick. It carries no load, so there is no load case.
Expected: envelope [3, 50, 50], volume 5890 mm³, open holes 0.

**P06 — Hexagonal prism** · expect `pass`
> A PLA hexagonal prism, 20 mm across the corners and 30 mm tall. It carries no load, so there is no load case.
Expected: envelope [17.32, 20, 30], volume 7794 mm³, open holes 0. Envelope across the flats depends on which way the hexagon is turned; checked loosely.

**P07 — Dome (half sphere)** · expect `pass`
> A PLA dome: exactly half of a 50 mm sphere, sitting flat side down. It carries no load, so there is no load case.
Expected: envelope [25, 50, 50], volume 32725 mm³, open holes 0.

**P08 — Tube** · expect `pass`
> An aluminium tube with a 30 mm outside diameter and a 24 mm inside diameter, 80 mm long, open at both ends. It carries no load, so there is no load case.
Expected: envelope [30, 30, 80], volume 20358 mm³, open holes —.

**P09 — Rounded-corner tag with a hole** · expect `pass`
> A 3D-printed PLA tag 50 mm by 30 mm and 3 mm thick with 5 mm rounded corners and a 4 mm hole centred 6 mm from one short end. It carries no load, so there is no load case.
Expected: envelope [3, 30, 50], volume 4398 mm³, open holes 1.

**P10 — Obround plate** · expect `pass`
> A PLA obround plate: 60 mm long overall, 20 mm wide with fully rounded ends, 4 mm thick. It carries no load, so there is no load case.
Expected: envelope [4, 20, 60], volume 4457 mm³, open holes 0.

**P11 — Torus / ring** · expect `pass`
> A PLA ring shaped like a doughnut: an 8 mm round section bent into a full ring 40 mm across at the centre line of the section. It carries no load, so there is no load case.
Expected: envelope [8, 48, 48], volume 6317 mm³, open holes 0.

**P12 — Cylinder lying on its side** · expect `pass`
> A PLA roller 30 mm in diameter and 50 mm long, lying on its side with its axis along X. It carries no load, so there is no load case.
Expected: envelope [50, 30, 30], volume 35343 mm³, open holes 0.

**P13 — Square slab, very thin** · expect `pass`
> A PLA shim 40 mm square and 1 mm thick. It carries no load, so there is no load case.
Expected: envelope [1, 40, 40], volume 1600 mm³, open holes 0.

**P14 — Tall thin pin** · expect `pass`
> A steel pin 3 mm in diameter and 60 mm long. It carries no load, so there is no load case.
Expected: envelope [3, 3, 60], volume 424 mm³, open holes 0.

## H — Holes of every kind

**H01 — Row of five holes** · expect `pass`
> An aluminium strip 120 mm long, 25 mm wide and 5 mm thick, with five 6 mm holes in a row along its centre line, 20 mm apart, the row centred on the strip. It carries no load, so there is no load case.
Expected: envelope [5, 25, 120], volume 14293 mm³, open holes 5.

**H02 — 3 x 3 grid of holes** · expect `pass`
> A PLA perforated plate 60 mm square and 3 mm thick, with a 3 by 3 grid of 6 mm holes on 18 mm centres, centred on the plate. It carries no load, so there is no load case.
Expected: envelope [3, 60, 60], volume 10037 mm³, open holes 9.

**H03 — Counterbored holes** · expect `pass`
> A steel plate 60 mm long, 40 mm wide and 10 mm thick with two counterbored holes for M5 screws, 40 mm apart along the length: each a 5.5 mm through hole with a 10 mm counterbore 5 mm deep from the top face. It carries no load, so there is no load case.
Expected: envelope [10, 40, 60], volume 22977 mm³, open holes 2.

**H04 — Countersunk holes** · expect `pass`
> An aluminium plate 50 mm long, 30 mm wide and 6 mm thick with two 4.5 mm countersunk holes 30 mm apart along its length, each countersunk at 90 degrees to 9 mm across at the top face. It carries no load, so there is no load case.
Expected: envelope [6, 30, 50], volume 8714 mm³, open holes 2.

**H05 — Blind hole** · expect `pass`
> A 40 mm aluminium cube with a 10 mm hole drilled 25 mm deep into the middle of its top face. The hole does not go all the way through. It carries no load, so there is no load case.
Expected: envelope [40, 40, 40], volume 62037 mm³, open holes —.

**H06 — Horizontal hole** · expect `pass`
> A PLA block 50 mm long, 30 mm wide and 30 mm tall with an 8 mm hole drilled straight through it along its length, through the middle. It carries no load, so there is no load case.
Expected: envelope [30, 30, 50], volume 42487 mm³, open holes 1.

**H07 — Three crossing holes** · expect `pass`
> A 30 mm PLA cube with three 10 mm holes passing through its centre, one along each axis. It carries no load, so there is no load case.
Expected: envelope [30, 30, 30], volume 21346 mm³, open holes 3.

**H08 — Threaded hole (thread not modelled)** · expect `pass`
> A 20 mm steel cube with an M6 threaded hole straight through its centre, top to bottom. It carries no load, so there is no load case.
Expected: envelope [20, 20, 20], volume 7400–7700 mm³, open holes 1. Forge does not model threads: a plain 5 to 6 mm hole is the right answer; the report should not claim a thread.

**H09 — Holes of two sizes** · expect `pass`
> A PLA plate 80 mm by 40 mm and 4 mm thick with a 12 mm hole in its centre and two 4 mm holes 60 mm apart along its length. It carries no load, so there is no load case.
Expected: envelope [4, 40, 80], volume 12247 mm³, open holes 3.

**H10 — Six holes on a circle** · expect `pass`
> An aluminium disc 70 mm across and 6 mm thick with six 5 mm holes equally spaced on a 50 mm circle and no centre hole. It carries no load, so there is no load case.
Expected: envelope [6, 70, 70], volume 22384 mm³, open holes 6.

## C — Compositions: pieces joined together

**C01 — Plate with a post on top** · expect `pass`
> A PLA stand: a base plate 60 mm long, 40 mm wide and 6 mm thick, with a round post 20 mm across and 30 mm tall standing on top of it, centred. It carries no load, so there is no load case.
Expected: envelope [36, 40, 60], volume 23825 mm³, open holes 0.

**C02 — T-bar with a rib** · expect `pass`
> A PLA T-bar: a flat bar 80 mm long, 20 mm wide and 5 mm thick, with a 5 mm thick rib 30 mm tall standing along the middle of it for its full length. It carries no load, so there is no load case.
Expected: envelope [20, 35, 80], volume 20000 mm³, open holes 0.

**C03 — U-channel** · expect `pass`
> A steel U-channel 100 mm long. The base is 40 mm wide and 4 mm thick and lies flat; two side walls 4 mm thick stand along both long edges of the base and the channel is 30 mm tall overall. It carries no load, so there is no load case.
Expected: envelope [30, 40, 100], volume 36800 mm³, open holes 0.

**C04 — Stepped shaft** · expect `pass`
> An aluminium stepped shaft on one axis: a section 20 mm in diameter and 30 mm long, followed by a section 12 mm in diameter and 40 mm long. It carries no load, so there is no load case.
Expected: envelope [20, 20, 70], volume 13949 mm³, open holes 0.

**C05 — Pin with a ball on top** · expect `pass`
> A PLA pin: a 6 mm rod 50 mm long standing upright, with a 12 mm ball centred on its top end. It carries no load, so there is no load case.
Expected: envelope [12, 12, 56], volume 2160 mm³, open holes 0.

**C06 — Hydra: pole with arms** · expect `pass`
> A PLA hydra: a round base 40 mm across and 5 mm thick, with an upright pole 10 mm across and 80 mm tall standing on the middle of it. Six 4 mm rods, each 20 mm long, stick straight out sideways from the pole near its top, evenly spaced around it. It carries no load, so there is no load case.
Expected: envelope height 85 mm, volume 13600–14300 mm³, open holes 0. Whether the 20 mm is measured from the pole's surface or its axis is the brief's ambiguity; only the height and volume are checked. Inspect the STL.

**C07 — Jack: three crossing rods** · expect `pass`
> A PLA jack: three 6 mm rods, each 40 mm long, crossing at their centres, one along each axis. It carries no load, so there is no load case.
Expected: envelope [40, 40, 40], volume 3087 mm³, open holes 0.

**C08 — Sealed hollow cube** · expect `pass`
> A sealed hollow PLA cube 40 mm on the outside with 2 mm walls on every side, completely closed. It carries no load, so there is no load case.
Expected: envelope [40, 40, 40], volume 17344 mm³, open holes 0.

**C09 — Cup** · expect `pass`
> A PLA cup: 60 mm outside diameter and 80 mm tall, with 2 mm walls and a 3 mm floor, open at the top. It carries no load, so there is no load case.
Expected: envelope [60, 60, 80], volume 36543 mm³, open holes 0.

**C10 — Tray with a divider** · expect `pass`
> A PLA tray 100 mm long, 60 mm wide and 25 mm tall on the outside, with 2 mm walls and a 2 mm floor, open at the top, and one 2 mm thick divider wall across the middle splitting it into two equal compartments. It carries no load, so there is no load case.
Expected: envelope [25, 60, 100], volume 28928 mm³, open holes 0.

**C11 — Plate with two posts** · expect `pass`
> A PLA plate 80 mm long, 30 mm wide and 5 mm thick, with two round posts 10 mm across and 20 mm tall standing on it, 50 mm apart along its length and centred across its width. It carries no load, so there is no load case.
Expected: envelope [25, 30, 80], volume 15142 mm³, open holes 0.

**C12 — Disc with bumps on a circle** · expect `pass`
> An aluminium disc 80 mm across and 5 mm thick with eight 8 mm half-ball bumps on its top face, equally spaced on a 60 mm circle. It carries no load, so there is no load case.
Expected: envelope [9, 80, 80], volume 26205 mm³, open holes 0.

**C13 — Clevis with two ears** · expect `pass`
> A steel clevis: a block 40 mm long, 20 mm wide and 10 mm thick, with two ears 6 mm thick, 20 mm wide and 25 mm tall rising from its two ends, each with an 8 mm hole straight through it, centred 8 mm below its top. It carries no load, so there is no load case.
Expected: envelope [20, 35, 40], volume 13397 mm³, open holes 2.

**C14 — Cube with a ball half sunk on top** · expect `pass`
> A PLA ornament: a 30 mm cube with a 20 mm ball half sunk into the middle of its top face, so half the ball sticks up. It carries no load, so there is no load case.
Expected: envelope [30, 30, 40], volume 29094 mm³, open holes 0.

**C15 — Bar with a ball at each end** · expect `pass`
> A PLA dumbbell: a bar 50 mm long and 10 mm square, with a 16 mm ball centred on each end of it. It carries no load, so there is no load case.
Expected: envelope [16, 16, 66], volume 7922 mm³, open holes 0.

**C16 — Mounting bracket with a boss and four holes** · expect `pass`
> A machined aluminium mounting bracket. The base is a 60 mm by 40 mm plate 8 mm thick. A 20 mm diameter boss 15 mm tall rises from the middle, with a 3 mm fillet at its root. A 10 mm bore runs through the boss and the plate. Four 6 mm bolt holes pass through the plate, on a 44 mm by 24 mm rectangle. It carries no load, so there is no load case.
Expected: envelope [23, 40, 60], volume 21050–21650 mm³, open holes 5.

## A — Abstract shapes that resemble nothing

**A01 — Cube intersected with a sphere** · expect `pass`
> An abstract PLA shape: a 30 mm cube and a 36 mm sphere sharing the same centre, keeping only the volume they share. It carries no load, so there is no load case.
Expected: envelope [30, 30, 30], volume 21545 mm³, open holes 0.

**A02 — Cube with a spherical dent** · expect `pass`
> A 40 mm PLA cube with a 30 mm sphere cut out of it, the sphere centred on the middle of the top face. It carries no load, so there is no load case.
Expected: envelope [40, 40, 40], volume 56931 mm³, open holes 0.

**A03 — Three overlapping balls** · expect `pass`
> Three 20 mm PLA balls in a row, their centres 15 mm apart, fused into one piece. It carries no load, so there is no load case.
Expected: envelope [20, 20, 50], volume 11846 mm³, open holes 0.

**A04 — Tilted bar** · expect `pass`
> A PLA bar 40 mm long and 10 mm square, rotated 45 degrees about its 10 mm wide horizontal axis so it leans over. It carries no load, so there is no load case.
Expected: envelope [10, 35.36, 35.36], volume 4000 mm³, open holes 0. Leans in X or Y, either way; checked on the sorted envelope.

**A05 — Hollow ball** · expect `pass`
> A sealed hollow PLA ball 40 mm across with a 3 mm wall. It carries no load, so there is no load case.
Expected: envelope [40, 40, 40], volume 12931 mm³, open holes 0.

**A06 — Bead: ball with a hole** · expect `pass`
> A 40 mm PLA ball with a 10 mm hole drilled straight through its centre. It carries no load, so there is no load case.
Expected: envelope [40, 40, 40], volume 30418 mm³, open holes 1.

**A07 — Stacked discs, getting smaller** · expect `pass`
> A PLA tower of three discs stacked on top of each other, centred: the bottom one 40 mm across, the middle one 30 mm across and the top one 20 mm across, each 10 mm thick. It carries no load, so there is no load case.
Expected: envelope [30, 40, 40], volume 22777 mm³, open holes 0.

**A08 — Plus sign** · expect `pass`
> A flat PLA plus sign 5 mm thick: two bars 50 mm long and 10 mm wide crossing at their middles at right angles. It carries no load, so there is no load case.
Expected: envelope [5, 50, 50], volume 4500 mm³, open holes 0.

## V — The same part, asked in different ways

**V01 — Terse** · expect `pass`
> plate 70x50x4mm aluminium, 4x 4mm holes on a 56x36mm rectangle, no load
Expected: envelope [4, 50, 70], volume 13799 mm³, open holes 4.

**V02 — Casual with typos** · expect `pass`
> yo i need a lil aluminum plate, like 70 by 50 and 4 thick (mm), with a 4mm hole near each corner - the holes are 56 apart one way and 36 the other. nothing heavy goes on it
Expected: envelope [4, 50, 70], volume 13799 mm³, open holes 4.

**V03 — Spec sheet** · expect `pass`
> Part: mounting plate. Material: aluminium 6061-T6. Dimensions: L = 70 mm, W = 50 mm, T = 4 mm. Features: 4x diameter 4 mm through holes on a 56 x 36 mm pattern, centred. Load: none.
Expected: envelope [4, 50, 70], volume 13799 mm³, open holes 4.

**V04 — Centimetres** · expect `pass`
> An aluminium plate 7 cm long, 5 cm wide and 0.4 cm thick, with four 4 mm holes on a 5.6 cm by 3.6 cm rectangle centred on the plate. It carries no load, so there is no load case.
Expected: envelope [4, 50, 70], volume 13799 mm³, open holes 4.

**V05 — Holes described first** · expect `pass`
> Four 4 mm holes, one near each corner, with their centres on a 56 mm by 36 mm rectangle, go through an aluminium plate that is 70 mm long, 50 mm wide and 4 mm thick. It carries no load, so there is no load case.
Expected: envelope [4, 50, 70], volume 13799 mm³, open holes 4.

**V06 — Inches** · expect `pass`
> A steel plate 3 inches long, 2 inches wide and 0.25 inches thick with a 0.5 inch hole through the middle. It carries no load, so there is no load case.
Expected: envelope [6.35, 50.8, 76.2], volume 23776 mm³, open holes 1.

**V07 — Everyday object name** · expect `pass`
> A PLA disc the size of a hockey puck: 76 mm across and 25 mm thick. It carries no load, so there is no load case.
Expected: envelope [25, 76, 76], volume 113411 mm³, open holes 0.

**V08 — Wordy, one fact per sentence** · expect `pass`
> I would like a cylinder. Its diameter should be 30 millimetres. Its height should be 45 millimetres. Please make it out of stainless steel. Nothing will be pushing on it.
Expected: envelope [30, 30, 45], volume 31809 mm³, open holes 0.

**V09 — Lowercase, no punctuation** · expect `pass`
> pla washer 30mm od 12mm id 3mm thick no load
Expected: envelope [3, 30, 30], volume 1781 mm³, open holes 1.

**V10 — Romanian** · expect `inspect`
> O placă de aluminiu de 70 mm lungime, 50 mm lățime și 4 mm grosime, cu patru găuri de 4 mm, câte una lângă fiecare colț, cu centrele pe un dreptunghi de 56 pe 36 mm. Nu suportă nicio sarcină.
Expected: envelope [4, 50, 70], volume 13799 mm³, open holes 4. Forge's brief-reading rules are English; this measures how far the model alone gets. A wrong part reported as PASS would be the real failure.

**V11 — No material named** · expect `pass_or_held`
> A plate 70 mm long, 50 mm wide and 4 mm thick with four 4 mm holes on a 56 mm by 36 mm rectangle. It carries no load, so there is no load case.
Expected: envelope [4, 50, 70], volume 13799 mm³, open holes 4. No material: mass cannot be computed, but nothing asks for it. The geometry must still be right.

## L — Loads, margins and limits

**L01 — Cantilever, grade named** · expect `held`
> A 6061-T6 aluminium cantilever bracket: a 60 mm long, 20 mm wide, 6 mm thick bar fixed at one end by two 5 mm bolt holes 15 mm apart near that end. A load of 150 N pushes straight down on the free end. It must have a safety factor of at least 2.
Expected: envelope [6, 20, 60], volume 6964 mm³, open holes 2. Held only for the load; no grade assumption.

**L02 — Cantilever too weak in PLA** · expect `honest_fail`
> A PLA cantilever bracket: a 60 mm long, 20 mm wide, 6 mm thick bar fixed at one end by two 5 mm bolt holes 15 mm apart near that end. A load of 150 N pushes straight down on the free end. It must have a safety factor of at least 2.
Expected: envelope [6, 20, 60], volume 6964 mm³, open holes 2. PLA cannot carry it: the margin must be reported FAIL, never PASS.

**L03 — Longer cantilever** · expect `held`
> A 6061-T6 aluminium cantilever arm 100 mm long, 25 mm wide and 8 mm thick, fixed at one end by two 6 mm bolt holes 20 mm apart near that end. A 300 N load pushes straight down on the free end. It needs a safety factor of at least 2.
Expected: envelope [8, 25, 100], volume 19548 mm³, open holes 2.

**L04 — Pin in a bearing block** · expect `held`
> A 6061-T6 aluminium bearing block 40 mm long, 30 mm wide and 20 mm tall with a 10 mm hole for a pin straight through it across its 30 mm width, through the middle. The pin carries 2000 N. The bearing stress must keep a safety factor of at least 3.
Expected: envelope [20, 30, 40], volume 21644 mm³, open holes 1.

**L05 — Mass limit that fails** · expect `honest_fail`
> A 20 mm cube of 1018 steel. It must weigh no more than 50 g. It carries no load, so there is no load case.
Expected: envelope [20, 20, 20], volume 8000 mm³, open holes 0. It weighs about 63 g: the mass limit must be reported FAIL.

**L06 — Mass limit that passes** · expect `pass`
> A PLA cube 20 mm on each side. It must weigh no more than 15 g. It carries no load, so there is no load case.
Expected: envelope [20, 20, 20], volume 8000 mm³, open holes 0.

**L07 — Height limit** · expect `pass`
> A PLA post 15 mm across and 40 mm tall on a 40 mm square base 5 mm thick, centred. The whole part must be no taller than 50 mm. It carries no load, so there is no load case.
Expected: envelope [40, 40, 45], volume 15069 mm³, open holes 0.

## X — Honesty: what Forge cannot or should not build

**X01 — No dimensions at all** · expect `honest`
> Make a washer.
Expected: envelope —, volume —, open holes —. Nothing sized: must not come back COMPLETED with numbers it invented.

**X02 — Gear (no involute teeth)** · expect `honest`
> A PLA spur gear with 20 teeth, module 2, 8 mm thick, with a 5 mm bore. It carries no load, so there is no load case.
Expected: envelope —, volume —, open holes —. Forge cannot cut gear teeth. A plain disc reported as a gear and PASS is the failure.

**X03 — Hex bolt with a thread** · expect `inspect`
> An M8 steel bolt 40 mm long with a standard hex head. It carries no load, so there is no load case.
Expected: envelope —, volume —, open holes —. Head and shank are buildable; the thread is not. Pass if built and the report does not claim a thread was checked.

**X04 — Cone** · expect `honest`
> A PLA cone 40 mm across the base and 60 mm tall, coming to a point. It carries no load, so there is no load case.
Expected: envelope —, volume —, open holes —. No cone or taper primitive in V1.

**X05 — Coil spring** · expect `honest`
> A steel compression spring: 20 mm outside diameter, 2 mm wire, 10 coils, 50 mm free length. It carries no load, so there is no load case.
Expected: envelope —, volume —, open holes —.

**X06 — Hole bigger than the part** · expect `honest`
> A 20 mm PLA cube with a 30 mm hole straight through it. It carries no load, so there is no load case.
Expected: envelope —, volume —, open holes —. Impossible: must not report PASS.

**X07 — Contradictory size limit** · expect `honest_fail`
> A PLA sphere 50 mm in diameter. The whole part must fit inside a 20 mm box. It carries no load, so there is no load case.
Expected: envelope —, volume —, open holes —. The limit contradicts the size: the limit must FAIL.

**X08 — No idea what to make** · expect `honest`
> Make me something cool.
Expected: envelope —, volume —, open holes —.

**X09 — Not a part at all** · expect `honest`
> Write me a poem about bridges.
Expected: envelope —, volume —, open holes —.

**X10 — Heart-shaped keychain** · expect `inspect`
> A PLA heart-shaped keychain 40 mm wide and 3 mm thick with a 4 mm hole near the top.
Expected: envelope —, volume —, open holes —. Approximable from discs and a turned square; inspect the shape.

**X11 — Vague load** · expect `honest`
> A PLA hook strong enough to hang a coat on.
Expected: envelope —, volume —, open holes —. No sizes and no load figure: must not complete with invented ones.

**X12 — Two separate parts** · expect `honest`
> Two separate PLA cubes, 20 mm each, 10 mm apart, not touching.
Expected: envelope —, volume —, open holes —. V1 makes one-piece parts: the one-piece gate must not pass two loose cubes.
