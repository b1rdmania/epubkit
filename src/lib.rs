use pyo3::prelude::*;
use pyo3::types::PyBytes;

/// Fast Floyd-Steinberg dithering on 8-bit grayscale image buffer.
/// Maps 0-255 pixels to nearest target levels with error diffusion.
#[pyfunction]
fn dither_grayscale_fs<'py>(
    py: Python<'py>,
    pixels: &[u8],
    width: usize,
    height: usize,
    levels: Vec<u8>,
) -> PyResult<Bound<'py, PyBytes>> {
    if pixels.len() != width * height {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "Buffer length ({}) does not match width * height ({} * {} = {})",
            pixels.len(),
            width,
            height,
            width * height
        )));
    }

    if levels.is_empty() {
        return Ok(PyBytes::new(py, pixels));
    }

    let out = py.allow_threads(|| {
        // Build 256-entry lookup table for nearest level
        let mut lut = [0u8; 256];
        for (i, item) in lut.iter_mut().enumerate() {
            let val = i as i32;
            let mut best_level = levels[0];
            let mut min_diff = (val - (levels[0] as i32)).abs();

            for &lvl in &levels[1..] {
                let diff = (val - (lvl as i32)).abs();
                if diff < min_diff {
                    min_diff = diff;
                    best_level = lvl;
                }
            }
            *item = best_level;
        }

        // Use i16 buffer for error propagation
        let mut buffer: Vec<i16> = Vec::with_capacity(width * height);
        for &p in pixels {
            buffer.push(p as i16);
        }

        let mut out: Vec<u8> = vec![0u8; width * height];

        for y in 0..height {
            let row_offset = y * width;
            let next_row_offset = (y + 1) * width;
            let has_next_row = y + 1 < height;

            for x in 0..width {
                let idx = row_offset + x;
                let current = buffer[idx];
                let clamped = if current < 0 {
                    0u8
                } else if current > 255 {
                    255u8
                } else {
                    current as u8
                };
                let new_val = lut[clamped as usize];
                out[idx] = new_val;

                let error = (current - (new_val as i16)) as i32;
                if error == 0 {
                    continue;
                }

                // Floyd-Steinberg distribution:
                // pixel[x+1][y]   += error * 7 / 16
                // pixel[x-1][y+1] += error * 3 / 16
                // pixel[x][y+1]   += error * 5 / 16
                // pixel[x+1][y+1] += error * 1 / 16
                if x + 1 < width {
                    buffer[idx + 1] += ((error * 7) / 16) as i16;
                }
                if has_next_row {
                    if x > 0 {
                        buffer[next_row_offset + x - 1] += ((error * 3) / 16) as i16;
                    }
                    buffer[next_row_offset + x] += ((error * 5) / 16) as i16;
                    if x + 1 < width {
                        buffer[next_row_offset + x + 1] += ((error * 1) / 16) as i16;
                    }
                }
            }
        }
        out
    });

    Ok(PyBytes::new(py, &out))
}

/// Fast OCR ligature, mojibake, smart quote, and whitespace cleaner in Rust.
#[pyfunction]
fn clean_text_fast(
    text: &str,
    normalize_quotes: bool,
    fix_whitespace: bool,
    fix_ocr: bool,
    fix_mojibake: bool,
) -> (String, usize, usize, usize, usize, usize) {
    let mut result = text.to_string();
    let mut double_spaces = 0;
    let mut ocr_fixes = 0;
    let mut quote_fixes = 0;
    let mut mojibake_fixes = 0;

    // 1. Whitespace & punctuation
    if fix_whitespace {
        // Pass 1: Multiple spaces/tabs [ \t]{2,} -> ' '
        let mut pass1 = String::with_capacity(result.len());
        let mut space_run = 0;
        for c in result.chars() {
            if c == ' ' || c == '\t' {
                space_run += 1;
            } else {
                if space_run >= 2 {
                    pass1.push(' ');
                    double_spaces += 1;
                } else if space_run == 1 {
                    pass1.push(' ');
                }
                space_run = 0;
                pass1.push(c);
            }
        }
        if space_run >= 2 {
            pass1.push(' ');
            double_spaces += 1;
        } else if space_run == 1 {
            pass1.push(' ');
        }

        // Pass 2: \s+([.,;:!?]) -> \1
        let mut pass2 = String::with_capacity(pass1.len());
        let chars: Vec<char> = pass1.chars().collect();
        let mut i = 0;
        while i < chars.len() {
            if chars[i].is_whitespace() {
                let ws_start = i;
                while i < chars.len() && chars[i].is_whitespace() {
                    i += 1;
                }
                if i < chars.len() && matches!(chars[i], '.' | ',' | ';' | ':' | '!' | '?') {
                    // Stripped whitespace before punctuation
                    double_spaces += 1;
                    pass2.push(chars[i]);
                    i += 1;
                } else {
                    for &c in &chars[ws_start..i] {
                        pass2.push(c);
                    }
                }
            } else {
                pass2.push(chars[i]);
                i += 1;
            }
        }
        result = pass2;
    }

    // 2. OCR Ligatures
    if fix_ocr {
        let ligatures: [(&str, &str); 5] = [
            ("\u{fb01}", "fi"),
            ("\u{fb02}", "fl"),
            ("\u{fb03}", "ffi"),
            ("\u{fb04}", "ffl"),
            ("\u{fb00}", "ff"),
        ];
        for (from, to) in ligatures {
            if result.contains(from) {
                let count = result.matches(from).count();
                result = result.replace(from, to);
                ocr_fixes += count;
            }
        }
    }

    // 3. Smart Quotes / Typographical characters (only when normalize_quotes and fix_ocr)
    if normalize_quotes && fix_ocr {
        let quotes: [(&str, &str); 9] = [
            ("\u{2018}", "'"),
            ("\u{2019}", "'"),
            ("\u{201c}", "\""),
            ("\u{201d}", "\""),
            ("\u{2014}", "--"),
            ("\u{2013}", "-"),
            ("\u{2026}", "..."),
            ("\u{00a0}", " "),
            ("\u{201a}", ","),
        ];
        for (from, to) in quotes {
            if result.contains(from) {
                let count = result.matches(from).count();
                result = result.replace(from, to);
                quote_fixes += count;
            }
        }
    }

    // 4. Mojibake patterns
    if fix_mojibake {
        let mojibake_table: [(&str, &str); 28] = [
            ("\u{00e2}\u{0080}\u{0099}", "\u{2019}"),
            ("\u{00e2}\u{0080}\u{0098}", "\u{2018}"),
            ("\u{00e2}\u{0080}\u{009c}", "\u{201c}"),
            ("\u{00e2}\u{0080}\u{009d}", "\u{201d}"),
            ("\u{00e2}\u{0080}\u{0094}", "\u{2014}"),
            ("\u{00e2}\u{0080}\u{0093}", "\u{2013}"),
            ("\u{00e2}\u{0080}\u{00a6}", "\u{2026}"),
            ("\u{00c3}\u{00a9}", "\u{00e9}"),
            ("\u{00c3}\u{00a8}", "\u{00e8}"),
            ("\u{00c3}\u{00ab}", "\u{00eb}"),
            ("\u{00c3}\u{00a0}", "\u{00e0}"),
            ("\u{00c3}\u{00bc}", "\u{00fc}"),
            ("\u{00c3}\u{00b1}", "\u{00f1}"),
            ("\u{00c3}\u{00a7}", "\u{00e7}"),
            ("\u{00c3}\u{00b6}", "\u{00f6}"),
            ("\u{00c3}\u{00a4}", "\u{00e4}"),
            ("\u{00c2}\u{00a3}", "\u{00a3}"),
            ("\u{00c2}\u{00bb}", "\u{00bb}"),
            ("\u{00c2}\u{00ab}", "\u{00ab}"),
            ("\u{00c2}\u{00b0}", "\u{00b0}"),
            ("\u{00c3}\u{009f}", "\u{00df}"),
            ("\u{00c3}\u{00a1}", "\u{00e1}"),
            ("\u{00c3}\u{00ad}", "\u{00ed}"),
            ("\u{00c3}\u{00b3}", "\u{00f3}"),
            ("\u{00c3}\u{00ba}", "\u{00fa}"),
            ("\u{00c3}\u{0084}", "\u{00c4}"),
            ("\u{00c3}\u{0096}", "\u{00d6}"),
            ("\u{00c3}\u{009c}", "\u{00dc}"),
        ];

        for (from, to) in mojibake_table {
            if result.contains(from) {
                let count = result.matches(from).count();
                result = result.replace(from, to);
                mojibake_fixes += count;
            }
        }
    }

    let total_fixes = double_spaces + ocr_fixes + quote_fixes + mojibake_fixes;
    (
        result,
        double_spaces,
        ocr_fixes,
        quote_fixes,
        mojibake_fixes,
        total_fixes,
    )
}

#[pymodule]
fn epubkit_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(dither_grayscale_fs, m)?)?;
    m.add_function(wrap_pyfunction!(clean_text_fast, m)?)?;
    Ok(())
}
