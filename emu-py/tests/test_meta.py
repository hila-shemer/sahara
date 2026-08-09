"""META record contract: devspec/trace.md 2.3.7's mandatory 7-key v1
catalog, in catalog order, and nothing else."""

import io

import encoding as E
import image
import trc
from helpers import halt, li128, run_cli, wbytes

META_KEYS = ("trace", "encoding", "level", "mode", "image",
            "image_sha256", "platform")


def write_img(tmp_path, name, segments, entry=E.RESET_PC):
    p = tmp_path / name
    p.write_bytes(image.build_image(segments, entry))
    return p


def _meta_lines(trc_path):
    with open(trc_path, "rb") as f:
        typ, payload = next(trc.read_records(f))
    assert typ == trc.T_META
    text = payload.decode("utf-8")
    assert text.endswith("\n")
    return text[:-1].split("\n")


def _meta_kv(trc_path):
    kv = {}
    for line in _meta_lines(trc_path):
        k, v = line.split("=", 1)
        assert k not in kv, f"duplicate META key {k}"
        kv[k] = v
    return kv


def _simple_img(tmp_path, name="meta.img"):
    prog = li128(0, 0x600D) + [halt()]
    return write_img(tmp_path, name, [(E.RESET_PC, wbytes(prog))])


def test_meta_seven_keys_in_catalog_order(tmp_path):
    img = _simple_img(tmp_path)
    t = tmp_path / "out.trc"
    r = run_cli(img, "--trace", str(t), "--trace-level", "1")
    assert r.returncode == 0, r.stderr
    lines = _meta_lines(t)
    keys = [line.split("=", 1)[0] for line in lines]
    assert keys == list(META_KEYS)


def test_meta_values(tmp_path):
    img = _simple_img(tmp_path)
    t = tmp_path / "out.trc"
    r = run_cli(img, "--trace", str(t), "--trace-level", "2")
    assert r.returncode == 0, r.stderr
    kv = _meta_kv(t)
    assert kv["trace"] == "1"
    assert kv["encoding"] == E.SPEC_VERSION
    assert kv["level"] == "2"
    assert kv["mode"] == "live"
    assert kv["image"] == str(img)
    assert kv["platform"] == "1.0-draft"
    import hashlib
    assert kv["image_sha256"] == hashlib.sha256(img.read_bytes()).hexdigest()


def test_meta_image_is_path_as_given_not_basename(tmp_path):
    (tmp_path / "sub").mkdir()
    img = _simple_img(tmp_path, name="sub/meta.img")
    t = tmp_path / "out.trc"
    rel = "sub/meta.img"
    r = run_cli(rel, "--trace", str(t), cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    kv = _meta_kv(t)
    assert kv["image"] == rel
    assert kv["image"] != "meta.img"


def test_meta_mode_flips_under_replay(tmp_path):
    img = _simple_img(tmp_path)
    live_trc = tmp_path / "live.trc"
    r = run_cli(img, "--trace", str(live_trc), "--trace-level", "1")
    assert r.returncode == 0, r.stderr

    replay_trc = tmp_path / "replay.trc"
    r = run_cli(img, "--replay", str(live_trc), "--trace", str(replay_trc),
               "--trace-level", "1")
    assert r.returncode == 0, r.stderr
    assert _meta_kv(replay_trc)["mode"] == "replay"
    assert _meta_kv(live_trc)["mode"] == "live"


def test_no_eighth_key(tmp_path):
    img = _simple_img(tmp_path)
    t = tmp_path / "out.trc"
    r = run_cli(img, "--trace", str(t), "--trace-level", "1",
               "--check-invtp", "--check-devorder", "4")
    assert r.returncode == 0, r.stderr
    kv = _meta_kv(t)
    assert set(kv.keys()) == set(META_KEYS)
