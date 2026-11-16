// The source's own digest, compiled in: the loader refuses a library built from other source.
// FNV-1a, 64 bits, over src/lib.rs's bytes less carriage returns, so a checkout with Windows line
// endings digests the same (forge_numeric/_native.py computes the same).
fn main() {
    let source = std::fs::read("src/lib.rs").expect("src/lib.rs");
    let mut h: u64 = 0xcbf29ce484222325;
    for b in source.into_iter().filter(|&b| b != b'\r') {
        h ^= b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    println!("cargo:rustc-env=FNUM_SOURCE={:016x}", h);
    println!("cargo:rerun-if-changed=src/lib.rs");
}
