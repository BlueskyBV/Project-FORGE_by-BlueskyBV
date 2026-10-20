"""A run you can watch: a page in the run's folder that follows it live.

`forge design` opens `live.html` from the run's folder in the browser when it
starts, and rewrites it at every step: what Forge is doing, each model call
as it finishes, and -- each time the part is built -- the six-view sheet the
model itself is shown, with what failed marked on it. While the run goes the
page reloads itself every two seconds; when it ends it stops, and gains a 3D
view of the finished part you can turn with the mouse.

Everything is plain files beside the run's other artefacts -- the page, the
pictures, the mesh as a script -- so it opens from disk with no server, and
stays readable after the run as its record. Writing it can never stop a run:
every write is guarded, and a failure just leaves the last page standing.
"""

from __future__ import annotations

import base64
import html
import json
import os
import time
import webbrowser
from pathlib import Path
from typing import Any

import numpy as np

_STATE_COLOURS = {
    "completed": "#1b8a3e", "blocked": "#b26a00", "failed": "#c62828",
    "awaiting_answers": "#1565c0",
}


def _usage_said(usage: dict) -> str:
    """"81,487 tokens, about $0.65" -- what a run cost, as a person reads it."""
    if not usage:
        return ""
    total = usage.get("total_tokens") or (
        (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0))
    cost = usage.get("estimated_cost_usd") or usage.get("cost_usd")
    said = f"\u00b7 {int(total):,} tokens" if total else ""
    if cost:
        said += f", about ${float(cost):.2f}"
    return said


class LiveView:
    """Writes `live.html` and its pictures into `directory` as a run goes."""

    def __init__(self, directory: Path, brief: str, provider: str, *,
                 open_browser: bool = True) -> None:
        self.directory = Path(directory)
        self.brief = brief
        self.provider = provider
        self.started = time.time()
        self.events: list[dict[str, Any]] = []
        self.calls: list[str] = []
        self.pictures: list[tuple[str, str]] = []  # (caption, file name)
        self.finished: dict[str, Any] | None = None
        self.mesh_script: str | None = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._write()
        except OSError:
            return
        if open_browser:
            try:
                webbrowser.open(self.page.resolve().as_uri())
            except Exception:  # noqa: BLE001 - no browser is not an error
                pass

    @property
    def page(self) -> Path:
        return self.directory / "live.html"

    # -- what the run tells it -----------------------------------------
    def __call__(self, kind: str, item: Any) -> None:
        try:
            if kind == "event":
                self.events.append({
                    "at": time.time() - self.started,
                    "state": getattr(item.state, "value", str(item.state)),
                    "summary": str(item.summary)})
            elif kind == "picture":
                caption, png = item
                name = f"views-{len(self.pictures) + 1:02d}.png"
                (self.directory / name).write_bytes(png)
                self.pictures.append((str(caption), name))
            self._write()
        except Exception:  # noqa: BLE001 - a watcher never stops a run
            pass

    def call(self, request: Any, response: Any) -> None:
        """A model call finished: a provider observer."""
        try:
            self.calls.append(
                f"{request.purpose or 'call'}: {response.usage.input_tokens} in, "
                f"{response.usage.output_tokens} out, "
                f"{response.latency_seconds:.1f} s")
            self._write()
        except Exception:  # noqa: BLE001
            pass

    def finish(self, run: Any) -> None:
        """The run is over: its outcome, and the part in 3D."""
        try:
            self.finished = {
                "state": run.state.value,
                "usage": run.usage.as_dict() if hasattr(run.usage, "as_dict")
                else {},
                "reasons": [str(r) for r in getattr(
                    run.report, "release_reasons", ())][:12]
                if run.report is not None else [],
            }
            # The outcome first, on its own: a mesh that will not serialise
            # used to leave the page on disk saying the run was still going,
            # reloading every two seconds for ever.
            self._write()
        except Exception:  # noqa: BLE001
            pass
        try:
            mesh = getattr(run.report, "mesh", None) if run.report else None
            if mesh is not None:
                vertices = np.asarray(mesh.vertices, dtype="<f4")
                faces = np.asarray(mesh.faces, dtype="<u4")
                script = ("window.FORGE_MESH = " + json.dumps({
                    "v": base64.b64encode(vertices.tobytes()).decode("ascii"),
                    "f": base64.b64encode(faces.tobytes()).decode("ascii"),
                }) + ";")
                (self.directory / "live-mesh.js").write_text(script,
                                                             encoding="utf-8")
                # three.js beside it, from Forge itself: the page opens from
                # disk, where a browser will not load modules, and a viewer
                # that needs the internet is no viewer on a workshop laptop.
                here = Path(__file__).parent / "viewer"
                for name in ("three.min.js", "OrbitControls.js"):
                    source = here / name
                    if source.exists():
                        (self.directory / name).write_bytes(source.read_bytes())
                self.mesh_script = "live-mesh.js"
            self._write()
        except Exception:  # noqa: BLE001
            pass

    # -- the page -------------------------------------------------------
    def _write(self) -> None:
        text = self._render()
        temporary = self.page.with_suffix(".html.tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, self.page)

    def _render(self) -> str:
        running = self.finished is None
        state = (self.finished or {}).get("state") or (
            self.events[-1]["state"] if self.events else "starting")
        colour = _STATE_COLOURS.get(state, "#455a64")
        latest = self.pictures[-1] if self.pictures else None
        steps = "\n".join(
            f"<li><span class=t>{e['at']:6.0f}s</span> "
            f"<span class=s>{html.escape(e['state'])}</span> "
            f"{html.escape(e['summary'][:400])}</li>"
            for e in reversed(self.events[-200:]))
        calls = "\n".join(f"<li>{html.escape(c)}</li>"
                          for c in reversed(self.calls[-40:]))
        gallery = "\n".join(
            f"<figure><a href='{name}'><img src='{name}' alt=''></a>"
            f"<figcaption>{html.escape(caption)}</figcaption></figure>"
            for caption, name in reversed(self.pictures[:-1]))
        usage = (self.finished or {}).get("usage") or {}
        reasons = "".join(f"<li>{html.escape(r)}</li>"
                          for r in (self.finished or {}).get("reasons", []))
        picture = (
            f"<figure class=main><a href='{latest[1]}'><img src='{latest[1]}'"
            f" alt='the part'></a><figcaption>{html.escape(latest[0])}"
            "</figcaption></figure>" if latest else
            "<p class=wait>The part appears here as soon as it is first "
            "built.</p>")
        viewer = ""
        if self.mesh_script:
            viewer = VIEWER.replace("{{MESH}}", self.mesh_script)
        # Reloaded every two seconds while the run goes -- keeping the place
        # the reader had scrolled to, which a bare reload threw away.
        refresh = (
            "<script>(function(){try{var y=sessionStorage.getItem('forge-y');"
            "if(y!==null)window.scrollTo(0,+y);}catch(e){}"
            "setTimeout(function(){try{sessionStorage.setItem('forge-y',"
            "String(window.scrollY));}catch(e){}location.reload();},2000);"
            "})();</script>" if running else
            "<script>try{var y=sessionStorage.getItem('forge-y');"
            "if(y!==null)window.scrollTo(0,+y);sessionStorage.removeItem("
            "'forge-y');}catch(e){}</script>")
        return PAGE.format(
            title=html.escape(self.brief[:60]),
            brief=html.escape(self.brief),
            provider=html.escape(self.provider),
            state=html.escape(state.replace("_", " ")),
            colour=colour,
            started=int(self.started * 1000),
            running="true" if running else "false",
            elapsed=f"{(time.time() - self.started):.0f}",
            picture=picture,
            steps=steps,
            calls=calls or "<li>none yet</li>",
            gallery=(f"<section><h2>Earlier builds</h2><div class=gallery>"
                     f"{gallery}</div></section>" if gallery else ""),
            viewer=viewer,
            usage=html.escape(_usage_said(usage)),
            reasons=(f"<h2>Why it is not released</h2><ul>{reasons}</ul>"
                     if reasons else ""),
            refresh=refresh,
        )


PAGE = """<!doctype html>
<html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>Forge - {title}</title>
<style>
:root {{ --ink:#1f2933; --faint:#66788a; --line:#dde3ea; --paper:#f6f8fa; }}
* {{ box-sizing:border-box }}
body {{ margin:0; font:15px/1.45 system-ui,Segoe UI,sans-serif; color:var(--ink);
       background:var(--paper) }}
header {{ padding:14px 22px; background:#fff; border-bottom:1px solid var(--line);
         display:flex; gap:18px; align-items:center; flex-wrap:wrap }}
header h1 {{ margin:0; font-size:18px }}
.badge {{ padding:3px 10px; border-radius:12px; color:#fff; background:{colour};
         font-weight:600; text-transform:uppercase; font-size:12px }}
.meta {{ color:var(--faint); font-size:13px }}
main {{ display:grid; grid-template-columns:minmax(0,3fr) minmax(280px,1.2fr);
       gap:18px; padding:18px 22px }}
@media (max-width:900px) {{ main {{ grid-template-columns:1fr }} }}
section {{ background:#fff; border:1px solid var(--line); border-radius:8px;
          padding:14px 16px; min-width:0 }}
h2 {{ font-size:14px; margin:4px 0 10px; color:var(--faint);
     text-transform:uppercase; letter-spacing:.04em }}
.brief {{ white-space:pre-wrap; font-size:13px; color:#334; max-height:9em;
         overflow:auto }}
figure {{ margin:0 }}
figure.main img {{ width:100%; height:auto; border:1px solid var(--line);
                  border-radius:6px; background:#fff }}
figcaption {{ color:var(--faint); font-size:13px; margin-top:6px }}
.gallery {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr));
           gap:10px }}
.gallery img {{ width:100%; border:1px solid var(--line); border-radius:4px }}
ol, ul {{ margin:0; padding-left:18px }}
.steps {{ list-style:none; padding:0; max-height:60vh; overflow:auto;
         font-size:13px }}
.steps li {{ padding:4px 0; border-bottom:1px solid #f0f2f5 }}
.t {{ color:var(--faint); font-variant-numeric:tabular-nums }}
.s {{ font-weight:600; color:#3d5a80 }}
.calls {{ font-size:12px; color:#334 }}
.wait {{ color:var(--faint); padding:40px 0; text-align:center }}
#viewer {{ width:100%; height:520px; border:1px solid var(--line);
          border-radius:6px; background:#eef2f6 }}
</style></head>
<body>
<header><h1>Forge</h1><span class=badge>{state}</span>
<span class=meta>{provider} &middot; <span id=clock>{elapsed}</span> s
{usage}</span></header>
<main>
<div style="display:grid;gap:18px;min-width:0">
<section><h2>The part as built</h2>{picture}</section>
{viewer}
{gallery}
</div>
<div style="display:grid;gap:18px;align-content:start;min-width:0">
<section><h2>Brief</h2><div class=brief>{brief}</div>{reasons}</section>
<section><h2>Steps</h2><ul class=steps>{steps}</ul></section>
<section><h2>Model calls</h2><ul class=calls>{calls}</ul></section>
</div>
</main>
<script>
(function(){{ if(!{running}) return; var s={started};
 var el=document.getElementById('clock');
 setInterval(function(){{ el.textContent=Math.round((Date.now()-s)/1000); }},1000);
}})();
</script>
{refresh}
</body></html>
"""

VIEWER = """<section><h2>3D view &mdash; drag to turn, right-drag to move,
scroll to zoom</h2>
<div id=viewer><p id=viewer-note class=wait>Loading the 3D view&hellip;</p></div>
</section>
<script src="{{MESH}}"></script>
<script src="three.min.js"></script>
<script src="OrbitControls.js"></script>
<script>
(function () {
  var box = document.getElementById('viewer');
  var note = document.getElementById('viewer-note');
  function say(text) { note.textContent = text; }
  if (!window.THREE || !THREE.OrbitControls || !window.FORGE_MESH) {
    say('The 3D view could not load here; the pictures above and the STL in '
        + 'this folder show the same part.');
    return;
  }
  try {
    var renderer = new THREE.WebGLRenderer({antialias: true});
  } catch (e) {
    say('This browser cannot draw in 3D (WebGL is off); the pictures above '
        + 'and the STL in this folder show the same part.');
    return;
  }
  function bytes(b64) { var s = atob(b64), a = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) a[i] = s.charCodeAt(i); return a.buffer; }
  var m = window.FORGE_MESH;
  var geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position',
    new THREE.BufferAttribute(new Float32Array(bytes(m.v)), 3));
  geometry.setIndex(new THREE.BufferAttribute(new Uint32Array(bytes(m.f)), 1));
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  var scene = new THREE.Scene(); scene.background = new THREE.Color(0xeef2f6);
  scene.add(new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
    color: 0x6f93bd, metalness: 0.15, roughness: 0.55, side: THREE.DoubleSide})));
  scene.add(new THREE.HemisphereLight(0xffffff, 0x334455, 0.55));
  var sun = new THREE.DirectionalLight(0xffffff, 0.85); sun.position.set(1, -2, 3);
  var fill = new THREE.DirectionalLight(0xffffff, 0.3); fill.position.set(-2, 1, 1);
  scene.add(fill);
  scene.add(sun);
  var r = geometry.boundingSphere.radius, c = geometry.boundingSphere.center;
  geometry.computeBoundingBox();
  var axes = new THREE.AxesHelper(r * 0.35);
  axes.position.copy(geometry.boundingBox.min); scene.add(axes);
  var camera = new THREE.PerspectiveCamera(35,
    box.clientWidth / box.clientHeight, r / 100, r * 50);
  camera.up.set(0, 0, 1);
  camera.position.set(c.x + r * 1.5, c.y - r * 1.5, c.z + r * 1.1);
  note.remove();
  renderer.setSize(box.clientWidth, box.clientHeight);
  box.appendChild(renderer.domElement);
  var controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.target.copy(c); controls.update();
  (function loop() { requestAnimationFrame(loop); renderer.render(scene, camera); })();
  window.addEventListener('resize', function () {
    camera.aspect = box.clientWidth / box.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(box.clientWidth, box.clientHeight); });
})();
</script>"""


__all__ = ["LiveView"]
