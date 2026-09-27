#![no_main]

mod real_harness;
use libfuzzer_sys::fuzz_target;

fuzz_target!(|input: Vec<u8>| {
    real_harness::buy(&input);
});
