// SPDX-License-Identifier: MIT
use std::path::Path;
fn main() {
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("linux") {
        panic!("Only Linux hosts are currently supported");
    }
    for path in ["/usr/lib/x86_64-linux-gnu/libusb-1.0.so.0", "/usr/lib64/libusb-1.0.so.0"] {
        if Path::new(path).exists() {
            println!("cargo:rustc-link-arg={path}");
            return;
        }
    }
    panic!("Install libusb-1.0; supported builds use scripts/build.py");
}
