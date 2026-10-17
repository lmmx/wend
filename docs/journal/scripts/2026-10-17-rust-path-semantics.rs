// std::path vs pathlib: run with `rustc docs/journal/scripts/2026-10-17-rust-path-semantics.rs -o /tmp/sem && /tmp/sem`
use std::path::{Path, PathBuf};
fn main() {
    let mut p = PathBuf::from("/x/a.txt"); p.set_extension(".json"); println!("set_extension(\".json\") on /x/a.txt -> {:?}", p);
    let mut q = PathBuf::from("/x/a.txt"); q.set_extension("json"); println!("set_extension(\"json\") on /x/a.txt -> {:?}", q);
    println!("Path::new(\"/\").parent() -> {:?}", Path::new("/").parent());
    println!("Path::new(\"a\").parent() -> {:?}", Path::new("a").parent());
    println!("Path::new(\"/x\").join(\".\") -> {:?}", Path::new("/x").join("."));
    println!("Path::new(\"/x/.\").parent() -> {:?}", Path::new("/x/.").parent());
}
