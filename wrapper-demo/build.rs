// Validate the build-time recipe manifest at compile time. A malformed or
// incomplete commands.toml fails `cargo build` rather than producing a broken
// binary — the artifact is correct-by-construction.

fn main() {
    println!("cargo:rerun-if-changed=commands.toml");

    let text = std::fs::read_to_string("commands.toml")
        .expect("commands.toml must exist at build time");
    let manifest: toml::Value =
        toml::from_str(&text).expect("commands.toml is not valid TOML");

    let wrapped = manifest
        .get("wrapped")
        .expect("commands.toml: missing [wrapped] table");
    for key in ["name", "source", "version"] {
        assert!(
            wrapped.get(key).is_some(),
            "commands.toml: [wrapped].{key} is required"
        );
    }

    let cmds = manifest
        .get("command")
        .and_then(|v| v.as_array())
        .expect("commands.toml: at least one [[command]] is required");
    assert!(
        !cmds.is_empty(),
        "commands.toml: at least one [[command]] is required"
    );
    for c in cmds {
        assert!(
            c.get("name").is_some(),
            "commands.toml: each [[command]] needs a 'name'"
        );
        assert!(
            c.get("args").and_then(|v| v.as_array()).is_some(),
            "commands.toml: each [[command]] needs an 'args' array"
        );
    }
}
