// SPDX-License-Identifier: MIT
//! Bounded OpenH432 carrier checks, not a generic CE firmware parser.
pub const MAX_IMAGE: usize = 0x100000 + 39;
const BASE: u32 = 0x80020000;

fn word(data: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes(data[offset..offset + 4].try_into().unwrap())
}

pub fn validate(image: &[u8]) -> Result<(), String> {
    if image.len() < 0x1000 + 68 + 39 || image.len() > MAX_IMAGE
        || &image[..7] != b"B000FF\n" {
        return Err("expected a bounded OpenH432 CE carrier, not raw U-Boot or vendor firmware".into());
    }
    let span = word(image, 11) as usize;
    if word(image, 7) != BASE || word(image, 15) != BASE
        || word(image, 19) as usize != span || span + 39 != image.len() {
        return Err("expected one contiguous carrier record at 80020000".into());
    }
    let payload = &image[27..27 + span];
    let sum = payload.iter().fold(0u32, |a, b| a.wrapping_add(*b as u32));
    if sum != word(image, 23) { return Err("carrier checksum mismatch".into()); }
    let end = 27 + span;
    if word(image, end) != 0 || word(image, end + 4) != BASE || word(image, end + 8) != 0 {
        return Err("invalid carrier entry or trailer".into());
    }
    if word(payload, 0) != 0xea0003fe || &payload[0x40..0x44] != b"ECEC"
        || word(payload, 0x44) != BASE + 0x100 || word(payload, 0x48) != 0x100 {
        return Err("invalid cold-boot ECEC/ROMHDR pointer pair or entry branch".into());
    }
    if word(payload, 0x108) != BASE || word(payload, 0x10c) != BASE + span as u32
        || word(payload, 0x110) != 1 || word(payload, 0x164) != BASE + 0x220
        || &payload[0x220..0x227] != b"nk.exe\0" {
        return Err("invalid single-module NK table".into());
    }
    if payload[0x1003] != 0xea || word(payload, 0x1040) != 0x40021000 {
        return Err("wrong U-Boot link address; RAM-only loaders cannot be flashed".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn put(b: &mut [u8], n: usize, v: u32) { b[n..n+4].copy_from_slice(&v.to_le_bytes()); }
    fn reseal(b: &mut [u8]) {
        let sum = b[27..b.len()-12].iter().fold(0u32, |a, v| a.wrapping_add(*v as u32));
        put(b, 23, sum);
    }
    fn fixture() -> Vec<u8> {
        let size = 0x1044;
        let mut b = vec![0u8; size + 39];
        b[..7].copy_from_slice(b"B000FF\n");
        for (n, v) in [(7,BASE),(11,size as u32),(15,BASE),(19,size as u32),
            (27,0xea0003fe),(27+0x44,BASE+0x100),(27+0x48,0x100),
            (27+0x108,BASE),(27+0x10c,BASE+size as u32),(27+0x110,1),
            (27+0x164,BASE+0x220),(27+0x1040,0x40021000),(27+size+4,BASE)] {
            put(&mut b,n,v);
        }
        b[27+0x40..27+0x44].copy_from_slice(b"ECEC");
        b[27+0x220..27+0x227].copy_from_slice(b"nk.exe\0");
        b[27+0x1003]=0xea;
        reseal(&mut b);
        b
    }
    #[test] fn accepts_bounded_carrier() { assert!(validate(&fixture()).is_ok()); }
    #[test] fn rejects_every_truncation() {
        let b=fixture();
        for n in 0..b.len() { assert!(validate(&b[..n]).is_err()); }
    }
    #[test] fn rejects_historical_cold_base_bug() {
        let mut b=fixture(); put(&mut b,27+0x48,0); reseal(&mut b);
        assert!(validate(&b).is_err());
    }
    #[test] fn rejects_ram_link_even_with_valid_checksum() {
        let mut b=fixture(); put(&mut b,27+0x1040,0x46000000); reseal(&mut b);
        assert!(validate(&b).is_err());
    }
    #[test] fn rejects_corruption_trailing_and_oversize() {
        let mut b=fixture(); b[100]^=1; assert!(validate(&b).is_err());
        let mut b=fixture(); b.push(0); assert!(validate(&b).is_err());
        assert!(validate(&vec![0;MAX_IMAGE+1]).is_err());
    }
    #[test] fn rejects_forged_ranges_and_entry() {
        for (n,v) in [(7,0),(11,u32::MAX),(19,0),(27+0x164,0)] {
            let mut b=fixture(); put(&mut b,n,v); reseal(&mut b);
            assert!(validate(&b).is_err());
        }
        let mut b=fixture(); let n=b.len()-8; put(&mut b,n,0);
        assert!(validate(&b).is_err());
    }
}
