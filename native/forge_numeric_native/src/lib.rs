//! Forge's elementary functions, compiled: `forge_numeric.vector`'s twin, bit for bit (ADR-0037).
//!
//! Each function is `forge_numeric/scalar.py`'s, operation for operation, on
//! IEEE 754 doubles: Rust never fuses a multiply and an add nor reorders a
//! sum, so these are the same bits on every machine, and the same as the
//! Python. The Python is the specification (ADR-0024: the Python core kept as
//! the specification of the compiled one); `tests/test_v2_numeric.py` holds the
//! two to each other on every platform the library is built for.
//!
//! What the Python reduces with integers (sine and cosine arguments of
//! 2^20 pi/2 or more) is not done here: such an element is written NaN and
//! counted, and the caller computes it in Python.
//!
//! Where an x86-64 processor has AVX2, `fnum_hypot` runs four elements at
//! once rather than two: the same operations, each correctly rounded, so the
//! same bits (AVX2 has no fused multiply-add, and Rust would not fuse one if
//! it had).
//!
//! The algorithms are FreeBSD's msun, from Sun's fdlibm:
//!
//!     Copyright (C) 1993, 2004 by Sun Microsystems, Inc. All rights reserved.
//!
//!     Developed at SunSoft, a Sun Microsystems, Inc. business.
//!     Permission to use, copy, modify, and distribute this software is freely
//!     granted, provided that this notice is preserved.

#![allow(
    clippy::excessive_precision,
    clippy::many_single_char_names,
    clippy::too_many_arguments,
    clippy::approx_constant,  // msun's constants, written as msun writes them
    clippy::eq_op,  // x != x is NaN's test, x - x its making, as the Python spec writes them
    clippy::assign_op_pattern,
    // Safety, for every extern function: each pointer is to n float64 (or the one u8 buffer of fnum_source) that
    // forge_numeric._native allocates, contiguous, for the call's length.
    clippy::missing_safety_doc
)]

use std::slice;

/// The interface's version: the loader refuses any other.
const ABI: u64 = 6;

#[inline(always)]
fn from_high(h: u32) -> f64 {
    f64::from_bits((h as u64) << 32)
}

#[inline(always)]
fn with_low_zero(x: f64) -> f64 {
    f64::from_bits(x.to_bits() & 0xFFFF_FFFF_0000_0000)
}

#[inline(always)]
fn exponent(x: f64) -> i64 {
    ((x.to_bits() >> 52) & 0x7FF) as i64
}

/// Python's math.frexp exponent: x = m 2^e with m in [0.5, 1) (subnormals normalised), 0 for zero.
#[inline(always)]
fn frexp_exp(x: f64) -> i64 {
    let b = x.to_bits();
    let e = ((b >> 52) & 0x7FF) as i64;
    if e == 0 {
        if x == 0.0 {
            return 0;
        }
        let y = x * 18014398509481984.0; // 2^54
        return (((y.to_bits() >> 52) & 0x7FF) as i64) - 1022 - 54;
    }
    e - 1022
}

/// Python's math.frexp: (m, e).
#[inline(always)]
fn frexp(x: f64) -> (f64, i64) {
    let b = x.to_bits();
    let e = ((b >> 52) & 0x7FF) as i64;
    if e == 0 {
        if x == 0.0 {
            return (x, 0);
        }
        let (m, e2) = frexp(x * 18014398509481984.0);
        return (m, e2 - 54);
    }
    let m = f64::from_bits((b & 0x800F_FFFF_FFFF_FFFF) | (0x3FEu64 << 52));
    (m, e - 1022)
}

/// x 2^n, correctly rounded (as C's ldexp), without double rounding in the subnormal range.
#[inline(always)]
fn ldexp(x: f64, n: i64) -> f64 {
    let mut y = x;
    let mut n = n;
    if n > 1023 {
        y *= f64::from_bits(0x7FE0_0000_0000_0000); // 2^1023
        n -= 1023;
        if n > 1023 {
            y *= f64::from_bits(0x7FE0_0000_0000_0000);
            n -= 1023;
            if n > 1023 {
                n = 1023;
            }
        }
    } else if n < -1022 {
        let step = f64::from_bits(0x0010_0000_0000_0000) * 9007199254740992.0; // 2^-1022 2^53
        y *= step;
        n += 1022 - 53;
        if n < -1022 {
            y *= step;
            n += 1022 - 53;
            if n < -1022 {
                n = -1022;
            }
        }
    }
    y * f64::from_bits(((0x3FF + n) as u64) << 52)
}

// ----------------------------------------------------------------------
// sin and cos
// ----------------------------------------------------------------------
const S1: f64 = -1.66666666666666324348e-01;
const S2: f64 = 8.33333333332248946124e-03;
const S3: f64 = -1.98412698298579493134e-04;
const S4: f64 = 2.75573137070700676789e-06;
const S5: f64 = -2.50507602534068634195e-08;
const S6: f64 = 1.58969099521155010221e-10;
const C1: f64 = 4.16666666666666019037e-02;
const C2: f64 = -1.38888888888741095749e-03;
const C3: f64 = 2.48015872894767294178e-05;
const C4: f64 = -2.75573143513906633035e-07;
const C5: f64 = 2.08757232129817482790e-09;
const C6: f64 = -1.13596475577881948265e-11;

const INVPIO2: f64 = 6.36619772367581382433e-01;
const PIO2_1: f64 = 1.57079632673412561417e00;
const PIO2_1T: f64 = 6.07710050650619224932e-11;
const PIO2_2: f64 = 6.07710050630396597660e-11;
const PIO2_2T: f64 = 2.02226624879595063154e-21;
const PIO2_3: f64 = 2.02226624871116645580e-21;
const PIO2_3T: f64 = 8.47842766036889956997e-32;
const RNINT: f64 = 6755399441055744.0;

#[inline(always)]
fn k_sin(x: f64, y: f64, iy: i32) -> f64 {
    let z = x * x;
    let w = z * z;
    let r = S2 + z * (S3 + z * S4) + z * w * (S5 + z * S6);
    let v = z * x;
    if iy == 0 {
        x + v * (S1 + z * r)
    } else {
        x - ((z * (0.5 * y - v * r) - y) - v * S1)
    }
}

#[inline(always)]
fn k_cos(x: f64, y: f64) -> f64 {
    let z = x * x;
    let w = z * z;
    let r = z * (C1 + z * (C2 + z * C3)) + w * w * (C4 + z * (C5 + z * C6));
    let hz = 0.5 * z;
    let w = 1.0 - hz;
    w + (((1.0 - w) - hz) + (z * r - x * y))
}

/// (n mod 4, head, tail) for finite |x| below MEDIUM.
#[inline(always)]
fn rem_pio2(x: f64) -> (i64, f64, f64) {
    let fn_ = (x * INVPIO2 + RNINT) - RNINT;
    let n = fn_ as i64;
    let mut r = x - fn_ * PIO2_1;
    let mut w = fn_ * PIO2_1T;
    let j = exponent(x);
    let mut y0 = r - w;
    if j - exponent(y0) > 16 {
        let t = r;
        w = fn_ * PIO2_2;
        r = t - w;
        w = fn_ * PIO2_2T - ((t - r) - w);
        y0 = r - w;
        if j - exponent(y0) > 49 {
            let t = r;
            w = fn_ * PIO2_3;
            r = t - w;
            w = fn_ * PIO2_3T - ((t - r) - w);
            y0 = r - w;
        }
    }
    let y1 = (r - y0) - w;
    (n & 3, y0, y1)
}

struct Bounds {
    pio4: f64,
    medium: f64,
    cos_one: f64,
}

#[inline(always)]
fn bounds() -> Bounds {
    Bounds {
        pio4: from_high(0x3FE9_21FC),
        medium: from_high(0x4139_21FB),
        cos_one: from_high(0x3E46_A09E),
    }
}

/// (sin, cos, deferred): deferred where |x| >= MEDIUM (the Python reduces those exactly).
#[inline(always)]
fn sincos1(x: f64, b: &Bounds) -> (f64, f64, bool) {
    let a = x.abs();
    if a < b.pio4 {
        let s = if a < 1.4901161193847656e-08 {
            x
        } else {
            k_sin(x, 0.0, 0)
        };
        let c = if a < b.cos_one { 1.0 } else { k_cos(x, 0.0) };
        return (s, c, false);
    }
    if !x.is_finite() {
        return (x - x, x - x, false);
    }
    if a >= b.medium {
        return (f64::NAN, f64::NAN, true);
    }
    let (n, y0, y1) = rem_pio2(x);
    let mut s = k_sin(y0, y1, 1);
    let mut c = k_cos(y0, y1);
    if n & 1 != 0 {
        let t = s;
        s = c;
        c = -t;
    }
    if n & 2 != 0 {
        s = -s;
        c = -c;
    }
    (s, c, false)
}

// ----------------------------------------------------------------------
// atan and atan2
// ----------------------------------------------------------------------
const ATANHI: [f64; 4] = [
    4.63647609000806093515e-01,
    7.85398163397448278999e-01,
    9.82793723247329054082e-01,
    1.57079632679489655800e00,
];
const ATANLO: [f64; 4] = [
    2.26987774529616870924e-17,
    3.06161699786838301793e-17,
    1.39033110312309984516e-17,
    6.12323399573676603587e-17,
];
const AT: [f64; 11] = [
    3.33333333333329318027e-01,
    -1.99999999998764832476e-01,
    1.42857142725034663711e-01,
    -1.11111104054623557880e-01,
    9.09088713343650656196e-02,
    -7.69187620504482999495e-02,
    6.66107313738753120669e-02,
    -5.83357013379057348645e-02,
    4.97687799461593236017e-02,
    -3.65315727442169155270e-02,
    1.62858201153657823623e-02,
];

#[inline(always)]
fn atan1(x: f64) -> f64 {
    if x != x {
        return x + x;
    }
    let a = x.abs();
    if a >= 7.378697629483820646e19 {
        let z = ATANHI[3] + ATANLO[3];
        return if x < 0.0 { -z } else { z };
    }
    let (k, t): (i32, f64);
    if a < 0.4375 {
        if a < 7.450580596923828e-09 {
            return x;
        }
        t = x;
        k = -1;
    } else if a < 1.1875 {
        if a < 0.6875 {
            k = 0;
            t = (2.0 * a - 1.0) / (2.0 + a);
        } else {
            k = 1;
            t = (a - 1.0) / (a + 1.0);
        }
    } else if a < 2.4375 {
        k = 2;
        t = (a - 1.5) / (1.0 + 1.5 * a);
    } else {
        k = 3;
        t = -1.0 / a;
    }
    let z = t * t;
    let w = z * z;
    let s1 = z * (AT[0] + w * (AT[2] + w * (AT[4] + w * (AT[6] + w * (AT[8] + w * AT[10])))));
    let s2 = w * (AT[1] + w * (AT[3] + w * (AT[5] + w * (AT[7] + w * AT[9]))));
    if k < 0 {
        return t - t * (s1 + s2);
    }
    let k = k as usize;
    let z = ATANHI[k] - ((t * (s1 + s2) - ATANLO[k]) - t);
    if x < 0.0 {
        -z
    } else {
        z
    }
}

const PI: f64 = 3.1415926535897931160e00;
const PI_LO: f64 = 1.2246467991473531772e-16;
const PIO2: f64 = 1.5707963267948965580e00;
const PIO4_: f64 = 7.8539816339744827900e-01;

#[inline(always)]
fn atan2_1(y: f64, x: f64) -> f64 {
    if x != x || y != y {
        return x + y;
    }
    if x == 1.0 {
        return atan1(y);
    }
    let mut m = (y.is_sign_negative() as i32) | ((x.is_sign_negative() as i32) << 1);
    if y == 0.0 {
        return if m < 2 {
            y
        } else if m == 2 {
            PI
        } else {
            -PI
        };
    }
    if x == 0.0 {
        return if y < 0.0 { -PIO2 } else { PIO2 };
    }
    if x.is_infinite() {
        if y.is_infinite() {
            return [PIO4_, -PIO4_, 3.0 * PIO4_, -3.0 * PIO4_][m as usize];
        }
        return [0.0, -0.0, PI, -PI][m as usize];
    }
    if y.is_infinite() {
        return if y < 0.0 { -PIO2 } else { PIO2 };
    }
    let k = frexp_exp(y) - frexp_exp(x);
    let z;
    if k > 60 {
        z = PIO2 + 0.5 * PI_LO;
        m &= 1;
    } else if x < 0.0 && k < -60 {
        z = 0.0;
    } else {
        z = atan1((y / x).abs());
    }
    match m {
        0 => z,
        1 => -z,
        2 => PI - (z - PI_LO),
        _ => (z - PI_LO) - PI,
    }
}

// ----------------------------------------------------------------------
// asin and acos
// ----------------------------------------------------------------------
const PIO2_HI: f64 = 1.57079632679489655800e00;
const PIO2_LO: f64 = 6.12323399573676603587e-17;
const PIO4_HI: f64 = 7.85398163397448278999e-01;
const PS0: f64 = 1.66666666666666657415e-01;
const PS1: f64 = -3.25565818622400915405e-01;
const PS2: f64 = 2.01212532134862925881e-01;
const PS3: f64 = -4.00555345006794114027e-02;
const PS4: f64 = 7.91534994289814532176e-04;
const PS5: f64 = 3.47933107596021167570e-05;
const QS1: f64 = -2.40339491173441421878e00;
const QS2: f64 = 2.02094576023350569471e00;
const QS3: f64 = -6.88283971605453293030e-01;
const QS4: f64 = 7.70381505559019352791e-02;

#[inline(always)]
fn rr(z: f64) -> f64 {
    let p = z * (PS0 + z * (PS1 + z * (PS2 + z * (PS3 + z * (PS4 + z * PS5)))));
    let q = 1.0 + z * (QS1 + z * (QS2 + z * (QS3 + z * QS4)));
    p / q
}

#[inline(always)]
fn asin1(x: f64) -> f64 {
    if x != x {
        return x + x;
    }
    let a = x.abs();
    if a >= 1.0 {
        if a == 1.0 {
            return x * PIO2_HI + x * PIO2_LO;
        }
        return f64::NAN;
    }
    if a < 0.5 {
        if a < 1.4901161193847656e-08 {
            return x;
        }
        return x + x * rr(x * x);
    }
    let w = 1.0 - a;
    let t = w * 0.5;
    let s = t.sqrt();
    let t = if a >= from_high(0x3FEF_3333) {
        PIO2_HI - (2.0 * (s + s * rr(t)) - PIO2_LO)
    } else {
        let w = with_low_zero(s);
        let c = (t - w * w) / (s + w);
        let r = rr(t);
        let p = 2.0 * s * r - (PIO2_LO - 2.0 * c);
        let q = PIO4_HI - 2.0 * w;
        PIO4_HI - (p - q)
    };
    if x > 0.0 {
        t
    } else {
        -t
    }
}

#[inline(always)]
fn acos1(x: f64) -> f64 {
    if x != x {
        return x + x;
    }
    let a = x.abs();
    if a >= 1.0 {
        if a == 1.0 {
            return if x > 0.0 { 0.0 } else { PI + 2.0 * PIO2_LO };
        }
        return f64::NAN;
    }
    if a < 0.5 {
        if a < from_high(0x3C60_0001) {
            return PIO2_HI + PIO2_LO;
        }
        return PIO2_HI - (x - (PIO2_LO - x * rr(x * x)));
    }
    if x < 0.0 {
        let z = (1.0 + x) * 0.5;
        let s = z.sqrt();
        let w = rr(z) * s - PIO2_LO;
        return PI - 2.0 * (s + w);
    }
    let z = (1.0 - x) * 0.5;
    let s = z.sqrt();
    let df = with_low_zero(s);
    let c = (z - df * df) / (s + df);
    let w = rr(z) * s + c;
    2.0 * (df + w)
}

// ----------------------------------------------------------------------
// exp and log
// ----------------------------------------------------------------------
const O_THRESHOLD: f64 = 7.09782712893383973096e02;
const U_THRESHOLD: f64 = -7.45133219101941108420e02;
const LN2HI: f64 = 6.93147180369123816490e-01;
const LN2LO: f64 = 1.90821492927058770002e-10;
const INVLN2: f64 = 1.44269504088896338700e00;
const P1: f64 = 1.66666666666666019037e-01;
const P2: f64 = -2.77777777770155933842e-03;
const P3: f64 = 6.61375632143793436117e-05;
const P4: f64 = -1.65339022054652515390e-06;
const P5: f64 = 4.13813679705723846039e-08;

#[inline(always)]
fn exp1(x: f64) -> f64 {
    if x != x {
        return x + x;
    }
    if x > O_THRESHOLD {
        return f64::INFINITY;
    }
    if x < U_THRESHOLD {
        return 0.0;
    }
    let a = x.abs();
    let (k, hi, lo, xr);
    if a >= from_high(0x3FD6_2E43) {
        if a < from_high(0x3FF0_A2B2) {
            if x > 0.0 {
                hi = x - LN2HI;
                lo = LN2LO;
                k = 1;
            } else {
                hi = x + LN2HI;
                lo = -LN2LO;
                k = -1;
            }
        } else {
            k = (INVLN2 * x + if x > 0.0 { 0.5 } else { -0.5 }) as i64;
            let t = k as f64;
            hi = x - t * LN2HI;
            lo = t * LN2LO;
        }
        xr = hi - lo;
    } else if a < 3.725290298461914e-09 {
        return 1.0 + x;
    } else {
        k = 0;
        hi = 0.0;
        lo = 0.0;
        xr = x;
    }
    let t = xr * xr;
    let c = xr - t * (P1 + t * (P2 + t * (P3 + t * (P4 + t * P5))));
    if k == 0 {
        return 1.0 - ((xr * c) / (c - 2.0) - xr);
    }
    let y = 1.0 - ((lo - (xr * c) / (2.0 - c)) - hi);
    ldexp(y, k)
}

const LG1: f64 = 6.666666666666735130e-01;
const LG2: f64 = 3.999999999940941908e-01;
const LG3: f64 = 2.857142874366239149e-01;
const LG4: f64 = 2.222219843214978396e-01;
const LG5: f64 = 1.818357216161805012e-01;
const LG6: f64 = 1.531383769920937332e-01;
const LG7: f64 = 1.479819860511658591e-01;

#[inline(always)]
fn log1(x: f64) -> f64 {
    if x != x {
        return x + x;
    }
    if x <= 0.0 {
        return if x == 0.0 {
            f64::NEG_INFINITY
        } else {
            f64::NAN
        };
    }
    if x.is_infinite() {
        return x;
    }
    let (m, e) = frexp(x);
    let hx = ((m * 2097152.0) as i64) - 1048576;
    let i = (hx + 0x95F64) & 0x100000;
    let k = e - 1 + (i >> 20);
    let f = ldexp(m, 1 - (i >> 20)) - 1.0;
    let dk = k as f64;
    if (0x000F_FFFF & (2 + hx)) < 3 {
        if f == 0.0 {
            return if k == 0 { 0.0 } else { dk * LN2HI + dk * LN2LO };
        }
        let r = f * f * (0.5 - 0.33333333333333333 * f);
        return if k == 0 {
            f - r
        } else {
            dk * LN2HI - ((r - dk * LN2LO) - f)
        };
    }
    let s = f / (2.0 + f);
    let z = s * s;
    let mut i = hx - 0x6147A;
    let w = z * z;
    let j = 0x6B851 - hx;
    let t1 = w * (LG2 + w * (LG4 + w * LG6));
    let t2 = z * (LG1 + w * (LG3 + w * (LG5 + w * LG7)));
    i |= j;
    let r = t2 + t1;
    if i > 0 {
        let hfsq = 0.5 * f * f;
        if k == 0 {
            return f - (hfsq - s * (hfsq + r));
        }
        return dk * LN2HI - ((hfsq - (s * (hfsq + r) + dk * LN2LO)) - f);
    }
    if k == 0 {
        return f - s * (f - r);
    }
    dk * LN2HI - ((s * (f - r) - dk * LN2LO) - f)
}

// ----------------------------------------------------------------------
// cbrt and hypot
// ----------------------------------------------------------------------
const B1: u64 = 715094163;
const B2: u64 = 696219795;
const CP0: f64 = 1.87595182427177009643;
const CP1: f64 = -1.88497979543377169875;
const CP2: f64 = 1.621429720105354466140;
const CP3: f64 = -0.758397934778766047437;
const CP4: f64 = 0.145996192886612446982;

#[inline(always)]
fn cbrt1(x: f64) -> f64 {
    if !x.is_finite() {
        return x + x;
    }
    if x == 0.0 {
        return x;
    }
    let bits = x.to_bits();
    let sign = (bits >> 32) & 0x8000_0000;
    let hx = (bits >> 32) & 0x7FFF_FFFF;
    let word = if hx < 0x0010_0000 {
        let t = x * 18014398509481984.0;
        ((t.to_bits() >> 32) & 0x7FFF_FFFF) / 3 + B2
    } else {
        hx / 3 + B1
    };
    let mut t = f64::from_bits((sign | word) << 32);
    let r = (t * t) * (t / x);
    t = t * ((CP0 + r * (CP1 + r * CP2)) + ((r * r) * r) * (CP3 + r * CP4));
    t = f64::from_bits((t.to_bits().wrapping_add(0x8000_0000)) & 0xFFFF_FFFF_C000_0000);
    let s = t * t;
    let r = x / s;
    let w = t + t;
    let r = (r - t) / (w + r);
    t + t * r
}

// ----------------------------------------------------------------------
// The C interface: element by element over contiguous float64 arrays
// ----------------------------------------------------------------------
#[no_mangle]
pub extern "C" fn fnum_abi() -> u64 {
    ABI
}

/// The source's digest, as `src/lib.rs`'s FNV-1a (build.rs): written into `out` (16 hex digits).
#[no_mangle]
pub unsafe extern "C" fn fnum_source(out: *mut u8) {
    let s = env!("FNUM_SOURCE").as_bytes();
    let o = slice::from_raw_parts_mut(out, 16);
    o.copy_from_slice(&s[..16]);
}

macro_rules! unary {
    ($name:ident, $f:ident) => {
        #[no_mangle]
        pub unsafe extern "C" fn $name(x: *const f64, out: *mut f64, n: usize) {
            let x = slice::from_raw_parts(x, n);
            let out = slice::from_raw_parts_mut(out, n);
            for i in 0..n {
                out[i] = $f(x[i]);
            }
        }
    };
}

unary!(fnum_atan, atan1);
unary!(fnum_asin, asin1);
unary!(fnum_acos, acos1);
unary!(fnum_exp, exp1);
unary!(fnum_log, log1);
unary!(fnum_cbrt, cbrt1);

/// sin and cos together; returns how many elements were deferred (|x| >= MEDIUM: written NaN, for the caller).
#[no_mangle]
pub unsafe extern "C" fn fnum_sincos(x: *const f64, s: *mut f64, c: *mut f64, n: usize) -> usize {
    let x = slice::from_raw_parts(x, n);
    let s = slice::from_raw_parts_mut(s, n);
    let c = slice::from_raw_parts_mut(c, n);
    let b = bounds();
    let mut count = 0usize;
    for i in 0..n {
        let (si, ci, d) = sincos1(x[i], &b);
        s[i] = si;
        c[i] = ci;
        count += d as usize;
    }
    count
}

#[no_mangle]
pub unsafe extern "C" fn fnum_atan2(y: *const f64, x: *const f64, out: *mut f64, n: usize) {
    let y = slice::from_raw_parts(y, n);
    let x = slice::from_raw_parts(x, n);
    let out = slice::from_raw_parts_mut(out, n);
    for i in 0..n {
        out[i] = atan2_1(y[i], x[i]);
    }
}

const SPLIT: f64 = 134217729.0; // 2^27 + 1
const TINY: f64 = 2.2250738585072014e-308; // 2^-1022

/// (hi, lo) with hi = x*x rounded and hi + lo = x*x exactly: Dekker's product, by Veltkamp's split.
#[inline(always)]
fn two_square(x: f64) -> (f64, f64) {
    let hi = x * x;
    let t = SPLIT * x;
    let xh = t - (t - x);
    let xl = x - xh;
    (hi, ((xh * xh - hi) + 2.0 * xh * xl) + xl * xl)
}

/// CPython's hypot of any number of coordinates, every operation rounded on its own (`scalar.hypot`).
fn hypot_n(values: &[f64]) -> f64 {
    if values.iter().any(|c| c.is_infinite()) {
        return f64::INFINITY;
    }
    if values.iter().any(|c| c.is_nan()) {
        return f64::NAN;
    }
    let mut big = 0.0f64;
    for c in values {
        if c.abs() > big {
            big = c.abs();
        }
    }
    if big == 0.0 || values.len() <= 1 {
        return big;
    }
    let e = frexp_exp(big);
    if e < -1023 {
        let mut scaled = [0.0f64; 8];
        if values.len() <= 8 {
            for (k, c) in values.iter().enumerate() {
                scaled[k] = c / TINY;
            }
            return TINY * hypot_n(&scaled[..values.len()]);
        }
        let more: Vec<f64> = values.iter().map(|c| c / TINY).collect();
        return TINY * hypot_n(&more);
    }
    hypot_scaled(values, ldexp(1.0, -e))
}

/// The heart of `hypot_n`: the coordinates scaled by `scale` (2^-e, e the largest one's exponent), their
/// squares summed exactly in two parts, the root corrected once.
#[inline(always)]
fn hypot_scaled(values: &[f64], scale: f64) -> f64 {
    let (mut csum, mut frac1, mut frac2) = (1.0f64, 0.0f64, 0.0f64);
    for c in values {
        let (hi, lo) = two_square(c * scale);
        let total = csum + hi;
        frac2 += (csum - total) + hi;
        csum = total;
        frac1 += lo;
    }
    let mut h = (csum - 1.0 + (frac1 + frac2)).sqrt();
    let (hh, lh) = two_square(h);
    let total = csum - hh;
    frac2 += (csum - total) - hh;
    csum = total;
    frac1 -= lh;
    let r = csum - 1.0 + (frac1 + frac2);
    h += r / (2.0 * h);
    h / scale
}

/// `hypot_n` of N coordinates, the common case read from the bits: where every coordinate is finite and
/// the largest is a normal float below 2^1022, e is its biased exponent less 1022 and 2^-e a normal float
/// (what `frexp_exp` and `ldexp` give there, exactly); anything else goes the long way.
#[inline(always)]
fn hypot_fixed<const N: usize>(values: [f64; N]) -> f64 {
    let mut big = 0.0f64;
    for c in values {
        if c.abs() > big {
            big = c.abs();
        }
    }
    let biased = (big.to_bits() >> 52) as i64;
    // Zero, subnormal, at least 2^1022 or infinite largest, or a NaN (no NaN is <= anything): the long way.
    if (biased - 1) as u64 >= 2044 || !values.iter().all(|c| c.abs() <= big) {
        return hypot_n(&values);
    }
    hypot_scaled(&values, f64::from_bits(((2045 - biased) as u64) << 52))
}

#[inline(always)]
fn hypot2(a: f64, b: f64) -> f64 {
    hypot_fixed([a, b])
}

/// One length of two coordinates, for a number (`scalar.hypot`'s fast path).
#[no_mangle]
pub extern "C" fn fnum_hypot2_one(a: f64, b: f64) -> f64 {
    hypot2(a, b)
}

/// One length of three coordinates.
#[no_mangle]
pub extern "C" fn fnum_hypot3_one(a: f64, b: f64, c: f64) -> f64 {
    hypot_fixed([a, b, c])
}

/// 2^1022: from here up, 2^-e is not a normal float.
const BELOW: f64 = 4.4942328371557898e307;

/// Whether two coordinates' length is `hypot_fixed`'s common case, from the larger's and the second's
/// magnitudes: the larger a normal float below 2^1022, neither NaN. Without a branch.
#[inline(always)]
#[allow(clippy::manual_range_contains)]
fn common2(big: f64, ay: f64) -> bool {
    (big >= TINY) & (big < BELOW) & (ay <= big)
}

/// The length of each (x, y): CPython's hypot, every operation rounded on its own. Returns 0 (nothing is
/// deferred; the count is kept for the interface).
#[no_mangle]
pub unsafe extern "C" fn fnum_hypot(
    x: *const f64,
    y: *const f64,
    out: *mut f64,
    n: usize,
) -> usize {
    let x = slice::from_raw_parts(x, n);
    let y = slice::from_raw_parts(y, n);
    let out = slice::from_raw_parts_mut(out, n);
    #[cfg(target_arch = "x86_64")]
    {
        if std::is_x86_feature_detected!("avx2") {
            hypots_avx2(x, y, out);
            return 0;
        }
    }
    hypots(x, y, out);
    0
}

/// `fnum_hypot` without AVX2 whatever the processor has: for the tests, which hold the two to each other.
#[no_mangle]
pub unsafe extern "C" fn fnum_hypot_narrow(
    x: *const f64,
    y: *const f64,
    out: *mut f64,
    n: usize,
) -> usize {
    hypots(
        slice::from_raw_parts(x, n),
        slice::from_raw_parts(y, n),
        slice::from_raw_parts_mut(out, n),
    );
    0
}

/// `hypots`, compiled for AVX2: four lanes where SSE2 has two.
#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn hypots_avx2(x: &[f64], y: &[f64], out: &mut [f64]) {
    hypots(x, y, out);
}

/// Each length, in two passes, for speed: the first computes every element as `hypot_fixed`'s common
/// case does, without a branch (so the compiler can work several at once), and counts the elements
/// outside it; the second, where there are any, computes those the long way over what the first wrote.
#[inline(always)]
fn hypots(x: &[f64], y: &[f64], out: &mut [f64]) {
    let mut others = 0usize;
    for ((o, &a), &b) in out.iter_mut().zip(x).zip(y) {
        let (ax, ay) = (a.abs(), b.abs());
        let big = if ay > ax { ay } else { ax };
        let common = common2(big, ay);
        let scale = f64::from_bits(2045u64.wrapping_sub(big.to_bits() >> 52) << 52);
        *o = hypot_scaled(&[a, b], scale);
        others += usize::from(!common);
    }
    if others > 0 {
        for ((o, &a), &b) in out.iter_mut().zip(x).zip(y) {
            let (ax, ay) = (a.abs(), b.abs());
            let big = if ay > ax { ay } else { ax };
            if !common2(big, ay) {
                *o = hypot_n(&[a, b]);
            }
        }
    }
}

/// `a` (rows by k) times `b` (k by cols) into `out` (rows by cols), each sum from its first product,
/// left to right: the order forge_numeric's NumPy twin adds in for k <= 8 (`linear.matmul`).
#[no_mangle]
pub unsafe extern "C" fn fnum_matmul(
    a: *const f64,
    b: *const f64,
    out: *mut f64,
    rows: usize,
    k: usize,
    cols: usize,
) {
    let a = slice::from_raw_parts(a, rows * k);
    let b = slice::from_raw_parts(b, k * cols);
    let out = slice::from_raw_parts_mut(out, rows * cols);
    if k == 0 {
        out.fill(0.0);
        return;
    }
    for r in 0..rows {
        let ar = &a[r * k..(r + 1) * k];
        for c in 0..cols {
            let mut s = ar[0] * b[c];
            for t in 1..k {
                s = s + ar[t] * b[t * cols + c];
            }
            out[r * cols + c] = s;
        }
    }
}
